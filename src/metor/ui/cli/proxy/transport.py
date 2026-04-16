"""Transport helpers for CLI proxy daemon and headless request flows."""

import socket
from typing import Callable, Optional

from metor.application import run_with_headless_daemon
from metor.core.api import (
    EventType,
    GetConfigCommand,
    GetSettingCommand,
    IpcCommand,
    IpcEvent,
    SetConfigCommand,
    SetSettingCommand,
    SyncConfigCommand,
)
from metor.data.profile import ProfileManager
from metor.ui import PromptAbortedError, Theme
from metor.ui.cli.ipc import IpcRequestSession


CLI_ASYNC_EVENT_TYPES: set[EventType] = {
    EventType.ACK,
    EventType.AUTO_FALLBACK_QUEUED,
    EventType.AUTO_RECONNECT_SCHEDULED,
    EventType.CONNECTED,
    EventType.CONNECTION_AUTO_ACCEPTED,
    EventType.CONNECTION_CONNECTING,
    EventType.CONNECTION_FAILED,
    EventType.CONNECTION_PENDING,
    EventType.CONNECTION_REJECTED,
    EventType.CONNECTION_RETRY,
    EventType.CONNECTIONS_STATE,
    EventType.CONTACT_REMOVED,
    EventType.DISCONNECTED,
    EventType.DROP_FAILED,
    EventType.FALLBACK_SUCCESS,
    EventType.INBOX_NOTIFICATION,
    EventType.INCOMING_CONNECTION,
    EventType.INIT,
    EventType.NO_PENDING_LIVE_MSGS,
    EventType.PENDING_CONNECTION_EXPIRED,
    EventType.REMOTE_MSG,
    EventType.RENAME_SUCCESS,
    EventType.RETUNNEL_FAILED,
    EventType.RETUNNEL_INITIATED,
    EventType.RETUNNEL_SUCCESS,
    EventType.SWITCH_SUCCESS,
}


