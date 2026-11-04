"""Command authorization for full and restricted local sessions."""

from __future__ import annotations

import socket
import time
from typing import Optional

from metor.core.api import (
    AcceptCallCommand,
    CancelCallCommand,
    GetCallsCommand,
    HangupCallCommand,
    MuteCallCommand,
    ReadCallAudioCommand,
    RejectCallCommand,
    SendCallAudioCommand,
    AuthenticateSessionCommand,
    AcceptCommand,
    ReleaseVoiceOwnerCommand,
    ConfigureQuickUnlockCommand,
    ReauthorizeClientCommand,
    GetRestrictedClientStateCommand,
    RejectCommand,
    PrepareProfileExitCommand,
    SelfDestructCommand,
    EventType,
    IpcCommand,
    create_event,
)
from metor.utils import Constants

# Local Package Imports
from ...local_auth import (
    SessionAuthAttemptResult,
    SessionAuthPrompt,
)
from typing import TYPE_CHECKING

from .invitations import authorize_action
from .restricted_state import restricted_state

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
        if isinstance(cmd, GetCallsCommand):
            # Handler returns only privacy-scoped owned/incoming Call metadata.
            return True
        if isinstance(cmd, RejectCallCommand):
            return True
        if isinstance(cmd, AcceptCallCommand) and restricted_policy.accept_calls_locked:
            return True
        if isinstance(
            cmd,
            (
                CancelCallCommand,
                HangupCallCommand,
                MuteCallCommand,
                SendCallAudioCommand,
                ReadCallAudioCommand,
            ),
        ) and self._authorize_call(conn, cmd):
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
