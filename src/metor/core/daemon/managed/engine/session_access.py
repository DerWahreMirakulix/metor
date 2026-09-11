"""Authenticated IPC-session access and live-consumer ownership."""

import socket
import threading
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
    LockedAcceptPolicy,
    NotificationPrivacy,
    QuickUnlockAction,
    ReauthorizeClientCommand,
    RejectCommand,
    RestrictClientCommand,
    EventType,
    IpcCommand,
    IpcEvent,
    create_event,
)
from metor.core.daemon.managed.quick_unlock import QuickUnlockStore

# Local Package Imports
from ..local_auth import (
    LocalAuthTracker,
    SessionAuthAttemptResult,
    SessionAuthContext,
    SessionAuthPrompt,
)


@dataclass(frozen=True)
class RestrictedSessionPolicy:
    """Immutable permissions and privacy for one restricted lock cycle."""

    unlock_method: ClientUnlockMethod
    continued_live_target: Optional[str]
    live_while_locked: bool
    accept_while_locked: LockedAcceptPolicy
    notification_privacy: NotificationPrivacy


class SessionAccessController:
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
        self._quick_unlock = quick_unlock_store
        self._is_saved_contact = is_saved_contact_callback or (lambda _target: False)
        self._resolve_target = resolve_target_callback or (lambda target: target)
        self._voice_target = voice_target_callback or (lambda _msg_id: None)
        self._voice_delivery = voice_delivery_callback or (lambda _msg_id: None)
        self._restricted: dict[socket.socket, RestrictedSessionPolicy] = {}
        self._restricted_challenges: dict[socket.socket, str] = {}
        self._pin_failures: dict[socket.socket, int] = {}
        self._pin_disabled: set[socket.socket] = set()

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
            self._restricted.pop(conn, None)
            self._restricted_challenges.pop(conn, None)
            self._pin_failures.pop(conn, None)
            self._pin_disabled.discard(conn)
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
            self._restricted.clear()
            self._restricted_challenges.clear()
            self._pin_failures.clear()
            self._pin_disabled.clear()
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
            restricted_policy = self._restricted.get(conn)

        if restricted_policy is not None:
            if isinstance(cmd, ReauthorizeClientCommand):
                self._handle_reauthorize(cmd, conn, restricted_policy)
                return False
            if isinstance(cmd, RejectCommand):
                return True
            if isinstance(cmd, AcceptCommand):
                if restricted_policy.accept_while_locked is LockedAcceptPolicy.ALL:
                    return True
                if (
                    restricted_policy.accept_while_locked
                    is LockedAcceptPolicy.SAVED_CONTACTS
                    and self._is_saved_contact(cmd.target)
                ):
                    return True
            if (
                isinstance(cmd, BeginVoiceCommand)
                and cmd.delivery is Delivery.LIVE
                and restricted_policy.live_while_locked
                and restricted_policy.continued_live_target
                == self._resolve_target(cmd.target)
            ):
                return True
            if isinstance(cmd, (AppendVoiceChunkCommand, FinalizeVoiceCommand)):
                return (
                    restricted_policy.live_while_locked
                    and restricted_policy.continued_live_target
                    == self._voice_target(cmd.msg_id)
                    and self._voice_delivery(cmd.msg_id) is Delivery.LIVE
                )
            self._send(
                conn,
                create_event(
                    EventType.CLIENT_ACCESS_RESTRICTED,
                    {'command': cmd.command_type.value},
                ),
            )
            return False

        if isinstance(cmd, ConfigureQuickUnlockCommand) and not is_authenticated:
            quick_unlock_prompt = self._local_auth.issue_session_challenge(conn)
            if quick_unlock_prompt is not None:
                self._send(
                    conn,
                    self._session_auth_event(
                        EventType.AUTH_REQUIRED, quick_unlock_prompt
                    ),
                )
            else:
                self._send(conn, create_event(EventType.QUICK_UNLOCK_FAILED))
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
        if is_authenticated:
            self.mark_authenticated(conn)
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
        policy = RestrictedSessionPolicy(
            unlock_method=cmd.unlock_method,
            continued_live_target=(
                self._resolve_target(cmd.continued_live_target)
                if cmd.live_while_locked and cmd.continued_live_target is not None
                else None
            ),
            live_while_locked=cmd.live_while_locked,
            accept_while_locked=cmd.accept_while_locked,
            notification_privacy=cmd.notification_privacy,
        )
        challenge: Optional[str] = None
        salt: Optional[str] = None
        with self._lock:
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
            metadata = self._quick_unlock.metadata()
            if metadata is not None:
                salt = metadata[0]
            else:
                policy = RestrictedSessionPolicy(
                    ClientUnlockMethod.PROFILE_PASSWORD,
                    policy.continued_live_target,
                    policy.live_while_locked,
                    policy.accept_while_locked,
                    policy.notification_privacy,
                )
                with self._lock:
                    self._restricted[conn] = policy
        elif cmd.unlock_method is ClientUnlockMethod.PROFILE_PASSWORD:
            salt = self._local_auth.proof_salt()
        return create_event(
            EventType.CLIENT_RESTRICTED,
            {
                'unlock_method': policy.unlock_method.value,
                'challenge': challenge,
                'salt': salt,
            },
        )

    def configure_quick_unlock(self, cmd: ConfigureQuickUnlockCommand) -> IpcEvent:
        """Installs or removes client-derived PIN verifier material.

        Args:
            cmd (ConfigureQuickUnlockCommand): Authenticated configuration request.

        Returns:
            IpcEvent: Typed configuration result.
        """
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
        except (ValueError, OSError):
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
            self._complete_reauthorization(conn)
            return
        with self._lock:
            challenge = self._restricted_challenges.pop(conn, None)
        authenticated = False
        if challenge is not None and cmd.proof is not None:
            if (
                cmd.method is ClientUnlockMethod.PIN
                and policy.unlock_method is ClientUnlockMethod.PIN
                and conn not in self._pin_disabled
                and self._quick_unlock is not None
            ):
                authenticated = self._quick_unlock.verify(challenge, cmd.proof)
            elif cmd.method is ClientUnlockMethod.PROFILE_PASSWORD:
                authenticated = self._local_auth.verify_proof_key(challenge, cmd.proof)
        if authenticated:
            self._complete_reauthorization(conn)
            return
        password_required = False
        with self._lock:
            if cmd.method is ClientUnlockMethod.PIN:
                failures = self._pin_failures.get(conn, 0) + 1
                self._pin_failures[conn] = failures
                if failures >= 3:
                    self._pin_disabled.add(conn)
                    password_required = True
            next_challenge = secrets.token_hex(32)
            self._restricted_challenges[conn] = next_challenge
        salt = None
        if password_required or cmd.method is ClientUnlockMethod.PROFILE_PASSWORD:
            salt = self._local_auth.proof_salt()
        elif self._quick_unlock is not None:
            metadata = self._quick_unlock.metadata()
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

    def _complete_reauthorization(self, conn: socket.socket) -> None:
        """Clears only one client's restricted state after valid proof.

        Args:
            conn (socket.socket): Reauthorized IPC socket.

        Returns:
            None
        """
        with self._lock:
            self._restricted.pop(conn, None)
            self._restricted_challenges.pop(conn, None)
            self._pin_failures.pop(conn, None)
            self._pin_disabled.discard(conn)
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
        permitted_types = {
            EventType.INCOMING_CONNECTION,
            EventType.CONNECTION_PENDING,
            EventType.CONNECTION_AUTO_ACCEPTED,
            EventType.CONNECTED,
            EventType.DISCONNECTED,
        }
        if event.event_type not in permitted_types:
            return None
        if policy.notification_privacy is NotificationPrivacy.OFF:
            return None
        if policy.notification_privacy is NotificationPrivacy.ANONYMIZE:
            changes: dict[str, object] = {}
            if hasattr(event, 'alias'):
                changes['alias'] = 'unknown'
            if hasattr(event, 'onion'):
                changes['onion'] = None
            clone = IpcEvent.from_dict(json.loads(event.to_json()))
            for field_name, value in changes.items():
                setattr(clone, field_name, value)
            return clone
        return event

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
