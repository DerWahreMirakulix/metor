"""Connection rejection and disconnect helpers for the connection controller."""

import socket
import time
from typing import Any, Dict, Optional, Tuple

from metor.core.api import (
    AutoReconnectScheduledEvent,
    ConnectionActor,
    ConnectionFailedEvent,
    ConnectionOrigin,
    ConnectionReasonCode,
    ConnectionRejectedEvent,
    ContactRemovedEvent,
    DisconnectedEvent,
    EventType,
    FallbackSuccessEvent,
    PeerNotFoundEvent,
    create_event,
)
from metor.core.daemon.models import TorCommand
from metor.data import (
    HistoryActor,
    HistoryEvent,
    HistoryReasonCode,
    MessageDirection,
    MessageStatus,
    MessageType,
    SettingKey,
)


def _close_socket(sock: socket.socket) -> None:
    """
    Closes one socket while suppressing transport teardown noise.

    Args:
        sock (socket.socket): The socket to close.

    Returns:
        None
    """
    try:
        sock.close()
    except OSError:
        pass


def reject(
    controller: Any,
    target: str,
    initiated_by_self: bool = True,
    socket_to_close: Optional[socket.socket] = None,
    origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
) -> None:
    """
    Rejects one pending or in-flight connection attempt.

    Args:
        controller (Any): The owning connection controller instance.
        target (str): The target alias or onion.
        initiated_by_self (bool): Whether the local user initiated the rejection.
        socket_to_close (Optional[socket.socket]): Specific duplicate socket to terminate safely.
        origin (ConnectionOrigin): The machine-readable source of the rejected live flow.

    Returns:
        None
    """
    resolved: Optional[Tuple[str, str]] = controller._cm.resolve_target(target)
    if not resolved:
        if initiated_by_self:
            controller._broadcast(PeerNotFoundEvent(target=target))
        return
    alias, onion = resolved

    if initiated_by_self:
        controller._state.clear_scheduled_auto_reconnect(onion)
        controller._state.discard_outbound_attempt(onion)

    inflight_outbound: bool = False

    if socket_to_close and not controller._state.is_known_socket(
        onion, socket_to_close
    ):
        inflight_outbound = controller._is_inflight_outbound_socket(
            onion,
            socket_to_close,
        )
        if not inflight_outbound:
            if not initiated_by_self:
                controller._mark_live_reconnect_grace(onion)
            controller._discard_outbound_attempt_if_idle(onion)
            _close_socket(socket_to_close)
            return

    status: HistoryEvent = HistoryEvent.LIVE_REJECTED
    reject_actor: HistoryActor = (
        HistoryActor.LOCAL if initiated_by_self else HistoryActor.REMOTE
    )

    if inflight_outbound:
        controller._state.discard_outbound_attempt(onion)
        if socket_to_close:
            _close_socket(socket_to_close)

        if controller._state.is_connected_or_pending(onion):
            return

        controller._hm.log_event(
            status,
            onion,
            actor=reject_actor,
            trigger=origin,
            detail_code=HistoryReasonCode.OUTBOUND_ATTEMPT_REJECTED,
        )

        if controller._state.is_retunneling(onion):
            controller._schedule_retunnel_recovery_retry(
                alias,
                onion,
                'Outbound attempt rejected',
            )
            return

        if origin is ConnectionOrigin.AUTO_RECONNECT:
            controller._state.clear_scheduled_auto_reconnect(onion)

        controller._broadcast(
            ConnectionRejectedEvent(
                alias=alias,
                onion=onion,
                origin=origin,
                actor=(
                    ConnectionActor.LOCAL
                    if initiated_by_self
                    else ConnectionActor.REMOTE
                ),
                reason_code=ConnectionReasonCode.OUTBOUND_ATTEMPT_REJECTED,
            )
        )
        return

    conn: Optional[socket.socket] = controller._state.pop_any_connection(onion)

    if not conn and not inflight_outbound:
        controller._discard_outbound_attempt_if_idle(onion)
        if initiated_by_self:
            controller._broadcast(
                create_event(
                    EventType.NO_CONNECTION_TO_REJECT,
                    {'alias': alias, 'onion': onion},
                )
            )
        return

    if conn is not None and initiated_by_self:
        try:
            conn.sendall(
                f'{TorCommand.REJECT.value} {controller._tm.onion}\n'.encode('utf-8')
            )
        except OSError:
            pass

    if conn is not None:
        _close_socket(conn)

    controller._hm.log_event(status, onion, actor=reject_actor, trigger=origin)

    if origin is ConnectionOrigin.AUTO_RECONNECT or not initiated_by_self:
        controller._state.clear_scheduled_auto_reconnect(onion)

    controller._broadcast(
        ConnectionRejectedEvent(
            alias=alias,
            onion=onion,
            origin=origin,
            actor=(
                ConnectionActor.LOCAL if initiated_by_self else ConnectionActor.REMOTE
            ),
        )
    )


