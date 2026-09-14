"""Graphical prompt bridge; workers wait while the native input loop stays live."""

from dataclasses import dataclass
import threading

from metor.client import OneUseSecretProvider, build_session_auth_proof
from metor.ui.gui.state.mailbox import Mailbox, Update


@dataclass(frozen=True)
class Prompt:
    """Non-secret prompt state carrying its activation identity."""

    generation: int
    kind: str


class Interactions:
    """Implements host and SDK auth prompts without input/getpass or UI imports."""

    def __init__(self, generation: int, mailbox: Mailbox) -> None:
        """Creates one cancellable activation-owned prompt bridge.

        Args:
            generation: GUI activation identity.
            mailbox: Bounded UI handoff.
        Returns:
            None
        """
        self.generation = generation
        self.mailbox = mailbox
        self._condition = threading.Condition()
        self._prompt: Prompt | None = None
        self._answer: str | bool | None = None
        self._answered: bool = False
        self._cancelled: bool = False
        self._startup: OneUseSecretProvider | None = None

    def startup_secret(self, provider: OneUseSecretProvider | None) -> None:
        """Transfers or clears the public host's one-use bootstrap credential.

        Args:
            provider: Host-owned single-use credential or cleanup request.
        Returns:
            None
        """
        with self._condition:
            if self._startup is not None:
                self._startup.take()
            self._startup = provider
            if self._cancelled and self._startup is not None:
                self._startup.take()
                self._startup = None

    @property
    def prompt(self) -> Prompt | None:
        """Returns a safe current prompt descriptor.

        Args:
            None
        Returns:
            Prompt | None: Pending prompt without secret data.
        """
        with self._condition:
            return self._prompt

    def answer(self, value: str | bool | None) -> None:
        """Transfers one explicit UI response to its waiting worker.

        Args:
            value: Prompt response; secrets are never sent through general events.
        Returns:
            None
        """
        with self._condition:
            if self._prompt is not None and not self._cancelled:
                self._answer = value
                self._answered = True
                self._condition.notify_all()

    def cancel(self) -> None:
        """Abandons this generation and clears any unconsumed secret.

        Args:
            None
        Returns:
            None
        """
        with self._condition:
            self._cancelled = True
            self._answer = None
            self._prompt = None
            if self._startup is not None:
                self._startup.take()
                self._startup = None
            self._condition.notify_all()

    def _ask(self, kind: str) -> str | bool | None:
        """Waits off the UI/IPC-reader thread for a graphical response.

        Args:
            kind: Safe prompt type.
        Returns:
            str | bool | None: Single-use answer or cancellation.
        """
        with self._condition:
            if self._cancelled:
                return None
            self._prompt = Prompt(self.generation, kind)
            self._answered = False
            self._condition.notify_all()
            self._condition.wait_for(lambda: self._answered or self._cancelled)
            answer = self._answer
            self._answer = None
            self._prompt = None
            return None if self._cancelled else answer

    def confirm_daemon_start(self) -> bool | None:
        """Requests actual graphical autostart consent.

        Args:
            None
        Returns:
            bool | None: Explicit start/refuse/cancel.
        """
        result = self._ask('start')
        return result if isinstance(result, bool) else None

    def request_session_auth_secret(self) -> str | None:
        """Requests a graphical password without retaining it after handoff.

        Args:
            None
        Returns:
            str | None: Credential or cancellation.
        """
        result = self._ask('password')
        return result if isinstance(result, str) else None

    def get_unlock_password(self) -> str | None:
        """Supplies a cold-profile password through the SDK auth path.

        Args:
            None
        Returns:
            str | None: Credential or cancellation.
        """
        return self._password()

    def _password(self) -> str | None:
        """Consumes startup input once before asking for a fresh graphical secret.

        Args:
            None
        Returns:
            str | None: One-use credential or cancelled input.
        """
        with self._condition:
            if self._cancelled:
                return None
            provider, self._startup = self._startup, None
        secret = provider.take() if provider is not None else None
        return secret if secret is not None else self.request_session_auth_secret()

    def get_session_auth_proof(self, challenge: str, salt: str) -> str | None:
        """Derives a fresh proof solely through the public SDK.

        Args:
            challenge: Daemon-issued one-use challenge.
            salt: Daemon-issued derivation salt.
        Returns:
            str | None: Proof or cancellation.
        """
        secret = self._password()
        return (
            build_session_auth_proof(secret, challenge, salt)
            if secret is not None
            else None
        )

    def show_status(self, message: str) -> None:
        """Projects bootstrap phases without leaking arbitrary host messages.

        Args:
            message: Host bootstrap status, intentionally not forwarded verbatim.
        Returns:
            None
        """
        self.mailbox.put(Update(self.generation, 'status', status='Starting Metor…'))
