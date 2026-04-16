"""Shared UI-side helpers for daemon lock and session-auth exchanges."""

from dataclasses import dataclass
from typing import Callable, Optional

from metor.core.api import (
    AuthenticateSessionCommand,
    EventType,
    IpcCommand,
    IpcEvent,
    UnlockCommand,
)
from metor.ui.session_auth import extract_session_auth_prompt
from metor.utils import Constants


@dataclass(frozen=True)
class IpcAuthResult:
    """Describes one auth-gate handling step for a UI-side IPC exchange."""

    handled: bool
    resend_original_command: bool = False
    terminal_event: Optional[IpcEvent] = None
    terminal_message: Optional[str] = None


class IpcAuthExchange:
    """Tracks one in-flight daemon auth or unlock exchange on a persistent socket."""

    def __init__(
        self,
        *,
        prompt_session_proof: Callable[[str, str], Optional[str]],
        prompt_unlock_password: Callable[[], Optional[str]],
        send_command: Callable[[IpcCommand], None],
    ) -> None:
        """
        Initializes one reusable auth-gate exchange state machine.

        Args:
            prompt_session_proof (Callable[[str, str], Optional[str]]): Callback deriving one session-auth proof from a challenge and salt.
            prompt_unlock_password (Callable[[], Optional[str]]): Callback retrieving one daemon-unlock password.
            send_command (Callable[[IpcCommand], None]): Callback used to send follow-up IPC commands.

        Returns:
            None
        """
        self._prompt_session_proof = prompt_session_proof
        self._prompt_unlock_password = prompt_unlock_password
        self._send_command = send_command
        self._pending_resume_event: Optional[EventType] = None
        self._auth_failures: int = 0
        self._unlock_failures: int = 0

    def handle(self, event: IpcEvent) -> IpcAuthResult:
        """
        Handles one auth-related daemon event and drives the next local step.

        Args:
            event (IpcEvent): The daemon event to inspect.

        Returns:
            IpcAuthResult: The handling outcome for the caller.
        """
        session_auth_prompt: Optional[tuple[str, str]] = extract_session_auth_prompt(
            event
        )

        if event.event_type is EventType.AUTH_REQUIRED:
            if session_auth_prompt is None:
                return IpcAuthResult(
                    handled=True,
                    terminal_message='Daemon session authentication challenge missing.',
                )

            proof: Optional[str] = self._prompt_session_proof(
                session_auth_prompt[0],
                session_auth_prompt[1],
            )
            if proof is None:
                return IpcAuthResult(
                    handled=True,
                    terminal_message='Master password cannot be empty.',
                )

            self._pending_resume_event = EventType.SESSION_AUTHENTICATED
            self._send_command(AuthenticateSessionCommand(proof=proof))
            return IpcAuthResult(handled=True)

        if event.event_type is EventType.DAEMON_LOCKED:
            password: Optional[str] = self._prompt_unlock_password()
            if password is None:
                return IpcAuthResult(
                    handled=True,
                    terminal_message='Master password cannot be empty.',
                )

            self._pending_resume_event = EventType.DAEMON_UNLOCKED
            self._send_command(UnlockCommand(password=password))
            return IpcAuthResult(handled=True)

        if event.event_type is EventType.INVALID_PASSWORD:
            if self._pending_resume_event is EventType.SESSION_AUTHENTICATED:
                self._auth_failures += 1
                if self._auth_failures >= Constants.IPC_AUTH_FAILURE_LIMIT:
                    return IpcAuthResult(handled=True, terminal_event=event)

                if session_auth_prompt is None:
                    return IpcAuthResult(handled=True, terminal_event=event)

                proof = self._prompt_session_proof(
                    session_auth_prompt[0],
                    session_auth_prompt[1],
                )
                if proof is None:
                    return IpcAuthResult(
                        handled=True,
                        terminal_message='Master password cannot be empty.',
                    )

                self._send_command(AuthenticateSessionCommand(proof=proof))
                return IpcAuthResult(handled=True)

            if self._pending_resume_event is EventType.DAEMON_UNLOCKED:
                self._unlock_failures += 1
                if self._unlock_failures >= Constants.IPC_AUTH_FAILURE_LIMIT:
                    return IpcAuthResult(handled=True, terminal_event=event)

                password = self._prompt_unlock_password()
                if password is None:
                    return IpcAuthResult(
                        handled=True,
                        terminal_message='Master password cannot be empty.',
                    )

                self._send_command(UnlockCommand(password=password))
                return IpcAuthResult(handled=True)

        if (
            self._pending_resume_event is not None
            and event.event_type is self._pending_resume_event
        ):
            if event.event_type is EventType.SESSION_AUTHENTICATED:
                self._auth_failures = 0
            elif event.event_type is EventType.DAEMON_UNLOCKED:
                self._unlock_failures = 0

            self._pending_resume_event = None
            return IpcAuthResult(handled=True, resend_original_command=True)

        return IpcAuthResult(handled=False)