class CliProxyTransport:
    """Executes IPC and local headless request flows for the CLI proxy."""

    def __init__(
        self,
        pm: ProfileManager,
        *,
        is_remote: bool,
        prompt_password: Callable[..., Optional[str]],
        prefix_remote: Callable[[str], str],
        format_event: Callable[..., str],
        send_socket_command: Callable[[socket.socket, IpcCommand], None],
    ) -> None:
        """
        Initializes the request transport helper.

        Args:
            pm (ProfileManager): The active profile configuration.
            is_remote (bool): Whether the active profile is remote.
            prompt_password (Callable[..., Optional[str]]): Password prompt callback.
            prefix_remote (Callable[[str], str]): Remote-prefix renderer callback.
            format_event (Callable[..., str]): IPC event renderer callback.
            send_socket_command (Callable[[socket.socket, IpcCommand], None]): Socket serializer callback.

        Returns:
            None
        """
        self._pm = pm
        self._is_remote = is_remote
        self._prompt_password = prompt_password
        self._prefix_remote = prefix_remote
        self._format_event = format_event
        self._send_socket_command = send_socket_command

    def request_ipc(self, cmd: IpcCommand, wait_for_response: bool = True) -> str:
        """
        Routes one command to the active daemon or a temporary headless instance.

        Args:
            cmd (IpcCommand): The outbound command DTO.
            wait_for_response (bool): Whether to block for one response.

        Returns:
            str: The formatted CLI response.
        """
        try:
            port: Optional[int] = self._pm.get_daemon_port()

            if not port:
                if self._is_remote:
                    return self._prefix_remote(
                        f'Cannot reach remote Daemon on port '
                        f'{Theme.YELLOW}{self._pm.get_static_port()}{Theme.RESET}. '
                        'Did you forget the SSH tunnel?'
                    )

                password: Optional[str] = None
                if self._pm.supports_password_auth() and not isinstance(
                    cmd,
                    (
                        GetSettingCommand,
                        SetSettingCommand,
                        GetConfigCommand,
                        SetConfigCommand,
                        SyncConfigCommand,
                    ),
                ):
                    password = self._prompt_password()
                    if password is None:
                        return 'Master password cannot be empty.'

                return run_with_headless_daemon(
                    self._pm,
                    password,
                    lambda resolved_port: self.send_to_port(
                        resolved_port,
                        cmd,
                        wait_for_response,
                    ),
                )

            return self.send_to_port(port, cmd, wait_for_response)
        except PromptAbortedError:
            return self._prefix_remote('Aborted.')

    def request_ipc_event(self, cmd: IpcCommand) -> Optional[IpcEvent]:
        """
        Routes one command to the active daemon and returns the terminal typed event.

        Args:
            cmd (IpcCommand): The outbound command DTO.

        Returns:
            Optional[IpcEvent]: The terminal typed event, if one was received.
        """
        try:
            port: Optional[int] = self._pm.get_daemon_port()

            if not port:
                if self._is_remote:
                    return None

                password: Optional[str] = None
                if self._pm.supports_password_auth() and not isinstance(
                    cmd,
                    (
                        GetSettingCommand,
                        SetSettingCommand,
                        GetConfigCommand,
                        SetConfigCommand,
                        SyncConfigCommand,
                    ),
                ):
                    password = self._prompt_password()
                    if password is None:
                        return None

                return run_with_headless_daemon(
                    self._pm,
                    password,
                    lambda resolved_port: self.send_to_port_event(resolved_port, cmd),
                )

            return self.send_to_port_event(port, cmd)
        except PromptAbortedError:
            return None

    def request_local_headless(
        self,
        cmd: IpcCommand,
        wait_for_response: bool = True,
    ) -> str:
        """
        Routes one host-local command through the ephemeral headless daemon.

        Args:
            cmd (IpcCommand): The local command DTO.
            wait_for_response (bool): Whether to await one terminal response.

        Returns:
            str: The formatted local response.
        """
        try:
            return run_with_headless_daemon(
                self._pm,
                None,
                lambda port: self.send_to_port(
                    port,
                    cmd,
                    wait_for_response,
                    prefix_remote=False,
                ),
            )
        except PromptAbortedError:
            return 'Aborted.'

    def send_to_port(
        self,
        port: int,
        cmd: IpcCommand,
        wait_for_response: bool,
        *,
        prefix_remote: bool = True,
    ) -> str:
        """
        Executes the TCP socket transmission and parses the strict JSON response.

        Args:
            port (int): The target IPC socket port.
            cmd (IpcCommand): The outbound DTO.
            wait_for_response (bool): Whether to await one response.
            prefix_remote (bool): Whether to mark the output as remote.

        Returns:
            str: The formatted terminal output.
        """
        try:
            session = IpcRequestSession(
                self._pm,
                async_event_types=CLI_ASYNC_EVENT_TYPES,
                format_event=lambda event: self._format_event(
                    event,
                    prefix_remote=prefix_remote,
                ),
                format_message=(
                    self._prefix_remote if prefix_remote else (lambda text: text)
                ),
                prompt_password=self._prompt_password,
                send_socket_command=self._send_socket_command,
            )
            return session.execute(port, cmd, wait_for_response)
        except PromptAbortedError:
            if prefix_remote:
                return self._prefix_remote('Aborted.')
            return 'Aborted.'
        except ValueError as exc:
            if prefix_remote:
                return self._prefix_remote(str(exc))
            return str(exc)
        except Exception:
            if prefix_remote:
                return self._prefix_remote('Failed to communicate with the daemon.')
            return 'Failed to communicate with the daemon.'

    def send_to_port_event(self, port: int, cmd: IpcCommand) -> Optional[IpcEvent]:
        """
        Executes the TCP transmission and returns the terminal typed event.

        Args:
            port (int): The target IPC socket port.
            cmd (IpcCommand): The outbound DTO.

        Returns:
            Optional[IpcEvent]: The terminal event, if one was received.
        """
        session = IpcRequestSession(
            self._pm,
            async_event_types=CLI_ASYNC_EVENT_TYPES,
            format_event=lambda event: self._format_event(
                event,
                prefix_remote=True,
            ),
            format_message=self._prefix_remote,
            prompt_password=self._prompt_password,
            send_socket_command=self._send_socket_command,
        )
        return session.execute_event(port, cmd)
