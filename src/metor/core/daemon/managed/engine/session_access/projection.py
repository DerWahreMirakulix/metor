"""Per-recipient privacy and exact incoming-invitation capabilities."""

from __future__ import annotations

import socket
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Optional

from metor.core.api import (
    ConnectionOrigin,
    NotificationPrivacy,
    ConnectedEvent,
    ConnectionAutoAcceptedEvent,
    ConnectionPendingEvent,
    DisconnectedEvent,
    InboxNotificationEvent,
    IncomingConnectionEvent,
    PendingConnectionExpiredEvent,
    RuntimeStateChangedEvent,
    IpcEvent,
    CallStateEvent,
)
from .grants import PendingInvitationGrant

# Local Package Imports
from .policy import RestrictedSessionPolicy
from .invitations import project_event

if TYPE_CHECKING:
    from .controller import SessionAccessController


def restricted_policy(
    self: SessionAccessController, conn: socket.socket
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
    self: SessionAccessController, conn: socket.socket, event: IpcEvent
) -> Optional[IpcEvent]:
    """Applies locked notification privacy without exposing message content.

    Args:
        conn (socket.socket): Candidate restricted recipient.
        event (IpcEvent): Typed broadcast event.

    Returns:
        Optional[IpcEvent]: Safe event or None when unsolicited metadata is off.
    """
    policy = self.restricted_policy(conn)
    if isinstance(event, CallStateEvent):
        privacy = (
            policy.notification_privacy
            if policy is not None
            else NotificationPrivacy.SHOW_ALL
        )
        return self._project_call_event(conn, event, privacy)
    if policy is None:
        return project_event(self, conn, event)
    privacy = policy.notification_privacy
    if privacy is NotificationPrivacy.OFF:
        return None
    anonymous = privacy is NotificationPrivacy.ANONYMIZE
    if isinstance(event, (IncomingConnectionEvent, PendingConnectionExpiredEvent)):
        if anonymous:
            return replace(
                event,
                alias='unknown',
                onion=None,
                action_handle=None,
                origin=ConnectionOrigin.INCOMING,
            )
        return replace(event, action_handle=None)
    if isinstance(event, InboxNotificationEvent):
        return (
            replace(event, alias='unknown', onion=None, source_id=None)
            if anonymous
            else event
        )
    if isinstance(event, RuntimeStateChangedEvent):
        return replace(event, onion=None) if anonymous else event
    if isinstance(
        event, (ConnectionPendingEvent, ConnectionAutoAcceptedEvent, DisconnectedEvent)
    ):
        return (
            replace(
                event, alias='unknown', onion=None, origin=ConnectionOrigin.INCOMING
            )
            if anonymous
            else event
        )
    if isinstance(event, ConnectedEvent) and not anonymous:
        # Established transport events require a peer address on the wire.
        return event
    return None


def _consume_invitation_handle(
    self: SessionAccessController, conn: socket.socket, handle: Optional[str]
) -> None:
    """Consumes a handle only after its action was authorized.

    Args:
        conn (socket.socket): Restricted client owning the handle.
        handle (Optional[str]): Exact one-use anonymous handle.

    Returns:
        None
    """
    with self._lock:
        if handle is not None:
            grant = self._invitation_handles.get(conn, {}).pop(handle, None)
            if grant is not None:
                self._authorized_invitations[conn] = grant.pending


def _valid_invitation_grant(
    self: SessionAccessController, conn: socket.socket, grant: PendingInvitationGrant
) -> bool:
    """Checks the exact request, session cycle, runtime and expiry.

    Args:
        conn (socket.socket): Authenticated client connection presenting the grant.
        grant (PendingInvitationGrant): Exact pending-invitation capability under review.

    Returns:
        bool: Whether the grant still authorizes this connection and runtime cycle.
    """
    pending = self._pending_invitation(grant.onion)
    return (
        grant.restriction == self._restriction_generations.get(conn, 0)
        and grant.runtime == self._auth_runtime_generation
        and grant.expires_at > time.time()
        and pending is not None
        and pending[0] is grant.pending
    )


def take_pending_action(
    self: SessionAccessController, conn: socket.socket
) -> socket.socket | None:
    """Transfers exact pending identity to the controller's atomic removal.

    Args:
        conn (socket.socket): The conn input.

    Returns:
        socket.socket | None: The resulting value.
    """
    with self._lock:
        return self._authorized_invitations.pop(conn, None)
