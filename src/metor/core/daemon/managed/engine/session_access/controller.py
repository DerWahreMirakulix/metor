"""Owns authentication state and delegates its policy-specific operations."""

import socket
import threading
from typing import Callable, Optional, Set

from metor.core.api import (
    ConfigureQuickUnlockCommand,
    Delivery,
    QuickUnlockAction,
    ReauthorizeClientCommand,
    RestrictClientCommand,
    IpcCommand,
    IpcEvent,
    PendingConnectionEntry,
)
from metor.core.daemon.managed.quick_unlock import (
    QuickUnlockStorageError,
    QuickUnlockStore,
)
from .grants import PendingCallGrant

# Local Package Imports
from ...local_auth import (
    LocalAuthTracker,
    SessionAuthContext,
)
from .events import SessionEventMixin
from .policy import RestrictedSessionPolicy
from . import authorization, restriction, projection, calls


class SessionAccessController(SessionEventMixin):
    """Owns IPC authentication state and interactive-consumer registration."""

    def __init__(
        self,
        require_auth: bool,
        send_callback: Callable[[socket.socket, IpcEvent], None],
        lockout_timeout_callback: Callable[[], float],
        failure_limit_callback: Callable[[], int],
        live_consumer_available_callback: Callable[[], None],
        quick_unlock_store: Optional[QuickUnlockStore] = None,
        is_saved_contact_callback: Optional[Callable[[str], bool]] = None,
        resolve_target_callback: Optional[Callable[[str], Optional[str]]] = None,
        voice_target_callback: Optional[Callable[[str], Optional[str]]] = None,
        voice_delivery_callback: Optional[Callable[[str], Optional[Delivery]]] = None,
        inbound_voice_delivery_callback: Optional[
            Callable[[str, str], Optional[Delivery]]
        ] = None,
        live_context_callback: Optional[Callable[[str], object | None]] = None,
        voice_context_callback: Optional[
            Callable[[str, str, str], object | None]
        ] = None,
        self_destruct_requires_unlock_callback: Optional[Callable[[], bool]] = None,
        live_generation_callback: Optional[Callable[[str], Optional[int]]] = None,
        live_state_callback: Optional[Callable[[str], str]] = None,
        pending_projection_callback: Optional[
            Callable[[], list[PendingConnectionEntry]]
        ] = None,
        pending_token_callback: Optional[Callable[[str], Optional[str]]] = None,
        pending_call_callback: Optional[
            Callable[[str], tuple[socket.socket, float] | None]
        ] = None,
        active_connection_callback: Optional[
            Callable[[str], Optional[socket.socket]]
        ] = None,
    ) -> None:
        """Initializes session access with policy and event callbacks.

        Args:
            require_auth (bool): Whether enabled verifier contexts gate sessions.
            send_callback (Callable[[socket.socket, IpcEvent], None]): Direct IPC sender.
            lockout_timeout_callback (Callable[[], float]): Lockout-duration getter.
            failure_limit_callback (Callable[[], int]): Failure-limit getter.
            live_consumer_available_callback (Callable[[], None]): First-consumer hook.
            quick_unlock_store (Optional[QuickUnlockStore]): PIN verifier persistence.
            is_saved_contact_callback (Optional[Callable[[str], bool]]): Saved-peer check.
            resolve_target_callback (Optional[Callable]): Stable onion resolver.
            voice_target_callback (Optional[Callable]): Active Voice owner resolver.
            voice_delivery_callback (Optional[Callable]): Active Voice delivery
                semantics resolver.
            self_destruct_requires_unlock_callback (Optional[Callable[[], bool]]):
                Current conservative restricted-session purge policy.

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
        self._full_auth_clients: Set[socket.socket] = set()
        self._sensitive_auth_pending: dict[socket.socket, QuickUnlockAction] = {}
        self._sensitive_auth_grants: dict[
            socket.socket, tuple[QuickUnlockAction, float, int]
        ] = {}
        self._auth_runtime_generation = 0
        self._session_consumers: Set[socket.socket] = set()
        self._local_auth: LocalAuthTracker = LocalAuthTracker()
        self._quick_unlock = quick_unlock_store
        self._is_saved_contact = is_saved_contact_callback or (lambda _target: False)
        self._resolve_target = resolve_target_callback or (lambda target: target)
        self._voice_target = voice_target_callback or (lambda _msg_id: None)
        self._voice_delivery = voice_delivery_callback or (lambda _msg_id: None)
        self._inbound_voice_delivery = inbound_voice_delivery_callback or (
            lambda _onion, _msg_id: None
        )
        self._live_context = live_context_callback or (lambda _onion: None)
        self._live_generation = live_generation_callback or (lambda _onion: None)
        self._live_state = live_state_callback or (lambda _onion: 'disconnected')
        self._pending_projection = pending_projection_callback or (lambda: [])
        self._voice_context = voice_context_callback or (
            lambda _onion, _msg_id, _direction: None
        )
        self._self_destruct_requires_unlock = (
            self_destruct_requires_unlock_callback or (lambda: True)
        )
        self._restricted: dict[socket.socket, RestrictedSessionPolicy] = {}
        self._restricted_challenges: dict[socket.socket, str] = {}
        self._pin_failures: dict[socket.socket, int] = {}
        self._pin_disabled: set[socket.socket] = set()
        self._call_handles: dict[socket.socket, dict[str, PendingCallGrant]] = {}
        self._pending_call = pending_call_callback or (lambda _onion: None)
        self._pending_token = pending_token_callback
        self._active_connection = active_connection_callback or (lambda _onion: None)
        self._authorized_calls: dict[socket.socket, socket.socket] = {}
        self._accepted_calls: dict[
            socket.socket, dict[str, tuple[str, object, int]]
        ] = {}
        self._restriction_generations: dict[socket.socket, int] = {}

    def install_context(self, context: Optional[SessionAuthContext]) -> None:
        """Installs the verifier context for the active profile runtime.

        Args:
            context (Optional[SessionAuthContext]): The active verifier context.

        Returns:
            None
        """
        with self._lock:
            self._auth_runtime_generation += 1
            self._call_handles.clear()
            self._accepted_calls.clear()
            self._authorized_calls.clear()
            self._sensitive_auth_pending.clear()
            self._sensitive_auth_grants.clear()
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
            self._full_auth_clients.discard(conn)
            self._sensitive_auth_pending.pop(conn, None)
            self._sensitive_auth_grants.pop(conn, None)
            self._session_consumers.discard(conn)
            self._restricted.pop(conn, None)
            self._restricted_challenges.pop(conn, None)
            self._pin_failures.pop(conn, None)
            self._pin_disabled.discard(conn)
            self._call_handles.pop(conn, None)
            self._accepted_calls.pop(conn, None)
            self._authorized_calls.pop(conn, None)
            self._restriction_generations.pop(conn, None)
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
            self._full_auth_clients.clear()
            self._sensitive_auth_pending.clear()
            self._sensitive_auth_grants.clear()
            self._session_consumers.clear()
            self._restricted.clear()
            self._restricted_challenges.clear()
            self._pin_failures.clear()
            self._pin_disabled.clear()
            self._call_handles.clear()
            self._accepted_calls.clear()
            self._authorized_calls.clear()
            self._restriction_generations.clear()
        self._local_auth.install_context(None)

    def mark_authenticated(
        self, conn: socket.socket, *, full_password: bool = True
    ) -> None:
        """Marks one IPC client authenticated for the active runtime.

        Args:
            conn (socket.socket): The authenticated client socket.
            full_password (bool): Whether root-profile proof established the session.

        Returns:
            None
        """
        with self._lock:
            self._authenticated_clients.add(conn)
            if full_password:
                self._full_auth_clients.add(conn)

    def clear_connection_auth(self, conn: socket.socket) -> None:
        """Clears pending authentication state for one IPC connection.

        Args:
            conn (socket.socket): The client socket.

        Returns:
            None
        """
        self._local_auth.clear_connection(conn)

    def is_full_authenticated(self, conn: socket.socket) -> bool:
        """Checks current root-password strength without extending its lifetime.

        Args:
            conn: Requesting IPC session.
        Returns:
            bool: Whether this unrestricted session has root-password strength.
        """
        with self._lock:
            return (
                conn in self._authenticated_clients
                and conn in self._full_auth_clients
                and conn not in self._restricted
            )

    def quick_unlock_available(self) -> bool:
        """Checks whether Core has a usable protected PIN verifier.

        Args:
            None
        Returns:
            bool: Whether selecting the PIN method can be honored.
        """
        if self._quick_unlock is None:
            return False
        try:
            return self._quick_unlock.metadata() is not None
        except QuickUnlockStorageError:
            return False

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
        return authorization.authorize(self, cmd, conn, runtime_unlocked)

    def restrict(self, conn: socket.socket, cmd: RestrictClientCommand) -> IpcEvent:
        """Restricts only one authenticated client and fixes its locked policy.

        Args:
            conn (socket.socket): Requesting authenticated IPC socket.
            cmd (RestrictClientCommand): Immutable policy for this lock cycle.

        Returns:
            IpcEvent: Typed restriction event with optional proof challenge.
        """
        return restriction.restrict(self, conn, cmd)

    def configure_quick_unlock(
        self, conn: socket.socket, cmd: ConfigureQuickUnlockCommand
    ) -> IpcEvent:
        """Installs or removes client-derived PIN verifier material.

        Args:
            conn (socket.socket): Fully authorized requesting session.
            cmd (ConfigureQuickUnlockCommand): Authenticated configuration request.

        Returns:
            IpcEvent: Typed configuration result.
        """
        return restriction.configure_quick_unlock(self, conn, cmd)

    def _handle_reauthorize(
        self,
        cmd: ReauthorizeClientCommand,
        conn: socket.socket,
        policy: 'RestrictedSessionPolicy',
    ) -> None:
        """Verifies one restricted-session unlock proof and enforces PIN escalation.

        Args:
            cmd (ReauthorizeClientCommand): Proof attempt.
            conn (socket.socket): Restricted IPC socket.
            policy (RestrictedSessionPolicy): Fixed lock-cycle policy.

        Returns:
            None
        """
        return restriction._handle_reauthorize(self, cmd, conn, policy)

    def _issue_reauthorization_challenge(
        self,
        conn: socket.socket,
        *,
        password_required: bool,
        use_password_salt: bool,
    ) -> None:
        """Issues a fresh restricted-session challenge without counting a failure.

        Args:
            conn (socket.socket): Restricted IPC connection.
            password_required (bool): Whether PIN is unavailable for this cycle.
            use_password_salt (bool): Whether to return the profile proof salt.

        Returns:
            None
        """
        return restriction._issue_reauthorization_challenge(
            self,
            conn,
            password_required=password_required,
            use_password_salt=use_password_salt,
        )

    def _complete_reauthorization(
        self, conn: socket.socket, *, full_password: bool
    ) -> None:
        """Clears only one client's restricted state after valid proof.

        Args:
            conn (socket.socket): Reauthorized IPC socket.
            full_password (bool): Whether profile-password proof completed the flow.

        Returns:
            None
        """
        return restriction._complete_reauthorization(
            self, conn, full_password=full_password
        )

    def restricted_policy(
        self, conn: socket.socket
    ) -> Optional['RestrictedSessionPolicy']:
        """Returns one client's immutable restricted policy.

        Args:
            conn (socket.socket): IPC socket.

        Returns:
            Optional[RestrictedSessionPolicy]: Policy snapshot when restricted.
        """
        return projection.restricted_policy(self, conn)

    def filter_restricted_event(
        self, conn: socket.socket, event: IpcEvent
    ) -> Optional[IpcEvent]:
        """Applies locked notification privacy without exposing message content.

        Args:
            conn (socket.socket): Candidate restricted recipient.
            event (IpcEvent): Typed broadcast event.

        Returns:
            Optional[IpcEvent]: Safe event or None when unsolicited metadata is off.
        """
        return projection.filter_restricted_event(self, conn, event)

    def _consume_call_handle(self, conn: socket.socket, handle: Optional[str]) -> None:
        """Consumes a handle only after its action was authorized.

        Args:
            conn (socket.socket): Restricted client owning the handle.
            handle (Optional[str]): Exact one-use anonymous handle.

        Returns:
            None
        """
        return projection._consume_call_handle(self, conn, handle)

    def _valid_call_grant(self, conn: socket.socket, grant: PendingCallGrant) -> bool:
        """Checks the exact request, session cycle, runtime and expiry."""
        return projection._valid_call_grant(self, conn, grant)

    def take_pending_action(self, conn: socket.socket) -> socket.socket | None:
        """Transfers exact pending identity to the controller's atomic removal."""
        return projection.take_pending_action(self, conn)

    def project_pending_snapshot(
        self, conn: socket.socket, event: IpcEvent
    ) -> IpcEvent:
        """Qualifies call snapshot actions for this authenticated recipient.

        Args:
            conn: Receiving IPC connection.
            event: Direct command outcome.
        Returns:
            IpcEvent: Original outcome or recipient-qualified snapshot.
        """
        return calls.project_snapshot(self, conn, event)

    def record_accepted_call(
        self, conn: socket.socket, handle: str, onion: str, generation: int
    ) -> None:
        """Retains navigation identity only for a positively accepted logical context.

        Args:
            conn: Accepting IPC connection.
            handle: Consumed request handle.
            onion: Accepted canonical peer.
            generation: Exact new LIVE context generation.
        Returns:
            None
        """
        calls.record_accepted(self, conn, handle, onion, generation)

    def observe_call_transition(self, event: IpcEvent) -> None:
        """Preserves recipient request identity when another client accepts that exact call.

        Args:
            event: Core transport transition before recipient privacy filtering.
        Returns:
            None
        """
        calls.observe_transition(self, event)
