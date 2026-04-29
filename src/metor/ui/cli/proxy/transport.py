"""Transport helpers for CLI proxy daemon and headless request flows."""

import socket
from typing import Callable, Optional

from metor.application import run_with_headless_daemon
from metor.core.api import (
    EventType,
    GetConfigCommand,
    GetConfigListCommand,
    GetSettingCommand,
    GetSettingsListCommand,
    IpcCommand,
    IpcEvent,
    SetConfigCommand,
    SetSettingCommand,
    SyncConfigCommand,
)
from metor.data import ProfileManager, SettingKey
from metor.ui import PromptAbortedError, PromptOutputSpacer, Theme
from metor.ui.cli.errors import format_safe_local_runtime_error
from metor.ui.cli.ipc import IpcRequestResult, IpcRequestSession


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

HEADLESS_CONFIG_COMMANDS: tuple[type[IpcCommand], ...] = (
    GetSettingCommand,
    SetSettingCommand,
    GetSettingsListCommand,
    GetConfigCommand,
    GetConfigListCommand,
    SetConfigCommand,
    SyncConfigCommand,
)


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

    def _should_prompt_headless_password(self, cmd: IpcCommand) -> bool:
        """
        Decides whether one offline headless request must prompt for a password.

        Args:
            cmd (IpcCommand): The offline command about to be routed.

        Returns:
            bool: True when the current request must collect a password first.
        """
        if not self._pm.supports_password_auth():
            return False

        if not isinstance(cmd, HEADLESS_CONFIG_COMMANDS):
            return True

        return self._pm.config.get_bool(SettingKey.REQUIRE_LOCAL_AUTH)

    def request_ipc(self, cmd: IpcCommand, wait_for_response: bool = True) -> str:
        """
        Routes one command to the active daemon or a temporary headless instance.

        Args:
            cmd (IpcCommand): The outbound command DTO.
            wait_for_response (bool): Whether to block for one response.

        Returns:
            str: The formatted CLI response.
        """
        result: IpcRequestResult = self.request_ipc_result(cmd, wait_for_response)
        rendered: str
        if result.event is not None:
            rendered = self._format_event(result.event, prefix_remote=True)
        else:
            message: str = result.message or 'Command executed successfully.'
            rendered = self._prefix_remote(message)

        spacer = PromptOutputSpacer(result.insert_leading_blank_line)
        return spacer.format(rendered)

    def request_ipc_result(
        self,
        cmd: IpcCommand,
        wait_for_response: bool = True,
    ) -> IpcRequestResult:
        """
        Routes one command and returns the raw typed result before CLI formatting.

        Args:
            cmd (IpcCommand): The outbound command DTO.
            wait_for_response (bool): Whether to block for one response.

        Returns:
            IpcRequestResult: The typed raw response payload.
        """
        try:
            port: Optional[int] = self._pm.get_daemon_port()

            if not port:
                if self._is_remote:
                    return IpcRequestResult(
                        message=(
                            f'Cannot reach remote Daemon on port '
                            f'{Theme.YELLOW}{self._pm.get_static_port()}{Theme.RESET}. '
                            'Did you forget the SSH tunnel?'
                        )
                    )

                password: Optional[str] = None
                prompted_for_password: bool = False
                if self._should_prompt_headless_password(cmd):
                    password = self._prompt_password()
                    prompted_for_password = True
                    if password is None:
                        return IpcRequestResult(
                            message='Aborted.',
                            insert_leading_blank_line=True,
                            auth_incomplete=True,
                        )

                headless_result: str | IpcRequestResult = run_with_headless_daemon(
                    self._pm,
                    password,
                    lambda resolved_port: self.send_to_port_result(
                        resolved_port,
                        cmd,
                        wait_for_response,
                    ),
                )

                if isinstance(headless_result, IpcRequestResult):
                    result: IpcRequestResult = headless_result
                else:
                    result = IpcRequestResult(message=headless_result)

                return IpcRequestResult(
                    event=result.event,
                    message=result.message,
                    insert_leading_blank_line=(
                        prompted_for_password or result.insert_leading_blank_line
                    ),
                    auth_incomplete=result.auth_incomplete,
                )

            return self.send_to_port_result(port, cmd, wait_for_response)
        except PromptAbortedError:
            return IpcRequestResult(message='Aborted.', auth_incomplete=True)
        except ValueError as exc:
            return IpcRequestResult(
                message=format_safe_local_runtime_error(exc),
            )

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
                if self._should_prompt_headless_password(cmd):
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
        except ValueError:
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
        except ValueError as exc:
            return str(exc)

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
        result: IpcRequestResult = self.send_to_port_result(
            port,
            cmd,
            wait_for_response,
        )
        rendered: str
        if result.event is not None:
            rendered = self._format_event(
                result.event,
                prefix_remote=prefix_remote,
            )
        else:
            message: str = result.message or 'Command executed successfully.'
            if prefix_remote:
                rendered = self._prefix_remote(message)
            else:
                rendered = message

        spacer = PromptOutputSpacer(result.insert_leading_blank_line)
        return spacer.format(rendered)

    def send_to_port_result(
        self,
        port: int,
        cmd: IpcCommand,
        wait_for_response: bool,
    ) -> IpcRequestResult:
        """
        Executes the TCP transmission and returns the raw typed request result.

        Args:
            port (int): The target IPC socket port.
            cmd (IpcCommand): The outbound DTO.
            wait_for_response (bool): Whether to await one response.

        Returns:
            IpcRequestResult: The raw terminal response payload.
        """
        try:
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
            return session.execute_result(port, cmd, wait_for_response)
        except PromptAbortedError:
            return IpcRequestResult(message='Aborted.', auth_incomplete=True)
        except ValueError as exc:
            return IpcRequestResult(message=str(exc))
        except Exception:
            return IpcRequestResult(message='Failed to communicate with the daemon.')

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
