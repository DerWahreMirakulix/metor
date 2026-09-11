"""Client-side authentication helpers, proof derivation, and auth-gate state machine."""

from dataclasses import dataclass
from typing import Callable, Optional, Protocol


from metor.core.api import (
    AuthenticateSessionCommand,
    AuthRequiredEvent,
    EventType,
    InvalidPasswordEvent,
    IpcCommand,
    IpcEvent,
    UnlockCommand,
)
from metor.core.auth import (
    build_session_auth_proof,
    build_session_auth_proof_from_key,
    derive_session_auth_proof_key,
    build_pin_unlock_proof,
    create_pin_verifier,
    derive_pin_verifier,
)
from metor.shared.constants import Constants

__all__ = [
    'AuthProvider',
    'IpcAuthExchange',
    'IpcAuthResult',
    'build_pin_unlock_proof',
    'build_session_auth_proof',
    'build_session_auth_proof_from_key',
    'create_pin_verifier',
    'derive_pin_verifier',
    'derive_session_auth_proof_key',
    'extract_session_auth_prompt',
]


def extract_session_auth_prompt(event: IpcEvent) -> Optional[tuple[str, str]]:
    """
    Extracts the daemon-issued challenge payload from one auth-gate event.

    Args:
        event (IpcEvent): The incoming IPC event.

    Returns:
        Optional[tuple[str, str]]: The challenge and salt, or None when unavailable.
    """
    if isinstance(event, (AuthRequiredEvent, InvalidPasswordEvent)):
        if event.challenge is not None and event.salt is not None:
            return event.challenge, event.salt

    return None


class AuthProvider(Protocol):
    """Protocol defining how an embedder supplies credentials to the client."""

    def get_unlock_password(self) -> Optional[str]:
        """
        Retrieves the master password to unlock a locked daemon.

        Args:
            None

        Returns:
            Optional[str]: Master password, or None if aborted.
        """
        ...

    def get_session_auth_proof(self, challenge: str, salt: str) -> Optional[str]:
        """
        Derives one session authentication proof for the given challenge and salt.

        Args:
            challenge (str): The daemon challenge.
            salt (str): The daemon salt.

        Returns:
            Optional[str]: Derived HMAC proof, or None if aborted.
        """
        ...


@dataclass(frozen=True)
class IpcAuthResult:
    """Describes one auth-gate handling step for a client-side IPC exchange."""

    handled: bool
    resend_original_command: bool = False
    error_event: Optional[IpcEvent] = None
    error_message: Optional[str] = None
    auth_incomplete: bool = False

    @property
    def terminal_event(self) -> Optional[IpcEvent]:
        """
        Deprecated alias for error_event.

        Args:
            None

        Returns:
            Optional[IpcEvent]: The error event if present.
        """
        return self.error_event

    @property
    def terminal_message(self) -> Optional[str]:
        """
        Deprecated alias for error_message.

        Args:
            None

        Returns:
            Optional[str]: The error message if present.
        """
        return self.error_message


class IpcAuthExchange:
    """Tracks one in-flight daemon auth or unlock exchange on a persistent socket."""

    def __init__(
        self,
        *,
        prompt_session_proof: Callable[[str, str], Optional[str]],
        prompt_unlock_password: Callable[[], Optional[str]],
        send_command: Callable[[IpcCommand], None],
        request_id: Optional[str] = None,
        failure_limit: int = Constants.IPC_AUTH_FAILURE_LIMIT,
    ) -> None:
        """
        Initializes one reusable auth-gate exchange state machine.

        Args:
            prompt_session_proof (Callable[[str, str], Optional[str]]): Derives proof from challenge and salt.
            prompt_unlock_password (Callable[[], Optional[str]]): Retrieves daemon-unlock password.
            send_command (Callable[[IpcCommand], None]): Callback used to send follow-up IPC commands.
            request_id (Optional[str]): Stable request correlation identifier for follow-up auth commands.
            failure_limit (int): Maximum invalid attempts before stopping locally.

        Returns:
            None
        """
        self._prompt_session_proof: Callable[[str, str], Optional[str]] = (
            prompt_session_proof
        )
        self._prompt_unlock_password: Callable[[], Optional[str]] = (
            prompt_unlock_password
        )
        self._send_command: Callable[[IpcCommand], None] = send_command
        self._request_id: Optional[str] = request_id
        self._failure_limit: int = max(1, failure_limit)
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
                    error_message='Daemon session authentication challenge missing.',
                )

            proof: Optional[str] = self._prompt_session_proof(
                session_auth_prompt[0],
                session_auth_prompt[1],
            )
            if proof is None:
                return IpcAuthResult(
                    handled=True,
                    error_message='Aborted.',
                    auth_incomplete=True,
                )

            self._pending_resume_event = EventType.SESSION_AUTHENTICATED
            self._send_command(
                AuthenticateSessionCommand(
                    proof=proof,
                    request_id=self._request_id,
                )
            )
            return IpcAuthResult(handled=True)

        if event.event_type is EventType.DAEMON_LOCKED:
            password: Optional[str] = self._prompt_unlock_password()
            if password is None:
                return IpcAuthResult(
                    handled=True,
                    error_message='Aborted.',
                    auth_incomplete=True,
                )

            self._pending_resume_event = EventType.DAEMON_UNLOCKED
            self._send_command(
                UnlockCommand(
                    password=password,
                    request_id=self._request_id,
                )
            )
            return IpcAuthResult(handled=True)

        if event.event_type is EventType.INVALID_PASSWORD:
            if self._pending_resume_event is EventType.SESSION_AUTHENTICATED:
                self._auth_failures += 1
                if self._auth_failures >= self._failure_limit:
                    return IpcAuthResult(handled=True, error_event=event)

                if session_auth_prompt is None:
                    return IpcAuthResult(handled=True, error_event=event)

                proof = self._prompt_session_proof(
                    session_auth_prompt[0],
                    session_auth_prompt[1],
                )
                if proof is None:
                    return IpcAuthResult(
                        handled=True,
                        error_message='Aborted.',
                        auth_incomplete=True,
                    )

                self._send_command(
                    AuthenticateSessionCommand(
                        proof=proof,
                        request_id=self._request_id,
                    )
                )
                return IpcAuthResult(handled=True)

            if self._pending_resume_event is EventType.DAEMON_UNLOCKED:
                self._unlock_failures += 1
                if self._unlock_failures >= self._failure_limit:
                    return IpcAuthResult(handled=True, error_event=event)

                password = self._prompt_unlock_password()
                if password is None:
                    return IpcAuthResult(
                        handled=True,
                        error_message='Aborted.',
                        auth_incomplete=True,
                    )

                self._send_command(
                    UnlockCommand(
                        password=password,
                        request_id=self._request_id,
                    )
                )
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
