"""Pending-connection acceptance helpers for the connection controller."""

from typing import Optional, Tuple

from metor.core.api import (
    ConnectedEvent,
    ConnectionActor,
    ConnectionOrigin,
    ConnectionReasonCode,
    EventType,
    PendingConnectionExpiredEvent,
    PeerNotFoundEvent,
    RetunnelSuccessEvent,
    create_event,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import HistoryActor, HistoryEvent, HistoryReasonCode

from metor.core.daemon.managed.network.controller.session.protocols import (
    AcceptControllerProtocol,
)


def accept(
    controller: AcceptControllerProtocol,
    target: str,
    origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
) -> None:
    """
    Accepts one pending connection and transitions it into the active state.

    Args:
        controller (AcceptControllerProtocol): The owning connection controller instance.
        target (str): The target alias or onion.
        origin (ConnectionOrigin): The machine-readable source of the accepted live flow.

    Returns:
        None
    """
    resolved: Optional[Tuple[str, str]] = controller._cm.resolve_target(target)
    if not resolved:
        controller._broadcast(PeerNotFoundEvent(target=target))
        return
    alias, onion = resolved

    conn, initial_buffer, _, pending_origin = controller._state.pop_pending_connection(
        onion
    )
    if not conn:
        if controller._state.is_retunneling(onion):
            controller._hm.log_event(
                HistoryEvent.CONNECTION_LOST,
                onion,
                actor=HistoryActor.SYSTEM,
                trigger=origin,
                detail_code=HistoryReasonCode.RETUNNEL_PENDING_CONNECTION_MISSING,
            )
            if controller._state.is_live_active(onion):
                controller._broadcast_retunnel_preserved_failure(
                    alias,
                    onion,
                    'Retunnel pending connection missing',
                )
            else:
                controller._broadcast_retunnel_failure(
                    alias,
                    onion,
                    'Retunnel pending connection missing',
                )
            return
        if controller._state.consume_recent_pending_expiry(onion):
            controller._broadcast(
                PendingConnectionExpiredEvent(
                    alias=alias,
                    onion=onion,
                    origin=origin,
                    actor=ConnectionActor.SYSTEM,
                    reason_code=ConnectionReasonCode.PENDING_ACCEPTANCE_EXPIRED,
                )
            )
            return
        controller._broadcast(
            create_event(
                EventType.NO_PENDING_CONNECTION,
                {'alias': alias, 'onion': onion},
            )
        )
        return

    try:
        conn.sendall(f'{TorCommand.ACCEPTED.value}\n'.encode('utf-8'))
    except OSError:
        controller._hm.log_event(
            HistoryEvent.CONNECTION_LOST,
            onion,
            actor=HistoryActor.SYSTEM,
            trigger=origin,
            detail_code=HistoryReasonCode.LATE_ACCEPTANCE_TIMEOUT,
        )
        if controller._state.is_retunneling(onion):
            if controller._state.is_live_active(onion):
                controller._broadcast_retunnel_preserved_failure(
                    alias,
                    onion,
                    'Late acceptance timeout',
                )
            else:
                controller._broadcast_retunnel_failure(
                    alias,
                    onion,
                    'Late acceptance timeout',
                )
        else:
            controller._broadcast(
                PendingConnectionExpiredEvent(
                    alias=alias,
                    onion=onion,
                    origin=pending_origin or origin,
                    actor=ConnectionActor.SYSTEM,
                    reason_code=ConnectionReasonCode.LATE_ACCEPTANCE_TIMEOUT,
                )
            )
        try:
            conn.close()
        except OSError:
            pass
        return

    controller._state.add_active_connection(onion, conn)
    controller._hm.log_event(
        HistoryEvent.CONNECTED,
        onion,
        actor=controller._get_local_history_actor(origin),
        trigger=origin,
    )
    if controller._state.consume_retunnel_reconnect(onion):
        controller._hm.log_event(
            HistoryEvent.RETUNNEL_SUCCEEDED,
            onion,
            actor=HistoryActor.SYSTEM,
        )
        controller._state.clear_retunnel_flow(onion)
        controller._broadcast(RetunnelSuccessEvent(alias=alias, onion=onion))
    else:
        controller._broadcast(
            ConnectedEvent(
                alias=alias,
                onion=onion,
                origin=origin,
                actor=controller._get_local_connection_actor(origin),
            )
        )

    if controller._receiver:
        controller._receiver.start_receiving(
            onion,
            conn,
            initial_buffer,
            connection_origin=origin,
        )
