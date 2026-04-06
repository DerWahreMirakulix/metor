"""Local daemon authentication helpers for unlock and per-session challenge flows."""

from dataclasses import dataclass
import socket
import threading
from typing import Dict, Optional

from metor.utils import (
    Constants,
    create_session_auth_challenge,
    derive_session_auth_proof_key,
    verify_session_auth_proof,
)


@dataclass(frozen=True)
class SessionAuthContext:
    """In-memory verifier context for daemon-side session authentication."""

    salt_hex: str
    proof_key: bytes


@dataclass(frozen=True)
class SessionAuthPrompt:
    """Client-facing challenge payload required to build one session-auth proof."""

    challenge: str
    salt: str


@dataclass(frozen=True)
class SessionAuthAttemptResult:
    """Result payload for one daemon-side session-auth proof attempt."""

    authenticated: bool
    should_disconnect: bool
    retry_prompt: Optional[SessionAuthPrompt] = None


def create_session_auth_context(password: str, salt: bytes) -> SessionAuthContext:
    """
    Creates one daemon-side verifier context for future session-auth challenges.

    Args:
        password (str): The master password.
        salt (bytes): The persisted profile salt.

    Returns:
        SessionAuthContext: The derived verifier context.
    """
    return SessionAuthContext(
        salt_hex=salt.hex(),
        proof_key=derive_session_auth_proof_key(password, salt),
    )


class LocalAuthTracker:
    """Tracks local IPC auth failures and per-connection session-auth challenges."""

    def __init__(self) -> None:
        """
        Initializes the local auth tracker with empty challenge and failure state.

        Args:
            None

        Returns:
            None
        """
        self._context: Optional[SessionAuthContext] = None
        self._pending_challenges: Dict[socket.socket, str] = {}
        self._failure_counts: Dict[socket.socket, int] = {}
        self._lock: threading.Lock = threading.Lock()

    def install_context(self, context: Optional[SessionAuthContext]) -> None:
        """
        Replaces the active daemon-side session-auth verifier context.

        Args:
            context (Optional[SessionAuthContext]): The new verifier context.

        Returns:
            None
        """
        with self._lock:
            self._context = context
            self._pending_challenges.clear()
            self._failure_counts.clear()

    def is_enabled(self) -> bool:
        """
        Indicates whether daemon-side password-backed session-auth is available.

        Args:
            None

        Returns:
            bool: True when a verifier context is installed.
        """
        with self._lock:
            return self._context is not None

    def clear_connection(self, conn: socket.socket) -> None:
        """
        Removes one IPC connection from tracked local-auth state.

        Args:
            conn (socket.socket): The IPC client socket.

        Returns:
            None
        """
        with self._lock:
            self._pending_challenges.pop(conn, None)
            self._failure_counts.pop(conn, None)

    def clear_all(self) -> None:
        """
        Clears all tracked local-auth state across every active connection.

        Args:
            None

        Returns:
            None
        """
        with self._lock:
            self._pending_challenges.clear()
            self._failure_counts.clear()

    def issue_session_challenge(
        self,
        conn: socket.socket,
    ) -> Optional[SessionAuthPrompt]:
        """
        Creates and stores one fresh session-auth challenge for an IPC client.

        Args:
            conn (socket.socket): The IPC client socket.

        Returns:
            Optional[SessionAuthPrompt]: The challenge payload, or None when disabled.
        """
        with self._lock:
            if self._context is None:
                return None

            challenge: str = create_session_auth_challenge()
            self._pending_challenges[conn] = challenge
            return SessionAuthPrompt(challenge=challenge, salt=self._context.salt_hex)

    def register_invalid_unlock(self, conn: socket.socket) -> bool:
        """
        Counts one invalid unlock attempt and reports whether the socket should close.

        Args:
            conn (socket.socket): The IPC client socket.

        Returns:
            bool: True when the client reached the disconnect threshold.
        """
        with self._lock:
            return self._increment_failures_locked(conn)

    def verify_session_proof(
        self,
        conn: socket.socket,
        proof: str,
    ) -> SessionAuthAttemptResult:
        """
        Verifies one client-supplied session-auth proof against the active challenge.

        Args:
            conn (socket.socket): The IPC client socket.
            proof (str): The client-supplied proof digest.

        Returns:
            SessionAuthAttemptResult: The verification result and optional retry prompt.
        """
        with self._lock:
            if self._context is None:
                return SessionAuthAttemptResult(False, False)

            challenge: Optional[str] = self._pending_challenges.get(conn)
            if challenge is None:
                new_challenge: str = create_session_auth_challenge()
                self._pending_challenges[conn] = new_challenge
                return SessionAuthAttemptResult(
                    False,
                    False,
                    SessionAuthPrompt(
                        challenge=new_challenge,
                        salt=self._context.salt_hex,
                    ),
                )

            self._pending_challenges.pop(conn, None)

            if verify_session_auth_proof(self._context.proof_key, challenge, proof):
                self._failure_counts.pop(conn, None)
                return SessionAuthAttemptResult(True, False)

            should_disconnect: bool = self._increment_failures_locked(conn)
            if should_disconnect:
                return SessionAuthAttemptResult(False, True)

            retry_challenge: str = create_session_auth_challenge()
            self._pending_challenges[conn] = retry_challenge
            return SessionAuthAttemptResult(
                False,
                False,
                SessionAuthPrompt(
                    challenge=retry_challenge,
                    salt=self._context.salt_hex,
                ),
            )

    def _increment_failures_locked(self, conn: socket.socket) -> bool:
        """
        Increments one connection's auth failure counter under the internal lock.

        Args:
            conn (socket.socket): The IPC client socket.

        Returns:
            bool: True when the disconnect threshold was reached.
        """
        attempts: int = self._failure_counts.get(conn, 0) + 1
        self._failure_counts[conn] = attempts
        return attempts >= Constants.IPC_AUTH_FAILURE_LIMIT
