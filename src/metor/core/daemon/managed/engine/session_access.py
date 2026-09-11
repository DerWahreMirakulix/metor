"""Authenticated IPC-session access and live-consumer ownership."""

import socket
import threading
import time
from dataclasses import dataclass
import secrets
import json
from typing import Callable, Optional, Set

from metor.core.api import (
    AuthenticateSessionCommand,
    AcceptCommand,
    AppendVoiceChunkCommand,
    BeginVoiceCommand,
    ClientUnlockMethod,
    ConfigureQuickUnlockCommand,
    Delivery,
    FinalizeVoiceCommand,
    GetVoiceChunkCommand,
    LockedAcceptPolicy,
    NotificationPrivacy,
    QuickUnlockAction,
    ReleaseVoiceCommand,
    ReauthorizeClientCommand,
    RejectCommand,
    RestrictClientCommand,
    PrepareProfileExitCommand,
    SelfDestructCommand,
    EventType,
    IpcCommand,
    IpcEvent,
    create_event,
)
from metor.core.daemon.managed.quick_unlock import (
    QuickUnlockStorageError,
    QuickUnlockStore,
)
from metor.utils import Constants
from .capabilities import PendingCallGrant

# Local Package Imports
from ..local_auth import (
    LocalAuthTracker,
    SessionAuthAttemptResult,
    SessionAuthContext,
    SessionAuthPrompt,
)
from .session_events import SessionEventMixin


