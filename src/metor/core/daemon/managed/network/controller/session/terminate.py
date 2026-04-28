"""Connection rejection and disconnect helpers for the connection controller."""

import socket
import threading
import time
from typing import Dict, Optional, Tuple

from metor.core.api import (
    AutoReconnectScheduledEvent,
    ConnectionActor,
    ConnectionConnectingEvent,
    ConnectionFailedEvent,
    ConnectionOrigin,
    ConnectionReasonCode,
    ConnectionRejectedEvent,
    ContactRemovedEvent,
    DisconnectedEvent,
    EventType,
    PeerNotFoundEvent,
    create_event,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    HistoryActor,
    HistoryEvent,
    HistoryReasonCode,
    SettingKey,
)
from metor.utils import Constants

from metor.core.daemon.managed.network.controller.session.protocols import (
    TerminateControllerProtocol,
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


def _sleep_reconnect_grace(controller: TerminateControllerProtocol) -> None:
    """
    Waits for the configured reconnect-grace window while respecting shutdown.

    Args:
        controller (TerminateControllerProtocol): The owning connection controller instance.

    Returns:
        None
    """
    remaining_sec: float = float(
        controller._config.get_int(SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT)
    )
    while remaining_sec > 0:
        if controller._stop_flag.is_set():
            return

        sleep_sec: float = min(Constants.WORKER_SLEEP_SEC, remaining_sec)
        time.sleep(sleep_sec)
        remaining_sec -= sleep_sec


def _finalize_deferred_remote_fallback(
    controller: TerminateControllerProtocol,
    alias: str,
    onion: str,
    origin: Optional[ConnectionOrigin],
) -> None:
    """
    Emits a delayed remote-fallback disconnect only if recovery never arrived.

    Args:
        controller (TerminateControllerProtocol): The owning connection controller instance.
        alias (str): The peer alias.
        onion (str): The peer onion identity.
        origin (Optional[ConnectionOrigin]): The original disconnect origin.

    Returns:
        None
    """
    _sleep_reconnect_grace(controller)
    if controller._stop_flag.is_set():
        return

    if controller._state.is_connected_or_pending(onion):
        return

    if controller._state.has_outbound_attempt(onion):
        return

    controller._state.mark_live_reconnect_grace(onion, 0.0)
    controller._hm.log_event(
        HistoryEvent.CONNECTION_LOST,
        onion,
        actor=HistoryActor.SYSTEM,
        trigger=origin,
    )
    controller._broadcast(
        DisconnectedEvent(
            alias=alias,
            onion=onion,
            actor=ConnectionActor.SYSTEM,
            origin=origin or ConnectionOrigin.MANUAL,
        )
    )

    deleted_peers: list[Tuple[str, str]] = controller._cm.cleanup_orphans(
        controller._state.get_active_onions()
    )
    for removed_alias, removed_onion in deleted_peers:
        controller._broadcast(
            ContactRemovedEvent(alias=removed_alias, onion=removed_onion)
        )

    if controller._get_live_reconnect_delay() <= 0:
        return

    controller._state.mark_scheduled_auto_reconnect(onion)
    was_scheduled: bool = controller._enqueue_live_reconnect(onion)
    if not was_scheduled:
        return

    controller._hm.log_event(
        HistoryEvent.AUTO_RECONNECT_SCHEDULED,
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


def reject(
    controller: TerminateControllerProtocol,
    target: str,
    initiated_by_self: bool = True,
    socket_to_close: Optional[socket.socket] = None,
    origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
) -> None:
    """
    Rejects one pending or in-flight connection attempt.

    Args:
        controller (TerminateControllerProtocol): The owning connection controller instance.
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

    status: HistoryEvent = HistoryEvent.REJECTED
    reject_actor: HistoryActor = (
        HistoryActor.LOCAL if initiated_by_self else HistoryActor.REMOTE
    )

    if inflight_outbound:
        controller._state.discard_outbound_attempt(onion)
        if socket_to_close:
            _close_socket(socket_to_close)

        if controller._state.is_connected_or_pending(onion):
            if controller._state.is_retunneling(
                onion
            ) and controller._state.is_live_active(onion):
                controller._broadcast_retunnel_preserved_failure(
                    alias,
                    onion,
                    'Outbound attempt rejected',
                )
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
            controller._convert_unacked_live_to_drops(alias, onion)

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
    controller: TerminateControllerProtocol,
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
        controller (TerminateControllerProtocol): The owning connection controller instance.
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
    defer_remote_fallback: bool = (
        is_fallback
        and not initiated_by_self
        and controller._config.get_int(SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT) > 0
    )

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
            if controller._state.is_retunneling(
                onion
            ) and controller._state.is_live_active(onion):
                controller._broadcast_retunnel_preserved_failure(
                    alias,
                    onion,
                    'Outbound attempt closed before acceptance',
                )
            return

        controller._hm.log_event(
            HistoryEvent.CONNECTION_LOST,
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
                controller._convert_unacked_live_to_drops(alias, onion)
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
    retain_unacked_for_recovery: bool = (
        controller._state.is_retunneling(onion)
        or defer_remote_fallback
        or (is_fallback and controller._get_live_reconnect_delay() > 0)
    )

    if (
        controller._config.get_bool(SettingKey.FALLBACK_TO_DROP)
        and not retain_unacked_for_recovery
    ):
        unacked = controller._state.pop_unacked_messages(onion)

    held_unacked_messages: bool = bool(
        retain_unacked_for_recovery and controller._state.has_unacked_messages(onion)
    )

    if not conn and not unacked and not inflight_outbound and not held_unacked_messages:
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
        controller._convert_unacked_live_to_drops(
            alias,
            onion,
            emit_event=not suppress_events,
        )

    if conn:
        if initiated_by_self:
            try:
                conn.sendall(
                    f'{TorCommand.DISCONNECT.value} {controller._tm.onion}\n'.encode(
                        'utf-8'
                    )
                )
                try:
                    conn.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                linger_timeout_sec: float = controller._config.get_float(
                    SettingKey.LIVE_DISCONNECT_LINGER_TIMEOUT
                )
                if linger_timeout_sec > 0:
                    time.sleep(linger_timeout_sec)
            except OSError:
                pass
        _close_socket(conn)

    if defer_remote_fallback:
        controller._mark_live_reconnect_grace(onion)
        if not suppress_events:
            controller._broadcast(
                ConnectionConnectingEvent(
                    alias=alias,
                    onion=onion,
                    origin=ConnectionOrigin.GRACE_RECONNECT,
                    actor=ConnectionActor.SYSTEM,
                )
            )
        threading.Thread(
            target=_finalize_deferred_remote_fallback,
            args=(controller, alias, onion, origin),
            daemon=True,
        ).start()
        return

    if is_fallback:
        status = HistoryEvent.CONNECTION_LOST
        disconnect_actor: HistoryActor = HistoryActor.SYSTEM
    else:
        status = HistoryEvent.DISCONNECTED
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
                HistoryEvent.AUTO_RECONNECT_SCHEDULED,
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
