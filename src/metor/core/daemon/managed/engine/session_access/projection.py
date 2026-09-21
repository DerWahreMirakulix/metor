"""Per-recipient privacy and exact incoming-call capabilities."""

from __future__ import annotations

import socket
import time
import json
from typing import TYPE_CHECKING, Optional

from metor.core.api import (
    Delivery,
    ConnectionOrigin,
    NotificationPrivacy,
    EventType,
    IpcEvent,
)
from .grants import PendingCallGrant

# Local Package Imports
from .policy import RestrictedSessionPolicy
from .calls import project_event

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
    if policy is None:
        return project_event(self, conn, event)
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
        EventType.INBOX_NOTIFICATION,
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
        if hasattr(event, 'alias'):
            changes['alias'] = 'unknown'
        if hasattr(event, 'onion'):
            changes['onion'] = None
        if hasattr(event, 'source_id'):
            changes['source_id'] = None
        if hasattr(event, 'origin'):
            changes['origin'] = ConnectionOrigin.INCOMING
        event = project_event(self, conn, event)
        clone = IpcEvent.from_dict(json.loads(event.to_json()))
        for field_name, value in changes.items():
            setattr(clone, field_name, value)
        return clone
    return project_event(self, conn, event)


def _consume_call_handle(
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
            grant = self._call_handles.get(conn, {}).pop(handle, None)
            if grant is not None:
                self._authorized_calls[conn] = grant.pending


def _valid_call_grant(
    self: SessionAccessController, conn: socket.socket, grant: PendingCallGrant
) -> bool:
    """Checks the exact request, session cycle, runtime and expiry.

    Args:
        conn (socket.socket): Authenticated client connection presenting the grant.
        grant (PendingCallGrant): Exact pending-call capability under review.

    Returns:
        bool: Whether the grant still authorizes this connection and runtime cycle.
    """
    pending = self._pending_call(grant.onion)
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
        return self._authorized_calls.pop(conn, None)
