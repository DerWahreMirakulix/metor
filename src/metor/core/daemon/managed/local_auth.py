"""Local daemon authentication helpers for unlock and per-session challenge flows."""

from dataclasses import dataclass
import math
import socket
import threading
import time
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
        self._global_failure_count: int = 0
        self._lockout_deadline_monotonic: float = 0.0
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
            self._reset_rate_limit_locked()

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
            self._reset_rate_limit_locked()

    def get_retry_after_seconds(self) -> Optional[int]:
        """
        Returns the remaining local-auth lockout time when a cooldown is active.

        Args:
            None

        Returns:
            Optional[int]: Whole seconds remaining in the active lockout window.
        """
        with self._lock:
            return self._get_retry_after_seconds_locked()

    def reset_rate_limit(self) -> None:
        """
        Clears the global local-auth failure window and any active cooldown.

        Args:
            None

        Returns:
            None
        """
        with self._lock:
            self._failure_counts.clear()
            self._pending_challenges.clear()
            self._reset_rate_limit_locked()

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

    def register_invalid_unlock(
        self,
        conn: socket.socket,
        lockout_seconds: float = 0.0,
    ) -> bool:
        """
        Counts one invalid unlock attempt and reports whether the socket should close.

        Args:
            conn (socket.socket): The IPC client socket.
            lockout_seconds (float): Global cooldown duration after repeated failures.

        Returns:
            bool: True when the client reached the disconnect threshold.
        """
        with self._lock:
            return self._increment_failures_locked(conn, lockout_seconds)

    def verify_session_proof(
        self,
        conn: socket.socket,
        proof: str,
        lockout_seconds: float = 0.0,
    ) -> SessionAuthAttemptResult:
        """
        Verifies one client-supplied session-auth proof against the active challenge.

        Args:
            conn (socket.socket): The IPC client socket.
            proof (str): The client-supplied proof digest.
            lockout_seconds (float): Global cooldown duration after repeated failures.

        Returns:
            SessionAuthAttemptResult: The verification result and optional retry prompt.
        """
        with self._lock:
            if self._context is None:
                return SessionAuthAttemptResult(False, False)

            if self._get_retry_after_seconds_locked() is not None:
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
                self._reset_rate_limit_locked()
                return SessionAuthAttemptResult(True, False)

            should_disconnect: bool = self._increment_failures_locked(
                conn,
                lockout_seconds,
            )
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

    def _get_retry_after_seconds_locked(self) -> Optional[int]:
        """
        Returns the remaining local-auth cooldown under the internal lock.

        Args:
            None

        Returns:
            Optional[int]: Whole seconds remaining in the active lockout window.
        """
        if self._lockout_deadline_monotonic <= 0.0:
            return None

        remaining: float = self._lockout_deadline_monotonic - time.monotonic()
        if remaining <= 0.0:
            self._failure_counts.clear()
            self._pending_challenges.clear()
            self._reset_rate_limit_locked()
            return None

        return max(1, math.ceil(remaining))

    def _activate_lockout_locked(self, lockout_seconds: float) -> None:
        """
        Enables the cross-connection local-auth cooldown and clears stale challenges.

        Args:
            lockout_seconds (float): The cooldown duration in seconds.

        Returns:
            None
        """
        self._failure_counts.clear()
        self._pending_challenges.clear()
        self._global_failure_count = 0
        if lockout_seconds > 0.0:
            self._lockout_deadline_monotonic = time.monotonic() + lockout_seconds

    def _reset_rate_limit_locked(self) -> None:
        """
        Clears the global local-auth cooldown state under the internal lock.

        Args:
            None

        Returns:
            None
        """
        self._global_failure_count = 0
        self._lockout_deadline_monotonic = 0.0

    def _increment_failures_locked(
        self,
        conn: socket.socket,
        lockout_seconds: float,
    ) -> bool:
        """
        Increments one connection's auth failure counter under the internal lock.

        Args:
            conn (socket.socket): The IPC client socket.
            lockout_seconds (float): Global cooldown duration after repeated failures.

        Returns:
            bool: True when the disconnect threshold was reached.
        """
        if self._get_retry_after_seconds_locked() is not None:
            return True

        attempts: int = self._failure_counts.get(conn, 0) + 1
        self._failure_counts[conn] = attempts

        if lockout_seconds <= 0.0:
            return attempts >= Constants.IPC_AUTH_FAILURE_LIMIT

        self._global_failure_count += 1
        if self._global_failure_count >= Constants.IPC_AUTH_FAILURE_LIMIT:
            self._activate_lockout_locked(lockout_seconds)
            return True

        return False
