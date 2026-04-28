"""Stateful CLI-side IPC request orchestration for one command exchange."""

import socket
from typing import Callable, Optional

from metor.core.api import ensure_request_id, EventType, IpcCommand, IpcEvent
from metor.data import ProfileManager, SettingKey
from metor.ui.ipc import BufferedIpcEventReader, IpcAuthExchange

# Local Package Imports
from metor.ui import get_session_auth_prompt, prompt_session_auth_proof
from metor.ui.cli.ipc.request.models import IpcRequestResult


class IpcRequestSession:
    """Executes one CLI-to-daemon IPC exchange including local-auth prompts."""

    def __init__(
        self,
        pm: ProfileManager,
        *,
        async_event_types: set[EventType],
        format_event: Callable[[IpcEvent], str],
        format_message: Callable[[str], str],
        prompt_password: Callable[[str], Optional[str]],
        send_socket_command: Callable[[socket.socket, IpcCommand], None],
    ) -> None:
        """
        Initializes one stateful IPC request session.

        Args:
            pm (ProfileManager): The active profile configuration.
            async_event_types (set[EventType]): Broadcast-only event types to ignore.
            format_event (Callable[[IpcEvent], str]): Formatter for terminal response events.
            format_message (Callable[[str], str]): Formatter for plain status strings.
            prompt_password (Callable[[str], Optional[str]]): Password prompt callback.
            send_socket_command (Callable[[socket.socket, IpcCommand], None]): Command serializer.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._async_event_types: set[EventType] = async_event_types
        self._format_event: Callable[[IpcEvent], str] = format_event
        self._format_message: Callable[[str], str] = format_message
        self._prompt_password: Callable[[str], Optional[str]] = prompt_password
        self._send_socket_command: Callable[[socket.socket, IpcCommand], None] = (
            send_socket_command
        )

    def _build_auth_exchange(
        self,
        sock: socket.socket,
        request_id: str,
    ) -> IpcAuthExchange:
        """
        Creates one reusable auth-gate state machine for the active socket.

        Args:
            sock (socket.socket): The active IPC socket.
            request_id (str): The stable request correlation identifier.

        Returns:
            IpcAuthExchange: The prepared auth-gate helper.
        """
        return IpcAuthExchange(
            prompt_session_proof=lambda challenge, salt: prompt_session_auth_proof(
                get_session_auth_prompt(self._pm),
                challenge,
                salt,
            ),
            prompt_unlock_password=lambda: self._prompt_password(
                'Enter Master Password to unlock daemon: '
            ),
            send_command=lambda command: self._send_socket_command(sock, command),
            request_id=request_id,
            failure_limit=self._pm.config.get_int(SettingKey.LOCAL_AUTH_FAILURE_LIMIT),
        )

    def execute_result(
        self,
        port: int,
        cmd: IpcCommand,
        wait_for_response: bool,
    ) -> IpcRequestResult:
        """
        Executes the socket transmission and returns the typed response result.

        Args:
            port (int): The target IPC socket port.
            cmd (IpcCommand): The outbound DTO.
            wait_for_response (bool): Whether to await one terminal response.

        Returns:
            IpcRequestResult: The typed event or plain status message.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(self._pm.config.get_float(SettingKey.IPC_TIMEOUT))
            sock.connect(('127.0.0.1', port))
            reader: BufferedIpcEventReader = BufferedIpcEventReader()
            request_id: str = ensure_request_id(cmd)
            auth_exchange: IpcAuthExchange = self._build_auth_exchange(
                sock,
                request_id,
            )
            send_failed: bool = False
            try:
                self._send_socket_command(sock, cmd)
            except OSError:
                send_failed = True

            if not wait_for_response:
                if send_failed:
                    return IpcRequestResult(
                        message='Failed to communicate with the daemon.'
                    )
                return IpcRequestResult(message='Command executed successfully.')

            while True:
                event: Optional[IpcEvent] = reader.read_from_socket(sock)
                if event is None:
                    break

                if event.request_id is not None and event.request_id != request_id:
                    continue

                auth_result = auth_exchange.handle(event)
                if auth_result.handled:
                    if auth_result.terminal_message is not None:
                        return IpcRequestResult(message=auth_result.terminal_message)
                    if auth_result.terminal_event is not None:
                        return IpcRequestResult(event=auth_result.terminal_event)
                    if auth_result.resend_original_command:
                        self._send_socket_command(sock, cmd)
                    continue

                if event.event_type in self._async_event_types:
                    continue

                return IpcRequestResult(event=event)

            if send_failed:
                return IpcRequestResult(
                    message='Failed to communicate with the daemon.'
                )

        return IpcRequestResult(message='Command executed successfully.')

    def execute(self, port: int, cmd: IpcCommand, wait_for_response: bool) -> str:
        """
        Executes the socket transmission and formats the terminal response.

        Args:
            port (int): The target IPC socket port.
            cmd (IpcCommand): The outbound DTO.
            wait_for_response (bool): Whether to await one terminal response.

        Returns:
            str: The formatted terminal output.
        """
        result: IpcRequestResult = self.execute_result(port, cmd, wait_for_response)
        if result.event is not None:
            return self._format_event(result.event)
        return self._format_message(result.message or 'Command executed successfully.')

    def execute_event(self, port: int, cmd: IpcCommand) -> Optional[IpcEvent]:
        """
        Executes one IPC request and returns the terminal event without formatting.

        Args:
            port (int): The target IPC socket port.
            cmd (IpcCommand): The outbound DTO.

        Returns:
            Optional[IpcEvent]: The terminal typed event, if one was received.
        """
        result: IpcRequestResult = self.execute_result(
            port, cmd, wait_for_response=True
        )
        return result.event
