"""Authenticated IPC-session access and live-consumer ownership."""

import socket
import threading
from typing import Callable, Optional, Set

from metor.core.api import (
    AuthenticateSessionCommand,
    EventType,
    IpcCommand,
    IpcEvent,
    create_event,
)

# Local Package Imports
from ..local_auth import (
    LocalAuthTracker,
    SessionAuthAttemptResult,
    SessionAuthContext,
    SessionAuthPrompt,
)


class SessionAccessController:
    """Owns IPC authentication state and interactive-consumer registration."""

    def __init__(
        self,
        require_auth: bool,
        send_callback: Callable[[socket.socket, IpcEvent], None],
        lockout_timeout_callback: Callable[[], float],
        failure_limit_callback: Callable[[], int],
        live_consumer_available_callback: Callable[[], None],
    ) -> None:
        """Initializes session access with policy and event callbacks.

        Args:
            require_auth (bool): Whether enabled verifier contexts gate sessions.
            send_callback (Callable[[socket.socket, IpcEvent], None]): Direct IPC sender.
            lockout_timeout_callback (Callable[[], float]): Lockout-duration getter.
            failure_limit_callback (Callable[[], int]): Failure-limit getter.
            live_consumer_available_callback (Callable[[], None]): First-consumer hook.

        Returns:
            None
        """
        self._require_auth: bool = require_auth
        self._send: Callable[[socket.socket, IpcEvent], None] = send_callback
        self._lockout_timeout: Callable[[], float] = lockout_timeout_callback
        self._failure_limit: Callable[[], int] = failure_limit_callback
        self._live_consumer_available: Callable[[], None] = (
            live_consumer_available_callback
        )
        self._lock: threading.Lock = threading.Lock()
        self._authenticated_clients: Set[socket.socket] = set()
        self._session_consumers: Set[socket.socket] = set()
        self._local_auth: LocalAuthTracker = LocalAuthTracker()

    def install_context(self, context: Optional[SessionAuthContext]) -> None:
        """Installs the verifier context for the active profile runtime.

        Args:
            context (Optional[SessionAuthContext]): The active verifier context.

        Returns:
            None
        """
        self._local_auth.install_context(context)

    def requires_auth(self) -> bool:
        """Reports whether password-backed session authentication is active.

        Args:
            None

        Returns:
            bool: True when policy and a verifier context both require auth.
        """
        return self._require_auth and self._local_auth.is_enabled()

    def authenticated_recipients(self) -> Set[socket.socket]:
        """Returns a snapshot of authenticated IPC recipients.

        Args:
            None

        Returns:
            Set[socket.socket]: The authenticated client sockets.
        """
        with self._lock:
            return set(self._authenticated_clients)

    def has_session_consumers(self) -> bool:
        """Reports whether an interactive live consumer is attached.

        Args:
            None

        Returns:
            bool: True when at least one session consumer is registered.
        """
        with self._lock:
            return bool(self._session_consumers)

    def register_session_consumer(self, conn: socket.socket) -> None:
        """Registers one IPC socket as an interactive live consumer.

        Args:
            conn (socket.socket): The IPC session socket.

        Returns:
            None
        """
        with self._lock:
            had_consumers: bool = bool(self._session_consumers)
            self._session_consumers.add(conn)
        if not had_consumers:
            self._live_consumer_available()

    def disconnect(self, conn: socket.socket) -> None:
        """Clears all access state owned by a disconnected IPC socket.

        Args:
            conn (socket.socket): The disconnected client socket.

        Returns:
            None
        """
        with self._lock:
            self._authenticated_clients.discard(conn)
            self._session_consumers.discard(conn)
        self._local_auth.clear_connection(conn)

    def clear_all(self) -> None:
        """Revokes all session access and removes the verifier context.

        Args:
            None

        Returns:
            None
        """
        with self._lock:
            self._authenticated_clients.clear()
            self._session_consumers.clear()
        self._local_auth.install_context(None)

    def mark_authenticated(self, conn: socket.socket) -> None:
        """Marks one IPC client authenticated for the active runtime.

        Args:
            conn (socket.socket): The authenticated client socket.

        Returns:
            None
        """
        with self._lock:
            self._authenticated_clients.add(conn)

    def clear_connection_auth(self, conn: socket.socket) -> None:
        """Clears pending authentication state for one IPC connection.

        Args:
            conn (socket.socket): The client socket.

        Returns:
            None
        """
        self._local_auth.clear_connection(conn)

    def register_invalid_unlock(self, conn: socket.socket) -> bool:
        """Records one invalid unlock attempt under shared lockout policy.

        Args:
            conn (socket.socket): The client socket.

        Returns:
            bool: True when the client should be disconnected.
        """
        return self._local_auth.register_invalid_unlock(
            conn,
            self._lockout_timeout(),
            self._failure_limit(),
        )

    def retry_after_seconds(self) -> Optional[int]:
        """Returns the active authentication cooldown, if any.

        Args:
            None

        Returns:
            Optional[int]: Remaining whole seconds before retry is allowed.
        """
        return self._local_auth.get_retry_after_seconds()

    def authorize(
        self, cmd: IpcCommand, conn: socket.socket, runtime_unlocked: bool
    ) -> bool:
        """Applies session-auth gates before daemon command dispatch.

        Args:
            cmd (IpcCommand): The incoming typed command.
            conn (socket.socket): The requesting IPC socket.
            runtime_unlocked (bool): Whether the profile runtime is unlocked.

        Returns:
            bool: True when normal command processing may continue.
        """
        with self._lock:
            is_authenticated: bool = conn in self._authenticated_clients

        retry_after: Optional[int] = self.retry_after_seconds()
        if (
            not is_authenticated
            and retry_after is not None
            and (not runtime_unlocked or self.requires_auth())
        ):
            self._send(conn, self._rate_limited_event(retry_after))
            return False

        if self.requires_auth() and runtime_unlocked:
            if not isinstance(cmd, AuthenticateSessionCommand) and not is_authenticated:
                prompt: Optional[SessionAuthPrompt] = (
                    self._local_auth.issue_session_challenge(conn)
                )
                if prompt is not None:
                    self._send(
                        conn, self._session_auth_event(EventType.AUTH_REQUIRED, prompt)
                    )
                return False

        if not isinstance(cmd, AuthenticateSessionCommand):
            return True
        if not runtime_unlocked:
            self._send(conn, create_event(EventType.DAEMON_LOCKED))
            return False
        if not self.requires_auth() or is_authenticated:
            self.mark_authenticated(conn)
            self._send(conn, create_event(EventType.SESSION_AUTHENTICATED))
            return False

        result: SessionAuthAttemptResult = self._local_auth.verify_session_proof(
            conn,
            cmd.proof,
            self._lockout_timeout(),
            self._failure_limit(),
        )
        if result.authenticated:
            self.mark_authenticated(conn)
            self._send(conn, create_event(EventType.SESSION_AUTHENTICATED))
            return False

        retry_after = self.retry_after_seconds()
        if retry_after is not None:
            self._send(conn, self._rate_limited_event(retry_after))
            return False
        if result.retry_prompt is not None:
            self._send(
                conn,
                self._session_auth_event(
                    EventType.INVALID_PASSWORD, result.retry_prompt
                ),
            )
        else:
            self._send(conn, create_event(EventType.INVALID_PASSWORD))
        if result.should_disconnect:
            self._disconnect_client(conn)
        return False

    @staticmethod
    def _session_auth_event(
        event_type: EventType, prompt: SessionAuthPrompt
    ) -> IpcEvent:
        """Builds one session-auth challenge event.

        Args:
            event_type (EventType): The event type to create.
            prompt (SessionAuthPrompt): The challenge payload.

        Returns:
            IpcEvent: The typed authentication event.
        """
        return create_event(
            event_type,
            {'challenge': prompt.challenge, 'salt': prompt.salt},
        )

    @staticmethod
    def _rate_limited_event(retry_after: int) -> IpcEvent:
        """Builds one local-auth cooldown event.

        Args:
            retry_after (int): Remaining cooldown seconds.

        Returns:
            IpcEvent: The typed rate-limit event.
        """
        return create_event(
            EventType.LOCAL_AUTH_RATE_LIMITED,
            {'retry_after': retry_after},
        )

    @staticmethod
    def _disconnect_client(conn: socket.socket) -> None:
        """Closes one IPC socket after terminal authentication failure.

        Args:
            conn (socket.socket): The client socket.

        Returns:
            None
        """
        try:
            conn.close()
        except OSError:
            pass
