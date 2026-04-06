"""Helpers for chat transport and connection lifecycle event handling."""

from typing import Dict

from metor.core.api import (
    AutoReconnectScheduledEvent,
    ConnectedEvent,
    ConnectionAutoAcceptedEvent,
    ConnectionConnectingEvent,
    ConnectionFailedEvent,
    ConnectionPendingEvent,
    ConnectionReasonCode,
    ConnectionRejectedEvent,
    ConnectionRetryEvent,
    DisconnectedEvent,
    IncomingConnectionEvent,
    IpcEvent,
    JsonValue,
    MaxConnectionsReachedEvent,
    NoPendingConnectionEvent,
    PendingConnectionExpiredEvent,
    PeerNotFoundEvent,
)

from metor.ui.chat.event.protocols import EventHandlerProtocol


def handle_transport_event(handler: EventHandlerProtocol, event: IpcEvent) -> bool:
    """
    Handles connection lifecycle and transport status events.

    Args:
        handler (EventHandlerProtocol): The owning EventHandler instance.
        event (IpcEvent): The incoming IPC event.

    Returns:
        bool: True when the event was handled.
    """
    if isinstance(event, IncomingConnectionEvent):
        handler._remember_peer(event.alias, event.onion)
        if event.alias not in handler._session.pending_connections:
            handler._session.pending_connections.append(event.alias)
        handler._print_translated(
            event.event_type,
            {'origin': event.origin, 'actor': event.actor},
            alias=event.alias,
            onion=event.onion,
        )
        return True

    if isinstance(event, ConnectionPendingEvent):
        handler._remember_peer(event.alias, event.onion)
        if event.alias not in handler._session.pending_connections:
            handler._session.pending_connections.append(event.alias)
        handler._print_translated(
            event.event_type,
            {'origin': event.origin, 'actor': event.actor},
            alias=event.alias,
            onion=event.onion,
        )
        return True

    if isinstance(event, ConnectionConnectingEvent):
        handler._remember_peer(event.alias, event.onion)
        handler._print_translated(
            event.event_type,
            {'origin': event.origin, 'actor': event.actor},
            alias=event.alias,
            onion=event.onion,
        )
        return True

    if isinstance(event, ConnectionAutoAcceptedEvent):
        handler._remember_peer(event.alias, event.onion)
        if event.alias in handler._session.pending_connections:
            handler._session.pending_connections.remove(event.alias)
        handler._print_translated(
            event.event_type,
            {'origin': event.origin, 'actor': event.actor},
            alias=event.alias,
            onion=event.onion,
        )
        return True

    if isinstance(event, ConnectionRetryEvent):
        handler._remember_peer(event.alias, event.onion)
        handler._print_translated(
            event.event_type,
            {
                'attempt': event.attempt,
                'max_retries': event.max_retries,
                'origin': event.origin,
                'actor': event.actor,
            },
            alias=event.alias,
            onion=event.onion,
        )
        return True

    if isinstance(event, NoPendingConnectionEvent):
        if handler._matches_focus_target(
            handler._session.pending_accept_focus_target,
            alias=event.alias,
            onion=event.onion,
        ):
            handler._session.pending_accept_focus_target = None
        handler._remember_peer(event.alias, event.onion)
        handler._print_translated(
            event.event_type,
            alias=event.alias,
            onion=event.onion,
        )
        return True

    if isinstance(event, PendingConnectionExpiredEvent):
        if handler._matches_focus_target(
            handler._session.pending_accept_focus_target,
            alias=event.alias,
            onion=event.onion,
        ):
            handler._session.pending_accept_focus_target = None
        handler._remember_peer(event.alias, event.onion)
        handler._print_translated(
            event.event_type,
            alias=event.alias,
            onion=event.onion,
        )
        return True

    if isinstance(event, PeerNotFoundEvent):
        if handler._matches_focus_target(
            handler._session.pending_focus_target,
            alias=event.target,
            onion=event.target,
        ):
            handler._session.pending_focus_target = None
        if handler._matches_focus_target(
            handler._session.pending_accept_focus_target,
            alias=event.target,
            onion=event.target,
        ):
            handler._session.pending_accept_focus_target = None
        handler._print_translated(event.event_type, {'target': event.target})
        return True

    if isinstance(event, MaxConnectionsReachedEvent):
        if handler._matches_focus_target(
            handler._session.pending_focus_target,
            alias=event.target,
            onion=event.target,
        ):
            handler._session.pending_focus_target = None
        handler._print_translated(
            event.event_type,
            {'max_conn': event.max_conn},
            alias=event.target,
        )
        return True

    if isinstance(event, ConnectionFailedEvent):
        if event.alias in handler._session.pending_connections:
            handler._session.pending_connections.remove(event.alias)
        if handler._matches_focus_target(
            handler._session.pending_focus_target,
            alias=event.alias,
            onion=event.onion,
        ):
            handler._session.pending_focus_target = None
        if handler._matches_focus_target(
            handler._session.pending_accept_focus_target,
            alias=event.alias,
            onion=event.onion,
        ):
            handler._session.pending_accept_focus_target = None
        handler._remember_peer(event.alias, event.onion)
        error_params: Dict[str, JsonValue] = {}
        if event.error:
            error_params['error'] = event.error
        error_params['origin'] = event.origin
        error_params['actor'] = event.actor
        error_params['reason_code'] = event.reason_code
        handler._print_translated(
            event.event_type,
            error_params or None,
            alias=event.alias,
            onion=event.onion,
        )
        return True

    if isinstance(event, ConnectionRejectedEvent):
        if event.reason_code is ConnectionReasonCode.MUTUAL_TIEBREAKER_LOSER:
            handler._remember_peer(event.alias, event.onion)
            return True

        if event.alias in handler._session.pending_connections:
            handler._session.pending_connections.remove(event.alias)
        if handler._matches_focus_target(
            handler._session.pending_focus_target,
            alias=event.alias,
            onion=event.onion,
        ):
            handler._session.pending_focus_target = None
        if handler._matches_focus_target(
            handler._session.pending_accept_focus_target,
            alias=event.alias,
            onion=event.onion,
        ):
            handler._session.pending_accept_focus_target = None
        handler._remember_peer(event.alias, event.onion)
        handler._print_translated(
            event.event_type,
            {
                'origin': event.origin,
                'actor': event.actor,
                'reason_code': event.reason_code,
            },
            alias=event.alias,
            onion=event.onion,
        )
        return True

    if isinstance(event, AutoReconnectScheduledEvent):
        handler._remember_peer(event.alias, event.onion)
        handler._print_translated(
            event.event_type,
            {'origin': event.origin, 'actor': event.actor},
            alias=event.alias,
            onion=event.onion,
        )
        return True

    if isinstance(event, ConnectedEvent):
        handler._remember_peer(event.alias, event.onion)
        if event.alias not in handler._session.active_connections:
            handler._session.active_connections.append(event.alias)
        if event.alias in handler._session.pending_connections:
            handler._session.pending_connections.remove(event.alias)

        handler._print_translated(
            event.event_type,
            {'origin': event.origin, 'actor': event.actor},
            alias=event.alias,
            onion=event.onion,
        )

        if handler._session.focused_alias == event.alias:
            handler._renderer.set_focus(event.alias, is_live=True)

        should_auto_focus: bool = False
        if handler._matches_focus_target(
            handler._session.pending_focus_target,
            alias=event.alias,
            onion=event.onion,
        ):
            handler._session.pending_focus_target = None
            should_auto_focus = True

        if handler._matches_focus_target(
            handler._session.pending_accept_focus_target,
            alias=event.alias,
            onion=event.onion,
        ):
            handler._session.pending_accept_focus_target = None
            should_auto_focus = True

        if should_auto_focus:
            handler._switch_focus(event.alias, sync_daemon=True)
        return True

    if isinstance(event, DisconnectedEvent):
        handler._remember_peer(event.alias, event.onion)
        handler._print_translated(
            event.event_type,
            {
                'origin': event.origin,
                'actor': event.actor,
                'reason_code': event.reason_code,
            },
            alias=event.alias,
            onion=event.onion,
        )

        if event.alias in handler._session.active_connections:
            handler._session.active_connections.remove(event.alias)
        if event.alias in handler._session.pending_connections:
            handler._session.pending_connections.remove(event.alias)

        if handler._session.focused_alias == event.alias:
            handler._renderer.set_focus(event.alias, is_live=False)
        return True

    return False