@dataclass(frozen=True)
class RestrictedSessionPolicy:
    """Immutable permissions and privacy for one restricted lock cycle."""

    unlock_method: ClientUnlockMethod
    continued_live_target: Optional[str]
    live_while_locked: bool
    accept_while_locked: LockedAcceptPolicy
    notification_privacy: NotificationPrivacy
    continued_live_context: object | None = None
    device_lifecycle: bool = False


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
        pending_call_callback: Optional[
            Callable[[str], tuple[socket.socket, float] | None]
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
        self._authorized_calls: dict[socket.socket, socket.socket] = {}
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
            sensitive_auth_pending = self._sensitive_auth_pending.get(conn)
            restricted_policy = self._restricted.get(conn)

        if restricted_policy is not None:
            mapped_call_target = False
            mapped_call_handle: Optional[str] = None
            if isinstance(cmd, (AcceptCommand, RejectCommand)):
                with self._lock:
                    mapped_target = self._call_handles.get(conn, {}).get(cmd.target)
                if mapped_target is not None and self._valid_call_grant(
                    conn, mapped_target
                ):
                    mapped_call_handle = cmd.target
                    cmd.target = mapped_target.onion
                    mapped_call_target = True
            if isinstance(cmd, ReauthorizeClientCommand):
                restricted_retry_after = self.retry_after_seconds()
                if restricted_retry_after is not None:
                    self._send(conn, self._rate_limited_event(restricted_retry_after))
                    return False
                self._handle_reauthorize(cmd, conn, restricted_policy)
                return False
            if isinstance(cmd, PrepareProfileExitCommand):
                if restricted_policy.device_lifecycle:
                    return True
            if isinstance(cmd, SelfDestructCommand):
                if (
                    restricted_policy.device_lifecycle
                    and not self._self_destruct_requires_unlock()
                ):
                    return True
            if isinstance(cmd, RejectCommand):
                if (
                    restricted_policy.notification_privacy
                    is NotificationPrivacy.ANONYMIZE
                    and not mapped_call_target
                ):
                    self._send(
                        conn,
                        create_event(
                            EventType.CLIENT_ACCESS_RESTRICTED,
                            {'command': cmd.command_type.value},
                        ),
                    )
                    return False
                if mapped_call_target:
                    self._consume_call_handle(conn, mapped_call_handle)
                return True
            if isinstance(cmd, AcceptCommand):
                if (
                    restricted_policy.notification_privacy
                    is NotificationPrivacy.ANONYMIZE
                    and not mapped_call_target
                ):
                    self._send(
                        conn,
                        create_event(
                            EventType.CLIENT_ACCESS_RESTRICTED,
                            {'command': cmd.command_type.value},
                        ),
                    )
                    return False
                if restricted_policy.accept_while_locked is LockedAcceptPolicy.ALL:
                    if mapped_call_target:
                        self._consume_call_handle(conn, mapped_call_handle)
                    return True
                if (
                    restricted_policy.accept_while_locked
                    is LockedAcceptPolicy.SAVED_CONTACTS
                    and self._is_saved_contact(cmd.target)
                ):
                    if mapped_call_target:
                        self._consume_call_handle(conn, mapped_call_handle)
                    return True
            if (
                isinstance(cmd, BeginVoiceCommand)
                and cmd.delivery is Delivery.LIVE
                and restricted_policy.live_while_locked
                and restricted_policy.continued_live_target
                == self._resolve_target(cmd.target)
                and restricted_policy.continued_live_context is not None
                and self._live_context(restricted_policy.continued_live_target or '')
                == restricted_policy.continued_live_context
            ):
                return True
            if isinstance(cmd, (AppendVoiceChunkCommand, FinalizeVoiceCommand)):
                if (
                    restricted_policy.live_while_locked
                    and restricted_policy.continued_live_context is not None
                    and restricted_policy.continued_live_target
                    == self._voice_target(cmd.msg_id)
                    and self._voice_delivery(cmd.msg_id) is Delivery.LIVE
                    and self._voice_context(
                        restricted_policy.continued_live_target or '', cmd.msg_id, 'out'
                    )
                    == restricted_policy.continued_live_context
                    and self._live_context(
                        restricted_policy.continued_live_target or ''
                    )
                    == restricted_policy.continued_live_context
                ):
                    return True
            if isinstance(cmd, GetVoiceChunkCommand):
                target = self._resolve_target(cmd.target)
                if (
                    cmd.direction.value == 'in'
                    and restricted_policy.live_while_locked
                    and restricted_policy.continued_live_context is not None
                    and target == restricted_policy.continued_live_target
                    and target is not None
                    and self._inbound_voice_delivery(target, cmd.msg_id)
                    is Delivery.LIVE
                    and self._voice_context(target, cmd.msg_id, 'in')
                    == restricted_policy.continued_live_context
                    and self._live_context(target)
                    == restricted_policy.continued_live_context
                ):
                    return True
            if isinstance(cmd, ReleaseVoiceCommand):
                target = self._resolve_target(cmd.target)
                if (
                    restricted_policy.live_while_locked
                    and restricted_policy.continued_live_context is not None
                    and target == restricted_policy.continued_live_target
                    and target is not None
                    and self._inbound_voice_delivery(target, cmd.msg_id)
                    is Delivery.LIVE
                    and self._voice_context(target, cmd.msg_id, 'in')
                    == restricted_policy.continued_live_context
                    and self._live_context(target)
                    == restricted_policy.continued_live_context
                ):
                    return True
            self._send(
                conn,
                create_event(
                    EventType.CLIENT_ACCESS_RESTRICTED,
                    {'command': cmd.command_type.value},
                ),
            )
            return False

        if isinstance(cmd, ConfigureQuickUnlockCommand):
            now = time.monotonic()
            with self._lock:
                grant = self._sensitive_auth_grants.get(conn)
                grant_valid = (
                    grant is not None
                    and grant[0] is cmd.action
                    and grant[1] >= now
                    and grant[2] == self._auth_runtime_generation
                )
                if not grant_valid:
                    self._sensitive_auth_grants.pop(conn, None)
            if not grant_valid:
                quick_unlock_prompt = self._local_auth.issue_session_challenge(conn)
                if quick_unlock_prompt is not None:
                    with self._lock:
                        self._sensitive_auth_pending[conn] = cmd.action
                    self._send(
                        conn,
                        self._session_auth_event(
                            EventType.AUTH_REQUIRED, quick_unlock_prompt
                        ),
                    )
                else:
                    self._send(conn, create_event(EventType.QUICK_UNLOCK_FAILED))
                return False

        if isinstance(cmd, SelfDestructCommand) and not is_authenticated:
            purge_prompt = self._local_auth.issue_session_challenge(conn)
            if purge_prompt is not None:
                self._send(
                    conn,
                    self._session_auth_event(EventType.AUTH_REQUIRED, purge_prompt),
                )
            else:
                self._send(conn, create_event(EventType.AUTH_REQUIRED))
            return False

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
        if is_authenticated and sensitive_auth_pending is None:
            self._send(conn, create_event(EventType.SESSION_AUTHENTICATED))
            return False

        if not self._local_auth.is_enabled():
            self._send(conn, create_event(EventType.INVALID_PASSWORD))
            return False

        result: SessionAuthAttemptResult = self._local_auth.verify_session_proof(
            conn,
            cmd.proof,
            self._lockout_timeout(),
            self._failure_limit(),
        )
        if result.authenticated:
            self.mark_authenticated(conn)
            with self._lock:
                action = self._sensitive_auth_pending.pop(conn, None)
                if action is not None:
                    self._sensitive_auth_grants[conn] = (
                        action,
                        time.monotonic() + Constants.SENSITIVE_AUTH_GRANT_TIMEOUT_SEC,
                        self._auth_runtime_generation,
                    )
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

    def restrict(self, conn: socket.socket, cmd: RestrictClientCommand) -> IpcEvent:
        """Restricts only one authenticated client and fixes its locked policy.

        Args:
            conn (socket.socket): Requesting authenticated IPC socket.
            cmd (RestrictClientCommand): Immutable policy for this lock cycle.

        Returns:
            IpcEvent: Typed restriction event with optional proof challenge.
        """
        with self._lock:
            device_lifecycle = (
                cmd.device_lifecycle and conn in self._authenticated_clients
            )
            self._full_auth_clients.discard(conn)
            self._sensitive_auth_pending.pop(conn, None)
            self._sensitive_auth_grants.pop(conn, None)
        continued_target = (
            self._resolve_target(cmd.continued_live_target)
            if cmd.live_while_locked and cmd.continued_live_target is not None
            else None
        )
        policy = RestrictedSessionPolicy(
            unlock_method=cmd.unlock_method,
            continued_live_target=continued_target,
            live_while_locked=cmd.live_while_locked,
            accept_while_locked=cmd.accept_while_locked,
            notification_privacy=cmd.notification_privacy,
            continued_live_context=(
                self._live_context(continued_target)
                if continued_target is not None
                else None
            ),
            device_lifecycle=device_lifecycle,
        )
        challenge: Optional[str] = None
        salt: Optional[str] = None
        with self._lock:
            self._restriction_generations[conn] = (
                self._restriction_generations.get(conn, 0) + 1
            )
            self._call_handles.pop(conn, None)
            self._authorized_calls.pop(conn, None)
            self._restricted[conn] = policy
            self._pin_failures.pop(conn, None)
            self._pin_disabled.discard(conn)
            if cmd.unlock_method is not ClientUnlockMethod.NONE:
                challenge = secrets.token_hex(32)
                self._restricted_challenges[conn] = challenge
        if (
            cmd.unlock_method is ClientUnlockMethod.PIN
            and self._quick_unlock is not None
        ):
            try:
                metadata = self._quick_unlock.metadata()
            except QuickUnlockStorageError:
                metadata = None
            if metadata is not None:
                salt = metadata[0]
            else:
                policy = RestrictedSessionPolicy(
                    ClientUnlockMethod.PROFILE_PASSWORD,
                    policy.continued_live_target,
                    policy.live_while_locked,
                    policy.accept_while_locked,
                    policy.notification_privacy,
                    policy.continued_live_context,
                    policy.device_lifecycle,
                )
                with self._lock:
                    self._restricted[conn] = policy
                salt = self._local_auth.proof_salt()
        elif cmd.unlock_method is ClientUnlockMethod.PROFILE_PASSWORD:
            salt = self._local_auth.proof_salt()
        return create_event(
            EventType.CLIENT_RESTRICTED,
            {
                'unlock_method': policy.unlock_method.value,
                'challenge': challenge,
                'salt': salt,
                'device_lifecycle': policy.device_lifecycle,
            },
        )

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
        with self._lock:
            grant = self._sensitive_auth_grants.pop(conn, None)
            if (
                grant is None
                or grant[0] is not cmd.action
                or grant[1] < time.monotonic()
                or grant[2] != self._auth_runtime_generation
            ):
                return create_event(EventType.QUICK_UNLOCK_FAILED)
        if self._quick_unlock is None:
            return create_event(EventType.QUICK_UNLOCK_FAILED)
        try:
            if cmd.action is QuickUnlockAction.REMOVE:
                self._quick_unlock.remove()
                return create_event(
                    EventType.QUICK_UNLOCK_CONFIGURED, {'enabled': False}
                )
            if cmd.salt is None or cmd.verifier is None:
                return create_event(EventType.QUICK_UNLOCK_FAILED)
            self._quick_unlock.configure(cmd.salt, cmd.verifier)
            return create_event(EventType.QUICK_UNLOCK_CONFIGURED, {'enabled': True})
        except (QuickUnlockStorageError, ValueError, OSError):
            return create_event(EventType.QUICK_UNLOCK_FAILED)

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
        if (
            cmd.method is ClientUnlockMethod.NONE
            and policy.unlock_method is ClientUnlockMethod.NONE
        ):
            self._complete_reauthorization(conn, full_password=False)
            return
        with self._lock:
            pin_disabled = conn in self._pin_disabled
        if cmd.method is ClientUnlockMethod.PROFILE_PASSWORD and cmd.proof is None:
            self._issue_reauthorization_challenge(
                conn, password_required=True, use_password_salt=True
            )
            return
        with self._lock:
            challenge = self._restricted_challenges.pop(conn, None)
        authenticated = False
        password_attempt = False
        should_disconnect = False
        if challenge is not None and cmd.proof is not None:
            if (
                cmd.method is ClientUnlockMethod.PIN
                and policy.unlock_method is ClientUnlockMethod.PIN
                and conn not in self._pin_disabled
                and self._quick_unlock is not None
            ):
                authenticated = self._quick_unlock.verify(challenge, cmd.proof)
            elif cmd.method is ClientUnlockMethod.PROFILE_PASSWORD:
                password_attempt = True
                result = self._local_auth.verify_challenge_proof(
                    conn,
                    challenge,
                    cmd.proof,
                    self._lockout_timeout(),
                    self._failure_limit(),
                )
                authenticated = result.authenticated
                should_disconnect = result.should_disconnect
        if authenticated:
            self._complete_reauthorization(conn, full_password=password_attempt)
            return
        retry_after = self.retry_after_seconds()
        if retry_after is not None:
            self._send(conn, self._rate_limited_event(retry_after))
            return
        password_required = pin_disabled or password_attempt
        with self._lock:
            if cmd.method is ClientUnlockMethod.PIN:
                failures = self._pin_failures.get(conn, 0) + 1
                self._pin_failures[conn] = failures
                if failures >= 3:
                    self._pin_disabled.add(conn)
                    password_required = True
        if cmd.method is ClientUnlockMethod.PIN:
            should_disconnect = self._local_auth.register_invalid_unlock(
                conn,
                self._lockout_timeout(),
                self._failure_limit(),
            )
            retry_after = self.retry_after_seconds()
            if retry_after is not None:
                self._send(conn, self._rate_limited_event(retry_after))
                return
        if should_disconnect:
            self._disconnect_client(conn)
            return
        self._issue_reauthorization_challenge(
            conn,
            password_required=password_required,
            use_password_salt=password_required,
        )

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
        next_challenge = secrets.token_hex(32)
        with self._lock:
            self._restricted_challenges[conn] = next_challenge
        salt: Optional[str] = None
        if use_password_salt:
            salt = self._local_auth.proof_salt()
        elif self._quick_unlock is not None:
            try:
                metadata = self._quick_unlock.metadata()
            except QuickUnlockStorageError:
                metadata = None
            salt = metadata[0] if metadata else None
        self._send(
            conn,
            create_event(
                EventType.QUICK_UNLOCK_FAILED,
                {
                    'password_required': password_required,
                    'challenge': next_challenge,
                    'salt': salt,
                },
            ),
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
        with self._lock:
            self._restricted.pop(conn, None)
            self._restricted_challenges.pop(conn, None)
            self._pin_failures.pop(conn, None)
            self._pin_disabled.discard(conn)
            self._sensitive_auth_pending.pop(conn, None)
            self._sensitive_auth_grants.pop(conn, None)
            self._call_handles.pop(conn, None)
            self._restriction_generations.pop(conn, None)
            self._authorized_calls.pop(conn, None)
            if full_password:
                self._full_auth_clients.add(conn)
            else:
                self._full_auth_clients.discard(conn)
        self._send(conn, create_event(EventType.CLIENT_REAUTHORIZED))

    def restricted_policy(
        self, conn: socket.socket
    ) -> Optional['RestrictedSessionPolicy']:
        """Returns one client's immutable restricted policy.

        Args:
            conn (socket.socket): IPC socket.

        Returns:
            Optional[RestrictedSessionPolicy]: Policy snapshot when restricted.
        """
        with self._lock:
            return self._restricted.get(conn)

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
        policy = self.restricted_policy(conn)
        if policy is None:
            return event
        voice_types = {
            EventType.VOICE_STARTED,
            EventType.VOICE_CHUNK_ACCEPTED,
            EventType.VOICE_CHUNK_RECEIVED,
            EventType.VOICE_FINALIZED,
            EventType.VOICE_RESOURCE_PRESSURE,
            EventType.VOICE_RESOURCE_LIMIT,
            EventType.VOICE_INCOMING_STARTED,
        }
        if event.event_type in voice_types:
            if not policy.live_while_locked or policy.continued_live_target is None:
                return None
            event_onion = getattr(event, 'onion', None)
            event_msg_id = getattr(event, 'msg_id', None)
            if event_onion is None and isinstance(event_msg_id, str):
                event_onion = self._voice_target(event_msg_id)
            event_delivery = getattr(event, 'delivery', Delivery.LIVE)
            direction = getattr(event, 'direction', None)
            if direction is None:
                direction = (
                    'in'
                    if event.event_type
                    in {
                        EventType.VOICE_INCOMING_STARTED,
                        EventType.VOICE_CHUNK_RECEIVED,
                    }
                    else 'out'
                )
            else:
                direction = direction.value
            if (
                event_onion == policy.continued_live_target
                and event_delivery is Delivery.LIVE
                and policy.continued_live_context is not None
                and isinstance(event_msg_id, str)
                and self._live_context(event_onion) == policy.continued_live_context
                and self._voice_context(event_onion, event_msg_id, direction)
                == policy.continued_live_context
            ):
                return event
            return None
        permitted_types = {
            EventType.INCOMING_CONNECTION,
            EventType.CONNECTION_PENDING,
            EventType.CONNECTION_AUTO_ACCEPTED,
            EventType.CONNECTED,
            EventType.DISCONNECTED,
            EventType.PENDING_CONNECTION_EXPIRED,
            EventType.RUNTIME_STATE_CHANGED,
        }
        if event.event_type not in permitted_types:
            return None
        if policy.notification_privacy is NotificationPrivacy.OFF:
            return None
        if policy.notification_privacy is NotificationPrivacy.ANONYMIZE:
            changes: dict[str, object] = {}
            onion = getattr(event, 'onion', None)
            if hasattr(event, 'alias'):
                changes['alias'] = 'unknown'
            if hasattr(event, 'onion'):
                changes['onion'] = None
            if event.event_type in {
                EventType.INCOMING_CONNECTION,
                EventType.PENDING_CONNECTION_EXPIRED,
            } and isinstance(onion, str):
                with self._lock:
                    handles = self._call_handles.setdefault(conn, {})
                    generation = self._restriction_generations.get(conn, 0)
                    for handle, grant in tuple(handles.items()):
                        if (
                            not self._valid_call_grant(conn, grant)
                            and event.event_type
                            is not EventType.PENDING_CONNECTION_EXPIRED
                        ):
                            handles.pop(handle, None)
                    action_handle = None
                    if event.event_type is EventType.INCOMING_CONNECTION:
                        pending = self._pending_call(onion)
                        if pending is not None:
                            action_handle = next(
                                (
                                    handle
                                    for handle, grant in handles.items()
                                    if grant.onion == onion
                                    and grant.pending is pending[0]
                                ),
                                None,
                            )
                            if (
                                action_handle is None
                                and len(handles) < Constants.MAX_ANONYMOUS_CALL_HANDLES
                            ):
                                action_handle = secrets.token_urlsafe(32)
                                handles[action_handle] = PendingCallGrant(
                                    onion,
                                    generation,
                                    self._auth_runtime_generation,
                                    pending[0],
                                    min(
                                        pending[1],
                                        time.time()
                                        + Constants.PENDING_EXPIRY_FEEDBACK_WINDOW_SEC,
                                    ),
                                )
                    if event.event_type is EventType.PENDING_CONNECTION_EXPIRED:
                        for handle, grant in tuple(handles.items()):
                            if grant.onion == onion and grant.restriction == generation:
                                action_handle = handle
                                handles.pop(handle, None)
                                break
                if hasattr(event, 'action_handle'):
                    changes['action_handle'] = action_handle
            clone = IpcEvent.from_dict(json.loads(event.to_json()))
            for field_name, value in changes.items():
                setattr(clone, field_name, value)
            return clone
        return event

    def _consume_call_handle(self, conn: socket.socket, handle: Optional[str]) -> None:
        """Consumes a handle only after its action was authorized.

        Args:
            conn (socket.socket): Restricted client owning the handle.
            handle (Optional[str]): Exact one-use anonymous handle.

        Returns:
            None
        """
        with self._lock:
            if handle is not None:
                grant = self._call_handles.get(conn, {}).pop(handle, None)
                if grant is not None:
                    self._authorized_calls[conn] = grant.pending

    def _valid_call_grant(self, conn: socket.socket, grant: PendingCallGrant) -> bool:
        """Checks the exact request, session cycle, runtime and expiry."""
        pending = self._pending_call(grant.onion)
        return (
            grant.restriction == self._restriction_generations.get(conn)
            and grant.runtime == self._auth_runtime_generation
            and grant.expires_at > time.time()
            and pending is not None
            and pending[0] is grant.pending
        )

    def take_pending_action(self, conn: socket.socket) -> socket.socket | None:
        """Transfers exact pending identity to the controller's atomic removal."""
        with self._lock:
            return self._authorized_calls.pop(conn, None)
