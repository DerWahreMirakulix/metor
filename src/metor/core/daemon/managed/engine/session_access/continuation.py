"""Read-only projection of one restricted client's current media and call grants."""

from __future__ import annotations

from dataclasses import replace
import socket
from typing import TYPE_CHECKING

from metor.core.api import (
    RestrictedClientStateEvent,
    NotificationPrivacy,
    PendingConnectionEntry,
    PendingConnectionReasonCode,
    ConnectionOrigin,
)
from metor.utils import Constants

# Local Package Imports
from .calls import issue_handle

if TYPE_CHECKING:
    from .controller import SessionAccessController


def restricted_state(
    owner: SessionAccessController, conn: socket.socket
) -> RestrictedClientStateEvent:
    """Revalidates the immutable grant without promoting a background or replacement peer.

    Args:
        owner: Core session authorization owner.
        conn: Authenticated or restricted requesting connection.
    Returns:
        RestrictedClientStateEvent: Content-free current authority and permitted call facts.
    """
    policy = owner.restricted_policy(conn)
    if policy is None:
        return RestrictedClientStateEvent()
    peer = policy.continued_live_target
    allowed = (
        policy.live_while_locked
        and peer is not None
        and policy.continued_live_context is not None
        and owner._live_context(peer) == policy.continued_live_context
        and owner._live_generation(peer) == policy.continued_live_generation
    )
    phase = owner._live_state(peer) if allowed and peer is not None else 'disconnected'
    if (
        allowed
        and peer is not None
        and owner._live_context(peer) != policy.continued_live_context
    ):
        allowed, phase = False, 'disconnected'
    pending: list[PendingConnectionEntry] = []
    accepted: list[str] = []
    if policy.notification_privacy is not NotificationPrivacy.OFF:
        for source in owner._pending_projection():
            if len(pending) >= Constants.MAX_ANONYMOUS_CALL_HANDLES:
                break
            if source.onion is None:
                continue
            handle = issue_handle(owner, conn, source.onion, source.action_handle)
            if handle is None:
                continue
            anonymous = policy.notification_privacy is NotificationPrivacy.ANONYMIZE
            pending.append(
                replace(
                    source,
                    action_handle=handle,
                    onion=None if anonymous else source.onion,
                    alias='unknown' if anonymous else source.alias,
                    origin=ConnectionOrigin.INCOMING if anonymous else source.origin,
                    reason=PendingConnectionReasonCode.USER_ACCEPT
                    if anonymous
                    else source.reason,
                )
            )
        with owner._lock:
            accepted = [
                handle
                for handle, (onion, context, _generation) in owner._accepted_calls.get(
                    conn, {}
                ).items()
                if owner._live_context(onion) == context
            ]
    return RestrictedClientStateEvent(
        restricted=True,
        continued_live_target=peer if allowed else None,
        continued_live_context_generation=policy.continued_live_generation
        if allowed
        else None,
        session_state=phase,
        notification_privacy=policy.notification_privacy,
        accept_while_locked=policy.accept_while_locked,
        pending=pending,
        accepted_handles=accepted,
    )
