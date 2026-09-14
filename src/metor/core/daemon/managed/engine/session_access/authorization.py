"""Command authorization for full and restricted local sessions."""

from __future__ import annotations

import socket
import time
from typing import Optional

from metor.core.api import (
    AuthenticateSessionCommand,
    AcceptCommand,
    AppendVoiceChunkCommand,
    BeginVoiceCommand,
    ReleaseVoiceOwnerCommand,
    ConfigureQuickUnlockCommand,
    Delivery,
    FinalizeVoiceCommand,
    GetVoiceChunkCommand,
    ListRetainedMessagesCommand,
    MessageDirectionCode,
    LockedAcceptPolicy,
    NotificationPrivacy,
    ReleaseVoiceCommand,
    ReauthorizeClientCommand,
    GetRestrictedClientStateCommand,
    RejectCommand,
    PrepareProfileExitCommand,
    SelfDestructCommand,
    EventType,
    IpcCommand,
    create_event,
    NoPendingConnectionEvent,
)
from metor.utils import Constants

# Local Package Imports
from ...local_auth import (
    SessionAuthAttemptResult,
    SessionAuthPrompt,
)
from typing import TYPE_CHECKING

from .calls import authorize_action
from .continuation import restricted_state

if TYPE_CHECKING:
    from .controller import SessionAccessController


def authorize(
    self: SessionAccessController,
    cmd: IpcCommand,
    conn: socket.socket,
    runtime_unlocked: bool,
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
        if isinstance(cmd, GetRestrictedClientStateCommand):
            self._send(conn, restricted_state(self, conn))
            return False
        if isinstance(cmd, ReleaseVoiceOwnerCommand):
            return True
        mapped_call_target = False
        mapped_call_handle: Optional[str] = None
        if isinstance(cmd, (AcceptCommand, RejectCommand)):
            with self._lock:
                mapped_target = self._call_handles.get(conn, {}).get(
                    cmd.action_handle or cmd.target
                )
            if mapped_target is not None and self._valid_call_grant(
                conn, mapped_target
            ):
                mapped_call_handle = cmd.action_handle or cmd.target
                cmd.action_handle = mapped_call_handle
                cmd.target = mapped_target.onion
                mapped_call_target = True
            if cmd.action_handle is not None and not mapped_call_target:
                self._send(conn, NoPendingConnectionEvent(alias='unknown'))
                return False
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
                restricted_policy.notification_privacy is NotificationPrivacy.ANONYMIZE
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
                restricted_policy.notification_privacy is NotificationPrivacy.ANONYMIZE
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
                and self._live_context(restricted_policy.continued_live_target or '')
                == restricted_policy.continued_live_context
            ):
                return True
        if isinstance(cmd, ListRetainedMessagesCommand):
            target = (
                self._resolve_target(cmd.target) if cmd.target is not None else None
            )
            if (
                cmd.msg_id is not None
                and cmd.owner_token is not None
                and cmd.direction is MessageDirectionCode.OUT
                and cmd.cursor is None
                and restricted_policy.live_while_locked
                and restricted_policy.continued_live_context is not None
                and target is not None
                and target == restricted_policy.continued_live_target
                and self._voice_context(target, cmd.msg_id, 'out')
                == restricted_policy.continued_live_context
                and self._live_context(target)
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
                and self._inbound_voice_delivery(target, cmd.msg_id) is Delivery.LIVE
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
                and self._inbound_voice_delivery(target, cmd.msg_id) is Delivery.LIVE
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
        if isinstance(cmd, GetRestrictedClientStateCommand):
            self._send(conn, restricted_state(self, conn))
            return False
        if isinstance(cmd, (AcceptCommand, RejectCommand)):
            return authorize_action(self, conn, cmd)
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
            self._session_auth_event(EventType.INVALID_PASSWORD, result.retry_prompt),
        )
    else:
        self._send(conn, create_event(EventType.INVALID_PASSWORD))
    if result.should_disconnect:
        self._disconnect_client(conn)
    return False
