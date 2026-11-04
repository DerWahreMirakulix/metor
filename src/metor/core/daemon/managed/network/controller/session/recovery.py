"""Transport loss and delayed retries within an already accepted LIVE scope."""

import socket
import threading
import time
from typing import Optional

from metor.core.api import (
    AutoReconnectScheduledEvent,
    ConnectionActor,
    ConnectionConnectingEvent,
    ConnectionOrigin,
    ConnectionReasonCode,
    DisconnectedEvent,
)
from metor.data import HistoryActor, HistoryEvent, HistoryReasonCode, SettingKey

# Local Package Imports
from .protocols import ConnectControllerProtocol, TerminateControllerProtocol


def _expire_accepted_recovery(
    controller: ConnectControllerProtocol | TerminateControllerProtocol,
    alias: str,
    onion: str,
    generation: int,
    deadline: float,
) -> None:
    """Ends only the unrecovered scope after its configured grace deadline.

    A successful transport, End, replacement context, or later loss invalidates
    this timer. Pending publication follows the existing fallback setting.
    """
    if controller._stop_flag.wait(max(0.0, deadline - time.monotonic())):
        return
    with controller._operation_lock, controller._state.snapshot_barrier():
        if not controller._state.expire_accepted_live_recovery(
            onion, generation, deadline
        ):
            return
        outbound = controller._state.pop_outbound_socket(onion)
        pending = controller._state.pop_any_connection(onion)
        controller._state.clear_retunnel_flow(onion)
        if pending is not None:
            controller._state.retire_connection(pending)
        if outbound is not None and outbound is not pending:
            controller._state.retire_connection(outbound)
        controller._state.mark_live_reconnect_grace(onion, 0.0)
        controller._state.clear_scheduled_auto_reconnect(onion)
        if controller._config.get_bool(SettingKey.FALLBACK_TO_DROP):
            controller._convert_unacked_live_to_drops(alias, onion)
        controller._state.set_last_disconnect_reason(
            onion, ConnectionReasonCode.RETRY_EXHAUSTED, ConnectionActor.SYSTEM
        )
        controller._hm.log_event(
            HistoryEvent.CONNECTION_LOST,
            onion,
            actor=HistoryActor.SYSTEM,
            trigger=ConnectionOrigin.AUTO_RECONNECT,
            detail_code=HistoryReasonCode.RETRY_EXHAUSTED,
        )
        controller._broadcast(
            DisconnectedEvent(
                alias=alias,
                onion=onion,
                actor=ConnectionActor.SYSTEM,
                origin=ConnectionOrigin.AUTO_RECONNECT,
                reason_code=ConnectionReasonCode.RETRY_EXHAUSTED,
            )
        )


def start_accepted_recovery_timer(
    controller: TerminateControllerProtocol,
    alias: str,
    onion: str,
    generation: int,
) -> Optional[float]:
    """Starts one timer for the configured loss deadline without renewing consent.

    Args:
        controller: Owning lifecycle controller.
        alias: Already resolved peer label.
        onion: Canonical original peer.
        generation: Accepted scope before transport teardown.
    Returns:
        Optional[float]: Original monotonic deadline, absent after shutdown or End.
    """
    with controller._state.snapshot_barrier():
        if controller._stop_flag.is_set():
            return None
        previous_deadline = controller._state.accepted_live_recovery_deadline(onion)
        deadline = controller._state.begin_accepted_live_recovery(
            onion,
            float(controller._config.get_int(SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT)),
        )
        if deadline is not None and previous_deadline is None:
            threading.Thread(
                target=_expire_accepted_recovery,
                args=(controller, alias, onion, generation, deadline),
                daemon=True,
            ).start()
        return deadline


def schedule_accepted_recovery(
    controller: ConnectControllerProtocol | TerminateControllerProtocol,
    alias: str,
    onion: str,
    generation: int,
    *,
    emit_event: bool = True,
) -> bool:
    """Queues another bounded attempt only while the original scope is accepted.

    The state barrier serializes admission with End, grace expiry and
    replacement. A zero delay disables automatic work while configured grace
    still permits an authenticated peer recovery.

    Args:
        controller: Owning session lifecycle controller.
        alias: Already resolved peer label.
        onion: Canonical authenticated peer identity.
        generation: Accepted scope captured before the failed work.
        emit_event: Publish an absolute scheduled-recovery projection update.
    Returns:
        bool: Whether the original accepted scope remains eligible.
    """
    with controller._state.snapshot_barrier():
        if controller._stop_flag.is_set():
            return False
        if controller._state.accepted_live_context_generation(onion) != generation:
            return False
        if controller._state.is_connected_or_pending(onion):
            return True
        if controller._get_live_reconnect_delay() <= 0:
            controller._state.clear_scheduled_auto_reconnect(onion)
            return True
        controller._state.mark_scheduled_auto_reconnect(onion)
        was_queued = controller._enqueue_live_reconnect(onion)
        if emit_event and was_queued:
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
        return True


def recover_accepted_transport(
    controller: TerminateControllerProtocol,
    alias: str,
    onion: str,
    generation: int,
    socket_to_close: Optional[socket.socket],
    *,
    suppress_events: bool = False,
) -> None:
    """Retires one exact failed transport without ending its accepted scope.

    Args:
        controller: Owning session lifecycle controller.
        alias: Already resolved peer label.
        onion: Canonical peer identity.
        generation: Original accepted scope identity.
        socket_to_close: Exact socket from the receiver/writer loss callback.
        suppress_events: Suppress outward transport lifecycle updates.
    Returns:
        None
    """
    with controller._state.snapshot_barrier():
        if controller._state.accepted_live_context_generation(onion) != generation:
            if socket_to_close is not None:
                controller._state.retire_connection(socket_to_close)
            return
        if socket_to_close is not None and not (
            controller._state.is_known_socket(onion, socket_to_close)
            or controller._state.is_current_outbound_socket(onion, socket_to_close)
        ):
            controller._state.retire_connection(socket_to_close)
            return
        previous_deadline = controller._state.accepted_live_recovery_deadline(onion)
        deadline = start_accepted_recovery_timer(controller, alias, onion, generation)
        if deadline is None:
            return
        outbound = controller._state.pop_outbound_socket(onion)
        conn = controller._state.pop_any_connection(onion)
        if conn is not None:
            controller._state.retire_connection(conn)
        if outbound is not None and outbound is not conn:
            controller._state.retire_connection(outbound)
        controller._mark_live_reconnect_grace(onion)
        retunneling = controller._state.is_retunneling(onion)
        if not suppress_events and previous_deadline is None and not retunneling:
            controller._broadcast(
                ConnectionConnectingEvent(
                    alias=alias,
                    onion=onion,
                    origin=ConnectionOrigin.GRACE_RECONNECT,
                    actor=ConnectionActor.SYSTEM,
                )
            )
        if not retunneling:
            schedule_accepted_recovery(
                controller, alias, onion, generation, emit_event=not suppress_events
            )
