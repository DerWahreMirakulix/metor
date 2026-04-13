"""Stateful CLI-side IPC request orchestration for one command exchange."""

import json
import socket
from typing import Callable, Dict, Optional

from metor.core.api import (
    AuthenticateSessionCommand,
    AuthRequiredEvent,
    EventType,
    InvalidPasswordEvent,
    IpcCommand,
    IpcEvent,
    JsonValue,
    UnlockCommand,
)
from metor.data.profile import ProfileManager
from metor.data.settings import SettingKey
from metor.ui.session_auth import prompt_session_auth_proof
from metor.utils import Constants


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

    @staticmethod
    def _extract_session_auth_prompt(event: IpcEvent) -> Optional[tuple[str, str]]:
        """
        Extracts the daemon-issued session-auth challenge payload from one IPC event.

        Args:
            event (IpcEvent): The incoming IPC event.

        Returns:
            Optional[tuple[str, str]]: The challenge and salt, or None when unavailable.
        """
        if isinstance(event, (AuthRequiredEvent, InvalidPasswordEvent)):
            if event.challenge is not None and event.salt is not None:
                return event.challenge, event.salt

        return None

    @staticmethod
    def _read_socket_event(
        sock: socket.socket,
        buffer: bytearray,
    ) -> Optional[IpcEvent]:
        """
        Reads one strictly typed newline-delimited IPC event from the socket.

        Args:
            sock (socket.socket): The connected IPC socket.
            buffer (bytearray): The persistent receive buffer for the active socket.

        Returns:
            Optional[IpcEvent]: The decoded event, or None when the stream ends.
        """
        while b'\n' not in buffer:
            chunk: bytes = sock.recv(Constants.TCP_BUFFER_SIZE)
            if not chunk:
                return None

            buffer.extend(chunk)
            if len(buffer) > Constants.MAX_IPC_BYTES:
                raise ValueError('Daemon response exceeded the IPC size limit.')

        line_bytes, _, rest = buffer.partition(b'\n')
        buffer[:] = rest
        line: str = line_bytes.decode('utf-8')
        resp_dict: Dict[str, JsonValue] = json.loads(line)
        return IpcEvent.from_dict(resp_dict)

    def execute(self, port: int, cmd: IpcCommand, wait_for_response: bool) -> str:
        """
        Executes the socket transmission and parses the daemon response flow.

        Args:
            port (int): The target IPC socket port.
            cmd (IpcCommand): The outbound DTO.
            wait_for_response (bool): Whether to await one terminal response.

        Returns:
            str: The formatted terminal output.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(self._pm.config.get_float(SettingKey.IPC_TIMEOUT))
            sock.connect((Constants.LOCALHOST, port))
            send_failed: bool = False
            try:
                self._send_socket_command(sock, cmd)
            except OSError:
                send_failed = True

            if not wait_for_response:
                if send_failed:
                    return self._format_message(
                        'Failed to communicate with the daemon.'
                    )
                return self._format_message('Command executed successfully.')

            buffer: bytearray = bytearray()
            pending_resume_event: Optional[EventType] = None
            auth_failures: int = 0
            unlock_failures: int = 0

            while True:
                event: Optional[IpcEvent] = self._read_socket_event(sock, buffer)
                if event is None:
                    break

                session_auth_prompt: Optional[tuple[str, str]] = (
                    self._extract_session_auth_prompt(event)
                )

                if event.event_type is EventType.AUTH_REQUIRED:
                    if session_auth_prompt is None:
                        return self._format_message(
                            'Daemon session authentication challenge missing.'
                        )

                    proof: Optional[str] = prompt_session_auth_proof(
                        'Enter Master Password: ',
                        session_auth_prompt[0],
                        session_auth_prompt[1],
                    )
                    if proof is None:
                        return 'Master password cannot be empty.'

                    pending_resume_event = EventType.SESSION_AUTHENTICATED
                    self._send_socket_command(
                        sock,
                        AuthenticateSessionCommand(proof=proof),
                    )
                    continue

                if event.event_type is EventType.DAEMON_LOCKED:
                    password = self._prompt_password(
                        'Enter Master Password to unlock daemon: '
                    )
                    if password is None:
                        return 'Master password cannot be empty.'

                    pending_resume_event = EventType.DAEMON_UNLOCKED
                    self._send_socket_command(
                        sock,
                        UnlockCommand(password=password),
                    )
                    continue

                if event.event_type is EventType.INVALID_PASSWORD:
                    if pending_resume_event is EventType.SESSION_AUTHENTICATED:
                        auth_failures += 1
                        if auth_failures >= Constants.IPC_AUTH_FAILURE_LIMIT:
                            return self._format_event(event)

                        if session_auth_prompt is None:
                            return self._format_event(event)

                        proof = prompt_session_auth_proof(
                            'Enter Master Password: ',
                            session_auth_prompt[0],
                            session_auth_prompt[1],
                        )
                        if proof is None:
                            return 'Master password cannot be empty.'

                        self._send_socket_command(
                            sock,
                            AuthenticateSessionCommand(proof=proof),
                        )
                        continue

                    if pending_resume_event is EventType.DAEMON_UNLOCKED:
                        unlock_failures += 1
                        if unlock_failures >= Constants.IPC_AUTH_FAILURE_LIMIT:
                            return self._format_event(event)

                        password = self._prompt_password(
                            'Enter Master Password to unlock daemon: '
                        )
                        if password is None:
                            return 'Master password cannot be empty.'

                        self._send_socket_command(
                            sock,
                            UnlockCommand(password=password),
                        )
                        continue

                if (
                    pending_resume_event is not None
                    and event.event_type is pending_resume_event
                ):
                    pending_resume_event = None
                    self._send_socket_command(sock, cmd)
                    continue

                if event.event_type in self._async_event_types:
                    continue

                return self._format_event(event)

            if send_failed:
                return self._format_message('Failed to communicate with the daemon.')

        return self._format_message('Command executed successfully.')
