"""Restriction and proof-backed reauthorization lifecycle."""

from __future__ import annotations

import socket
from dataclasses import replace
import time
import secrets
from typing import TYPE_CHECKING, Optional

from metor.core.api import (
    ClientUnlockMethod,
    ConfigureQuickUnlockCommand,
    QuickUnlockAction,
    ReauthorizeClientCommand,
    RestrictClientCommand,
    EventType,
    IpcEvent,
    create_event,
)
from metor.core.daemon.managed.quick_unlock import (
    QuickUnlockStorageError,
)

# Local Package Imports
from .policy import RestrictedSessionPolicy

if TYPE_CHECKING:
    from .controller import SessionAccessController


def restrict(
    self: SessionAccessController, conn: socket.socket, cmd: RestrictClientCommand
) -> IpcEvent:
    """Restricts only one authenticated client and fixes its locked policy.

    Args:
        conn (socket.socket): Requesting authenticated IPC socket.
        cmd (RestrictClientCommand): Immutable policy for this lock cycle.

    Returns:
        IpcEvent: Typed restriction event with optional proof challenge.
    """
    with self._lock:
        device_lifecycle = cmd.device_lifecycle and conn in self._authenticated_clients
        self._full_auth_clients.discard(conn)
        self._sensitive_auth_pending.pop(conn, None)
        self._sensitive_auth_grants.pop(conn, None)
    continued_target = (
        self._resolve_target(cmd.continued_live_target)
        if cmd.live_while_locked and cmd.continued_live_target is not None
        else None
    )
    continued_context = (
        self._live_context(continued_target) if continued_target is not None else None
    )
    generation = (
        self._live_generation(continued_target)
        if continued_target is not None
        else None
    )
    if (
        cmd.continued_live_context_generation is not None
        and generation != cmd.continued_live_context_generation
    ) or (
        type(continued_context) is int
        and generation is not None
        and continued_context != generation
    ):
        continued_target = None
        continued_context = None
        generation = None
    policy = RestrictedSessionPolicy(
        unlock_method=cmd.unlock_method,
        continued_live_target=continued_target,
        live_while_locked=cmd.live_while_locked,
        accept_while_locked=cmd.accept_while_locked,
        notification_privacy=cmd.notification_privacy,
        continued_live_context=continued_context,
        device_lifecycle=device_lifecycle,
        continued_live_generation=generation,
    )
    challenge: Optional[str] = None
    salt: Optional[str] = None
    with self._lock:
        self._restriction_generations[conn] = (
            self._restriction_generations.get(conn, 0) + 1
        )
        self._call_handles.pop(conn, None)
        self._accepted_calls.pop(conn, None)
        self._authorized_calls.pop(conn, None)
        self._restricted[conn] = policy
        self._pin_failures.pop(conn, None)
        self._pin_disabled.discard(conn)
        if cmd.unlock_method is not ClientUnlockMethod.NONE:
            challenge = secrets.token_hex(32)
            self._restricted_challenges[conn] = challenge
    if cmd.unlock_method is ClientUnlockMethod.PIN and self._quick_unlock is not None:
        try:
            metadata = self._quick_unlock.metadata()
        except QuickUnlockStorageError:
            metadata = None
        if metadata is not None:
            salt = metadata[0]
        else:
            policy = replace(policy, unlock_method=ClientUnlockMethod.PROFILE_PASSWORD)
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
            'continued_live_target': policy.continued_live_target
            if policy.continued_live_context is not None
            else None,
            'continued_live_context_generation': policy.continued_live_generation
            if policy.continued_live_context is not None
            else None,
        },
    )


def configure_quick_unlock(
    self: SessionAccessController, conn: socket.socket, cmd: ConfigureQuickUnlockCommand
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
            return create_event(EventType.QUICK_UNLOCK_CONFIGURED, {'enabled': False})
        if cmd.salt is None or cmd.verifier is None:
            return create_event(EventType.QUICK_UNLOCK_FAILED)
        self._quick_unlock.configure(cmd.salt, cmd.verifier)
        return create_event(EventType.QUICK_UNLOCK_CONFIGURED, {'enabled': True})
    except (QuickUnlockStorageError, ValueError, OSError):
        return create_event(EventType.QUICK_UNLOCK_FAILED)


def _handle_reauthorize(
    self: SessionAccessController,
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
    self: SessionAccessController,
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
    self: SessionAccessController, conn: socket.socket, *, full_password: bool
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
        self._authorized_calls.pop(conn, None)
        if full_password:
            self._full_auth_clients.add(conn)
        else:
            self._full_auth_clients.discard(conn)
    self._send(conn, create_event(EventType.CLIENT_REAUTHORIZED))
