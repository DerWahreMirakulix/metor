"""Outbound connection setup helpers for the connection controller."""

import socket
from typing import Optional, Tuple

from metor.core.api import (
    ConnectionActor,
    ConnectionAutoAcceptedEvent,
    ConnectionConnectingEvent,
    ConnectionFailedEvent,
    ConnectionOrigin,
    ConnectionReasonCode,
    ConnectionRetryEvent,
    DisconnectedEvent,
    EventType,
    MaxConnectionsReachedEvent,
    RuntimeErrorCode,
    create_event,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    HistoryActor,
    HistoryEvent,
    HistoryReasonCode,
    SettingKey,
)

# Local Package Imports
from metor.core.daemon.managed.network.handshake import HandshakeProtocol
from metor.core.daemon.managed.network.controller.session.protocols import (
    ConnectControllerProtocol,
)
from metor.core.daemon.managed.network.stream import TcpStreamReader


def _close_socket(conn: Optional[socket.socket]) -> None:
    """
    Closes one failed outbound socket quietly.

    Args:
        conn (Optional[socket.socket]): The socket to close.

    Returns:
        None
    """
    if conn is None:
        return

    try:
        conn.close()
    except OSError:
        pass


def connect_to(
    controller: ConnectControllerProtocol,
    target: str,
    origin: ConnectionOrigin = ConnectionOrigin.MANUAL,
) -> None:
    """
    Initiates one outbound live connection attempt with retry and retunnel handling.

    Args:
        controller (ConnectControllerProtocol): The owning connection controller instance.
        target (str): The alias or onion address to connect to.
        origin (ConnectionOrigin): The machine-readable source of the connection attempt.

    Returns:
        None
    """
    resolved: Optional[Tuple[str, str]] = controller._cm.resolve_target_for_interaction(
        target
    )
    if not resolved or resolved[1] == controller._tm.onion:
        return
    alias, onion = resolved
    retunnel_reconnect: bool = (
        origin is ConnectionOrigin.RETUNNEL and controller._state.is_retunneling(onion)
    )

    if origin is not ConnectionOrigin.AUTO_RECONNECT:
        controller._state.clear_scheduled_auto_reconnect(onion)

    if controller._state.get_connection(onion) and not retunnel_reconnect:
        return

    implicit_accept: bool = False
    if onion in controller._state.get_pending_connections_keys():
        implicit_accept = True
    else:
        controller._state.add_outbound_attempt(onion, origin=origin)

    if implicit_accept:
        controller._broadcast(
            ConnectionAutoAcceptedEvent(
                alias=alias,
                onion=onion,
                origin=origin,
                actor=controller._get_local_connection_actor(origin),
            )
        )
        controller.accept(target, origin=origin)
        return

    max_conn: int = controller._config.get_int(SettingKey.MAX_CONCURRENT_CONNECTIONS)
    tracked_socket_count: int = controller._state.get_tracked_live_socket_count()
    if tracked_socket_count >= max_conn and not retunnel_reconnect:
        controller._state.discard_outbound_attempt(onion)
        if origin is ConnectionOrigin.AUTO_RECONNECT:
            controller._state.clear_scheduled_auto_reconnect(onion)
        controller._broadcast(
            MaxConnectionsReachedEvent(
                target=target,
                max_conn=max_conn,
            )
        )
        return

    controller._broadcast(
        ConnectionConnectingEvent(
            alias=alias,
            onion=onion,
            origin=origin,
            actor=controller._get_local_connection_actor(origin),
        )
    )

    handshake_success: bool = False
    last_error: Optional[str] = None
    try:
        max_retries: int = controller._config.get_int(SettingKey.MAX_CONNECT_RETRIES)
        for retry_index in range(max_retries + 1):
            if controller._stop_flag.is_set():
                break
            conn: Optional[socket.socket] = None
            try:
                conn = controller._tm.connect(onion)
                controller._state.bind_outbound_socket(onion, conn)
                conn.settimeout(controller._config.get_float(SettingKey.TOR_TIMEOUT))

                stream = TcpStreamReader(conn)
                challenge_line: Optional[str] = stream.read_line()

                if not challenge_line:
                    raise ConnectionError('Handshake incomplete.')

                challenge: str = HandshakeProtocol.parse_challenge_line(challenge_line)
                signature: Optional[str] = controller._crypto.sign_challenge(challenge)

                if not signature:
                    conn.close()
                    raise ConnectionError('Failed to sign live handshake challenge.')

                conn.sendall(
                    f'{TorCommand.AUTH.value} {controller._tm.onion} {signature}\n'.encode(
                        'utf-8'
                    )
                )

                conn.settimeout(
                    controller._config.get_float(SettingKey.LATE_ACCEPTANCE_TIMEOUT)
                )

                controller._hm.log_event(
                    HistoryEvent.REQUESTED,
                    onion,
                    actor=controller._get_local_history_actor(origin),
                    trigger=origin,
                )
                if controller._receiver:
                    controller._receiver.start_receiving(
                        onion,
                        conn,
                        stream.get_buffer(),
                        awaiting_acceptance=True,
                        connection_origin=origin,
                    )
                handshake_success = True
                conn = None
                return
            except Exception as exc:
                _close_socket(conn)
                if conn is not None:
                    controller._state.clear_bound_outbound_socket(onion, conn)
                last_error = str(exc).strip() or exc.__class__.__name__
                if retry_index < max_retries:
                    controller._broadcast(
                        ConnectionRetryEvent(
                            alias=alias,
                            onion=onion,
                            attempt=retry_index + 1,
                            max_retries=max_retries,
                            origin=origin,
                            actor=ConnectionActor.SYSTEM,
                        )
                    )
                    controller._sleep_connect_retry_backoff()
                else:
                    failure_reason: str = last_error or 'Connection timeout/exhausted'
                    controller._hm.log_event(
                        HistoryEvent.CONNECTION_LOST,
                        onion,
                        actor=HistoryActor.SYSTEM,
                        detail_text=failure_reason,
                        trigger=origin,
                        detail_code=HistoryReasonCode.RETRY_EXHAUSTED,
                    )
                    if controller._state.is_retunneling(onion):
                        if controller._state.is_live_active(onion):
                            controller._broadcast_retunnel_preserved_failure(
                                alias,
                                onion,
                                failure_reason,
                            )
                        else:
                            controller._state.clear_retunnel_flow(onion)
                            controller._broadcast(
                                DisconnectedEvent(
                                    alias=alias,
                                    onion=onion,
                                    actor=ConnectionActor.SYSTEM,
                                    origin=ConnectionOrigin.RETUNNEL,
                                    reason_code=ConnectionReasonCode.RETRY_EXHAUSTED,
                                )
                            )
                            controller._broadcast(
                                create_event(
                                    EventType.RETUNNEL_FAILED,
                                    {
                                        'alias': alias,
                                        'onion': onion,
                                        'error_code': RuntimeErrorCode.RETUNNEL_RECONNECT_FAILED,
                                        'error_detail': failure_reason,
                                    },
                                )
                            )
                    else:
                        if origin is ConnectionOrigin.AUTO_RECONNECT:
                            controller._state.clear_scheduled_auto_reconnect(onion)
                        controller._state.discard_retunnel_reconnect(onion)
                        controller._broadcast(
                            ConnectionFailedEvent(
                                alias=alias,
                                onion=onion,
                                error=failure_reason,
                                origin=origin,
                                actor=ConnectionActor.SYSTEM,
                                reason_code=ConnectionReasonCode.RETRY_EXHAUSTED,
                            )
                        )
    finally:
        if not handshake_success:
            controller._state.discard_outbound_attempt(onion)