def disconnect(
    controller: Any,
    target: str,
    initiated_by_self: bool = True,
    is_fallback: bool = False,
    socket_to_close: Optional[socket.socket] = None,
    suppress_events: bool = False,
    origin: Optional[ConnectionOrigin] = None,
) -> None:
    """
    Disconnects one active or pending live flow and processes fallback promotion.

    Args:
        controller (Any): The owning connection controller instance.
        target (str): The target alias or onion.
        initiated_by_self (bool): Whether the local user initiated the disconnect.
        is_fallback (bool): Whether the disconnect came from an unexpected network failure.
        socket_to_close (Optional[socket.socket]): Specific duplicate socket to safely terminate.
        suppress_events (bool): Whether lifecycle events should be suppressed.
        origin (Optional[ConnectionOrigin]): The machine-readable source of the disconnected flow.

        Returns:
            None
    """
    resolved: Optional[Tuple[str, str]] = controller._cm.resolve_target(target)
    if not resolved:
        if initiated_by_self:
            controller._broadcast(PeerNotFoundEvent(target=target))
        return
    alias, onion = resolved

    if initiated_by_self:
        controller._state.clear_scheduled_auto_reconnect(onion)
        controller._state.discard_outbound_attempt(onion)

    inflight_outbound: bool = False

    if socket_to_close and not controller._state.is_known_socket(
        onion, socket_to_close
    ):
        inflight_outbound = controller._is_inflight_outbound_socket(
            onion,
            socket_to_close,
        )
        if not inflight_outbound:
            if not initiated_by_self:
                controller._mark_live_reconnect_grace(onion)
            controller._discard_outbound_attempt_if_idle(onion)
            _close_socket(socket_to_close)
            return

    if inflight_outbound:
        controller._state.discard_outbound_attempt(onion)
        if socket_to_close:
            _close_socket(socket_to_close)

        if controller._state.is_connected_or_pending(onion):
            return

        controller._hm.log_event(
            HistoryEvent.LIVE_CONNECTION_LOST,
            onion,
            actor=HistoryActor.SYSTEM,
            trigger=origin,
            detail_code=HistoryReasonCode.OUTBOUND_ATTEMPT_CLOSED_BEFORE_ACCEPTANCE,
        )
        if controller._state.is_retunneling(onion):
            controller._schedule_retunnel_recovery_retry(
                alias,
                onion,
                'Outbound attempt closed before acceptance',
            )
        else:
            if origin is ConnectionOrigin.AUTO_RECONNECT:
                controller._state.clear_scheduled_auto_reconnect(onion)
            controller._broadcast(
                ConnectionFailedEvent(
                    alias=alias,
                    onion=onion,
                    error='Outbound attempt closed before acceptance',
                    origin=origin or ConnectionOrigin.MANUAL,
                    actor=ConnectionActor.SYSTEM,
                    reason_code=(
                        ConnectionReasonCode.OUTBOUND_ATTEMPT_CLOSED_BEFORE_ACCEPTANCE
                    ),
                )
            )
        return

    conn: Optional[socket.socket] = controller._state.pop_any_connection(onion)
    unacked: Dict[str, Tuple[str, str]] = {}

    if controller._config.get_bool(SettingKey.FALLBACK_TO_DROP):
        unacked = controller._state.pop_unacked_messages(onion)

    if not conn and not unacked and not inflight_outbound:
        if not initiated_by_self:
            controller._mark_live_reconnect_grace(onion)
        controller._discard_outbound_attempt_if_idle(onion)
        if initiated_by_self and not suppress_events:
            controller._broadcast(
                create_event(
                    EventType.NO_CONNECTION_TO_DISCONNECT,
                    {'alias': alias, 'onion': onion},
                )
            )
        return

    if unacked:
        for msg_id, pending_msg in unacked.items():
            content, timestamp = pending_msg
            controller._mm.queue_message(
                contact_onion=onion,
                direction=MessageDirection.OUT,
                msg_type=MessageType.DROP_TEXT,
                payload=content,
                status=MessageStatus.PENDING,
                msg_id=msg_id,
                timestamp=timestamp,
            )
            controller._hm.log_event(
                HistoryEvent.DROP_QUEUED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_code=HistoryReasonCode.UNACKED_LIVE_CONVERTED_TO_DROP,
            )
        if not suppress_events:
            controller._broadcast(
                FallbackSuccessEvent(
                    alias=alias,
                    onion=onion,
                    count=len(unacked),
                    msg_ids=list(unacked.keys()),
                )
            )

    if conn:
        if initiated_by_self:
            try:
                conn.sendall(
                    f'{TorCommand.DISCONNECT.value} {controller._tm.onion}\n'.encode(
                        'utf-8'
                    )
                )
                linger_timeout_sec: float = controller._config.get_float(
                    SettingKey.LIVE_DISCONNECT_LINGER_TIMEOUT
                )
                if linger_timeout_sec > 0:
                    time.sleep(linger_timeout_sec)
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        _close_socket(conn)

    if is_fallback:
        status = HistoryEvent.LIVE_CONNECTION_LOST
        disconnect_actor: HistoryActor = HistoryActor.SYSTEM
    else:
        status = HistoryEvent.LIVE_DISCONNECTED
        disconnect_actor = (
            HistoryActor.LOCAL if initiated_by_self else HistoryActor.REMOTE
        )
    controller._hm.log_event(
        status,
        onion,
        actor=disconnect_actor,
        trigger=origin,
    )

    if not suppress_events:
        controller._broadcast(
            DisconnectedEvent(
                alias=alias,
                onion=onion,
                actor=(
                    ConnectionActor.SYSTEM
                    if is_fallback
                    else (
                        ConnectionActor.LOCAL
                        if initiated_by_self
                        else ConnectionActor.REMOTE
                    )
                ),
                origin=origin or ConnectionOrigin.MANUAL,
            )
        )

    if not initiated_by_self:
        controller._mark_live_reconnect_grace(onion)

    deleted_peers: list[Tuple[str, str]] = controller._cm.cleanup_orphans(
        controller._state.get_active_onions()
    )
    for removed_alias, removed_onion in deleted_peers:
        controller._broadcast(
            ContactRemovedEvent(alias=removed_alias, onion=removed_onion)
        )

    if is_fallback and controller._get_live_reconnect_delay() > 0:
        controller._state.mark_scheduled_auto_reconnect(onion)
        was_scheduled: bool = controller._enqueue_live_reconnect(onion)
        if was_scheduled:
            controller._hm.log_event(
                HistoryEvent.LIVE_AUTO_RECONNECT_SCHEDULED,
                onion,
                actor=HistoryActor.SYSTEM,
                trigger=ConnectionOrigin.AUTO_RECONNECT,
            )
            controller._broadcast(
                AutoReconnectScheduledEvent(
                    alias=alias,
                    onion=onion,
                    origin=ConnectionOrigin.AUTO_RECONNECT,
                    actor=ConnectionActor.SYSTEM,
                )
            )
