"""
Module orchestrating active connection states initiated by the user.
Manages explicit connect, accept, reject, disconnect operations, the Auto-Reconnect logic, and Retunneling.
"""

import socket
import threading
import time
import secrets
from typing import List, Optional, Callable, Dict, TYPE_CHECKING, Tuple

from metor.core import TorManager
from metor.core.api import (
    ConnectionActor,
    ConnectionOrigin,
    ConnectionReasonCode,
    EventType,
    IpcEvent,
    JsonValue,
    AutoReconnectScheduledEvent,
    ConnectedEvent,
    DisconnectedEvent,
    FallbackSuccessEvent,
    ConnectionConnectingEvent,
    ConnectionAutoAcceptedEvent,
    ConnectionRetryEvent,
    ConnectionFailedEvent,
    ConnectionRejectedEvent,
    ContactRemovedEvent,
    MaxConnectionsReachedEvent,
    PendingConnectionExpiredEvent,
    PeerNotFoundEvent,
    RetunnelInitiatedEvent,
    RetunnelSuccessEvent,
    create_event,
)
from metor.core.daemon.models import TorCommand
from metor.core.daemon.crypto import Crypto
from metor.data import (
    HistoryActor,
    HistoryManager,
    HistoryEvent,
    HistoryReasonCode,
    ContactManager,
    MessageManager,
    MessageDirection,
    MessageType,
    MessageStatus,
    SettingKey,
)
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.network.state import StateTracker
from metor.core.daemon.network.state import PendingConnectionReason
from metor.core.daemon.network.stream import TcpStreamReader
from metor.core.daemon.network.router import MessageRouter

if TYPE_CHECKING:
    from metor.data.profile.config import Config
    from metor.core.daemon.network.receiver import StreamReceiver


class ConnectionController:
    """Orchestrates outbound connections, intentional socket teardowns, auto-reconnects, and retunneling."""

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        crypto: Crypto,
        state: StateTracker,
        router: MessageRouter,
        broadcast_callback: Callable[[IpcEvent], None],
        has_live_consumers_callback: Callable[[], bool],
        stop_flag: threading.Event,
        config: 'Config',
    ) -> None:
        """
        Initializes the ConnectionController.

        Args:
            tm (TorManager): Tor process manager.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Offline messages manager.
            crypto (Crypto): Cryptographic engine.
            state (StateTracker): The thread-safe state container.
            router (MessageRouter): The application-layer message router.
            broadcast_callback (Callable): IPC broadcaster.
            has_live_consumers_callback (Callable[[], bool]): Callback to check whether an interactive live consumer is attached.
            stop_flag (threading.Event): Global daemon termination flag.
            config (Config): The profile configuration instance.

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._crypto: Crypto = crypto
        self._state: StateTracker = state
        self._router: MessageRouter = router
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._has_live_consumers: Callable[[], bool] = has_live_consumers_callback
        self._stop_flag: threading.Event = stop_flag
        self._config: 'Config' = config

        self._receiver: Optional['StreamReceiver'] = None

        self._live_reconnect_queue: List[str] = []
        self._live_reconnect_lock: threading.Lock = threading.Lock()
        threading.Thread(target=self._live_reconnect_worker, daemon=True).start()

    def set_receiver(self, receiver: 'StreamReceiver') -> None:
        """
        Injects the StreamReceiver dependency to avoid circular imports.

        Args:
            receiver (StreamReceiver): The StreamReceiver instance.

        Returns:
            None
        """
        self._receiver = receiver

    def _is_inflight_outbound_socket(self, onion: str, sock: socket.socket) -> bool:
        """
        Checks whether a callback socket belongs to the current outbound attempt.

        Args:
            onion (str): The peer onion identity.
            sock (socket.socket): The callback socket instance.

        Returns:
            bool: True if the socket is the current in-flight outbound attempt.
        """
        return self._state.is_current_outbound_socket(onion, sock)

    def _broadcast_retunnel_failure(
        self, alias: str, onion: str, error: Optional[str] = None
    ) -> None:
        """
        Clears retunnel state and emits the failure lifecycle for one peer.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.

        Returns:
            None
        """
        self._state.clear_retunnel_flow(onion)
        self._broadcast(
            DisconnectedEvent(
                alias=alias,
                onion=onion,
                actor=ConnectionActor.SYSTEM,
                origin=ConnectionOrigin.RETUNNEL,
            )
        )
        params: Dict[str, JsonValue] = {'alias': alias, 'onion': onion}
        if error:
            params['error'] = error
        self._broadcast(create_event(EventType.RETUNNEL_FAILED, params))

    def _discard_outbound_attempt_if_idle(self, onion: str) -> None:
        """
        Clears outbound-attempt state only when no newer connection flow is active.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        if self._state.is_connected_or_pending(onion):
            return
        if self._state.has_outbound_attempt(onion):
            return
        self._state.discard_outbound_attempt(onion)

    def _get_live_reconnect_delay(self) -> float:
        """
        Returns the configured base delay for automatic live reconnect attempts.

        Args:
            None

        Returns:
            float: Delay in seconds, where 0 disables automatic reconnects.
        """
        reconnect_delay_sec: int = self._config.get_int(SettingKey.LIVE_RECONNECT_DELAY)
        return float(max(0, reconnect_delay_sec))

    def _allows_headless_live_backlog(self) -> bool:
        """
        Determines whether unread live backlog may exist without an interactive consumer.

        Args:
            None

        Returns:
            bool: True if headless live backlog is allowed.
        """
        return self._config.get_int(SettingKey.MAX_UNSEEN_LIVE_MSGS) != 0

    def _can_auto_accept_live(self) -> bool:
        """
        Determines whether a live session may be auto-accepted immediately.

        Args:
            None

        Returns:
            bool: True if a live session may become connected immediately.
        """
        return self._has_live_consumers() or self._allows_headless_live_backlog()

    def _mark_live_reconnect_grace(self, onion: str) -> None:
        """
        Marks an incoming reconnect grace window using the profile configuration.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        grace_timeout_sec: int = self._config.get_int(
            SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT
        )
        self._state.mark_live_reconnect_grace(onion, float(grace_timeout_sec))

    @staticmethod
    def _get_local_history_actor(origin: ConnectionOrigin) -> HistoryActor:
        """
        Resolves whether one local flow should be attributed to the user or the daemon.

        Args:
            origin (ConnectionOrigin): The connection lifecycle origin.

        Returns:
            HistoryActor: The normalized local actor classification.
        """
        if origin in {
            ConnectionOrigin.AUTO_RECONNECT,
            ConnectionOrigin.GRACE_RECONNECT,
            ConnectionOrigin.MUTUAL_CONNECT,
            ConnectionOrigin.AUTO_ACCEPT_CONTACT,
        }:
            return HistoryActor.SYSTEM
        return HistoryActor.LOCAL

    @staticmethod
    def _get_local_connection_actor(origin: ConnectionOrigin) -> ConnectionActor:
        """
        Resolves the IPC-facing actor for one locally initiated lifecycle step.

        Args:
            origin (ConnectionOrigin): The connection lifecycle origin.

        Returns:
            ConnectionActor: The normalized IPC actor classification.
        """
        if origin in {
            ConnectionOrigin.AUTO_RECONNECT,
            ConnectionOrigin.GRACE_RECONNECT,
            ConnectionOrigin.MUTUAL_CONNECT,
            ConnectionOrigin.AUTO_ACCEPT_CONTACT,
        }:
            return ConnectionActor.SYSTEM
        return ConnectionActor.LOCAL

    def _sleep_connect_retry_backoff(self) -> None:
        """
        Sleeps between connect retries while remaining responsive to daemon shutdown.

        Args:
            None

        Returns:
            None
        """
        remaining_sec: float = Constants.CONNECT_RETRY_BACKOFF_SEC
        while remaining_sec > 0:
            if self._stop_flag.is_set():
                break

            sleep_sec: float = min(Constants.WORKER_SLEEP_SEC, remaining_sec)
            time.sleep(sleep_sec)
            remaining_sec -= sleep_sec

    def _get_retunnel_reconnect_delay(self) -> float:
        """
        Returns the configured reconnect delay between retunnel teardown and retry.

        Args:
            None

        Returns:
            float: The configured delay in seconds.
        """
        return self._config.get_float(SettingKey.RETUNNEL_RECONNECT_DELAY)

    def _get_retunnel_recovery_retries(self) -> int:
        """
        Returns the configured delayed recovery retry budget for retunnel.

        Args:
            None

        Returns:
            int: The configured retry count.
        """
        return self._config.get_int(SettingKey.RETUNNEL_RECOVERY_RETRIES)

    def _sleep_retunnel_reconnect_delay(self) -> None:
        """
        Waits briefly before reconnecting a live retunnel to let the old session
        teardown propagate to the remote peer.

        Args:
            None

        Returns:
            None
        """
        remaining_sec: float = self._get_retunnel_reconnect_delay()
        while remaining_sec > 0:
            if self._stop_flag.is_set():
                break

            sleep_sec: float = min(Constants.WORKER_SLEEP_SEC, remaining_sec)
            time.sleep(sleep_sec)
            remaining_sec -= sleep_sec

    def _sleep_live_reconnect_delay(self, delay_sec: float) -> None:
        """
        Sleeps before an automatic live reconnect while remaining responsive to shutdown.

        Args:
            delay_sec (float): Total delay in seconds before the reconnect attempt.

        Returns:
            None
        """
        remaining_sec: float = delay_sec
        while remaining_sec > 0:
            if self._stop_flag.is_set():
                break

            sleep_sec: float = min(Constants.WORKER_SLEEP_SEC, remaining_sec)
            time.sleep(sleep_sec)
            remaining_sec -= sleep_sec

    def _retunnel_reconnect_retry_worker(self, onion: str) -> None:
        """
        Waits briefly and retries one retunnel reconnect attempt if the flow is still unresolved.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        try:
            self._sleep_retunnel_reconnect_delay()
            if self._stop_flag.is_set():
                return

            if not self._state.is_retunneling(onion):
                return

            if self._state.is_connected_or_pending(onion):
                return

            self.connect_to(onion, origin=ConnectionOrigin.RETUNNEL)
        finally:
            self._state.finish_retunnel_recovery_retry(onion)

    def _schedule_retunnel_recovery_retry(
        self,
        alias: str,
        onion: str,
        error: str,
    ) -> bool:
        """
        Schedules one bounded delayed retunnel recovery attempt before declaring the flow failed.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            error (str): The failure detail for the eventual fatal failure path.

        Returns:
            bool: True if the flow remains recoverable or one retry was scheduled.
        """
        retry_limit: int = self._get_retunnel_recovery_retries()

        self._state.clear_scheduled_auto_reconnect(onion)
        self._mark_live_reconnect_grace(onion)

        if self._state.has_retunnel_recovery_retry_pending(onion):
            return True

        attempt: Optional[int] = self._state.reserve_retunnel_recovery_retry(
            onion,
            retry_limit,
        )
        if attempt is None:
            self._broadcast_retunnel_failure(alias, onion, error)
            return False

        self._broadcast(
            ConnectionRetryEvent(
                alias=alias,
                onion=onion,
                attempt=attempt,
                max_retries=retry_limit,
                origin=ConnectionOrigin.RETUNNEL,
                actor=ConnectionActor.SYSTEM,
            )
        )
        threading.Thread(
            target=self._retunnel_reconnect_retry_worker,
            args=(onion,),
            daemon=True,
        ).start()
        return True

    def _enqueue_live_reconnect(self, onion: str) -> bool:
        """
        Adds one peer to the reconnect queue once without duplicating queue entries.

        Args:
            onion (str): The target onion identity.

        Returns:
            bool: True if the peer was added to the queue.
        """
        with self._live_reconnect_lock:
            if onion in self._live_reconnect_queue:
                return False
            self._live_reconnect_queue.append(onion)
            return True

    def connect_to(
        self,
        target: str,
        origin: ConnectionOrigin = ConnectionOrigin.MANUAL,
    ) -> None:
        """
        Initiates an outbound Tor connection securely utilizing the explicit Stream Reader.
        Receiver handles the Late Acceptance timeout. Protects against outbound FD/RAM exhaustion.
        Emits live lifecycle events before blocking Tor operations unless the peer is
        currently inside a retunnel flow.

        Args:
            target (str): The alias or onion address to connect to.
            origin (ConnectionOrigin): The machine-readable source of the connection attempt.

        Returns:
            None
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target_for_interaction(
            target
        )
        if not resolved or resolved[1] == self._tm.onion:
            return
        alias, onion = resolved

        if origin is not ConnectionOrigin.AUTO_RECONNECT:
            self._state.clear_scheduled_auto_reconnect(onion)

        if self._state.get_connection(onion):
            return

        implicit_accept: bool = False
        if onion in self._state.get_pending_connections_keys():
            implicit_accept = True
        else:
            self._state.add_outbound_attempt(onion, origin=origin)

        if implicit_accept:
            self._broadcast(
                ConnectionAutoAcceptedEvent(
                    alias=alias,
                    onion=onion,
                    origin=origin,
                    actor=self._get_local_connection_actor(origin),
                )
            )
            self.accept(target, origin=origin)
            return

        max_conn: int = self._config.get_int(SettingKey.MAX_CONCURRENT_CONNECTIONS)
        if len(self._state.get_active_onions()) >= max_conn:
            self._state.discard_outbound_attempt(onion)
            if origin is ConnectionOrigin.AUTO_RECONNECT:
                self._state.clear_scheduled_auto_reconnect(onion)
            self._broadcast(
                MaxConnectionsReachedEvent(
                    target=target,
                    max_conn=max_conn,
                )
            )
            return

        self._broadcast(
            ConnectionConnectingEvent(
                alias=alias,
                onion=onion,
                origin=origin,
                actor=self._get_local_connection_actor(origin),
            )
        )

        handshake_success: bool = False
        last_error: Optional[str] = None
        try:
            max_retries: int = self._config.get_int(SettingKey.MAX_CONNECT_RETRIES)
            for retry_index in range(max_retries + 1):
                if self._stop_flag.is_set():
                    break
                try:
                    conn: socket.socket = self._tm.connect(onion)
                    self._state.bind_outbound_socket(onion, conn)
                    conn.settimeout(self._config.get_float(SettingKey.TOR_TIMEOUT))

                    stream = TcpStreamReader(conn)
                    challenge_line: Optional[str] = stream.read_line()

                    if not challenge_line:
                        raise ConnectionError('Handshake incomplete.')

                    challenge: str = challenge_line.strip().split(' ')[1]
                    signature: Optional[str] = self._crypto.sign_challenge(challenge)

                    if not signature:
                        conn.close()
                        raise ConnectionError(
                            'Failed to sign live handshake challenge.'
                        )

                    conn.sendall(
                        f'{TorCommand.AUTH.value} {self._tm.onion} {signature}\n'.encode(
                            'utf-8'
                        )
                    )

                    conn.settimeout(
                        self._config.get_float(SettingKey.LATE_ACCEPTANCE_TIMEOUT)
                    )

                    self._hm.log_event(
                        HistoryEvent.LIVE_REQUESTED,
                        onion,
                        actor=self._get_local_history_actor(origin),
                        trigger=origin,
                    )
                    if self._receiver:
                        self._receiver.start_receiving(
                            onion,
                            conn,
                            stream.get_buffer(),
                            awaiting_acceptance=True,
                            connection_origin=origin,
                        )
                    handshake_success = True
                    return
                except Exception as exc:
                    last_error = str(exc).strip() or exc.__class__.__name__
                    if retry_index < max_retries:
                        self._broadcast(
                            ConnectionRetryEvent(
                                alias=alias,
                                onion=onion,
                                attempt=retry_index + 1,
                                max_retries=max_retries,
                                origin=origin,
                                actor=ConnectionActor.SYSTEM,
                            )
                        )
                        self._sleep_connect_retry_backoff()
                    else:
                        failure_reason: str = (
                            last_error or 'Connection timeout/exhausted'
                        )
                        self._hm.log_event(
                            HistoryEvent.LIVE_CONNECTION_LOST,
                            onion,
                            actor=HistoryActor.SYSTEM,
                            detail_text=failure_reason,
                            trigger=origin,
                            detail_code=HistoryReasonCode.RETRY_EXHAUSTED,
                        )
                        if self._state.is_retunneling(onion):
                            self._state.clear_retunnel_flow(onion)
                            self._broadcast(
                                DisconnectedEvent(
                                    alias=alias,
                                    onion=onion,
                                    actor=ConnectionActor.SYSTEM,
                                    origin=ConnectionOrigin.RETUNNEL,
                                    reason_code=(ConnectionReasonCode.RETRY_EXHAUSTED),
                                )
                            )
                            self._broadcast(
                                create_event(
                                    EventType.RETUNNEL_FAILED,
                                    {
                                        'alias': alias,
                                        'onion': onion,
                                        'error': failure_reason,
                                    },
                                )
                            )
                        else:
                            if origin is ConnectionOrigin.AUTO_RECONNECT:
                                self._state.clear_scheduled_auto_reconnect(onion)
                            self._state.discard_retunnel_reconnect(onion)
                            self._broadcast(
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
                self._state.discard_outbound_attempt(onion)

    def accept(
        self,
        target: str,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        """
        Approves a pending incoming connection. Safely handles if the socket has
        died in the meantime due to Late Acceptance Timeout.

        Args:
            target (str): The target alias or onion.
            origin (ConnectionOrigin): The machine-readable source of the accepted live flow.

        Returns:
            None
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(target)
        if not resolved:
            self._broadcast(PeerNotFoundEvent(target=target))
            return
        alias, onion = resolved

        conn, initial_buffer, _, pending_origin = self._state.pop_pending_connection(
            onion
        )
        if not conn:
            if self._state.is_retunneling(onion):
                self._hm.log_event(
                    HistoryEvent.LIVE_CONNECTION_LOST,
                    onion,
                    actor=HistoryActor.SYSTEM,
                    trigger=origin,
                    detail_code=HistoryReasonCode.RETUNNEL_PENDING_CONNECTION_MISSING,
                )
                self._broadcast_retunnel_failure(
                    alias,
                    onion,
                    'Retunnel pending connection missing',
                )
                return
            if self._state.consume_recent_pending_expiry(onion):
                self._broadcast(
                    PendingConnectionExpiredEvent(
                        alias=alias,
                        onion=onion,
                        origin=origin,
                        actor=ConnectionActor.SYSTEM,
                        reason_code=(ConnectionReasonCode.PENDING_ACCEPTANCE_EXPIRED),
                    )
                )
                return
            self._broadcast(
                create_event(
                    EventType.NO_PENDING_CONNECTION,
                    {'alias': alias, 'onion': onion},
                )
            )
            return

        try:
            conn.sendall(f'{TorCommand.ACCEPTED.value}\n'.encode('utf-8'))
        except Exception:
            self._hm.log_event(
                HistoryEvent.LIVE_CONNECTION_LOST,
                onion,
                actor=HistoryActor.SYSTEM,
                trigger=origin,
                detail_code=HistoryReasonCode.LATE_ACCEPTANCE_TIMEOUT,
            )
            if self._state.is_retunneling(onion):
                self._broadcast_retunnel_failure(
                    alias,
                    onion,
                    'Late acceptance timeout',
                )
            else:
                self._broadcast(
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
            except Exception:
                pass
            return

        self._state.add_active_connection(onion, conn)
        self._hm.log_event(
            HistoryEvent.LIVE_CONNECTED,
            onion,
            actor=self._get_local_history_actor(origin),
            trigger=origin,
        )
        if self._state.consume_retunnel_reconnect(onion):
            self._hm.log_event(
                HistoryEvent.LIVE_RETUNNEL_SUCCESS,
                onion,
                actor=HistoryActor.SYSTEM,
            )
            self._state.clear_retunnel_flow(onion)
            self._broadcast(RetunnelSuccessEvent(alias=alias, onion=onion))
        else:
            self._broadcast(
                ConnectedEvent(
                    alias=alias,
                    onion=onion,
                    origin=origin,
                    actor=self._get_local_connection_actor(origin),
                )
            )

        if self._receiver:
            self._receiver.start_receiving(
                onion,
                conn,
                initial_buffer,
                connection_origin=origin,
            )

    def reject(
        self,
        target: str,
        initiated_by_self: bool = True,
        socket_to_close: Optional[socket.socket] = None,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        """
        Rejects a connection request and drops the socket using state tracker safeguards.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the rejection.
            socket_to_close (Optional[socket.socket]): Specific duplicate socket to terminate safely.
            origin (ConnectionOrigin): The machine-readable source of the rejected live flow.

        Returns:
            None
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(target)
        if not resolved:
            if initiated_by_self:
                self._broadcast(PeerNotFoundEvent(target=target))
            return
        alias, onion = resolved

        if initiated_by_self:
            self._state.clear_scheduled_auto_reconnect(onion)
            self._state.discard_outbound_attempt(onion)

        inflight_outbound: bool = False

        if socket_to_close and not self._state.is_known_socket(onion, socket_to_close):
            inflight_outbound = self._is_inflight_outbound_socket(
                onion, socket_to_close
            )
            if not inflight_outbound:
                if not initiated_by_self:
                    self._mark_live_reconnect_grace(onion)
                self._discard_outbound_attempt_if_idle(onion)
                try:
                    socket_to_close.close()
                except Exception:
                    pass
                return

        status: HistoryEvent = HistoryEvent.LIVE_REJECTED
        reject_actor: HistoryActor = (
            HistoryActor.LOCAL if initiated_by_self else HistoryActor.REMOTE
        )

        if inflight_outbound:
            self._state.discard_outbound_attempt(onion)
            if socket_to_close:
                try:
                    socket_to_close.close()
                except Exception:
                    pass

            if self._state.is_connected_or_pending(onion):
                return

            self._hm.log_event(
                status,
                onion,
                actor=reject_actor,
                trigger=origin,
                detail_code=HistoryReasonCode.OUTBOUND_ATTEMPT_REJECTED,
            )

            if self._state.is_retunneling(onion):
                self._schedule_retunnel_recovery_retry(
                    alias,
                    onion,
                    'Outbound attempt rejected',
                )
                return

            if origin is ConnectionOrigin.AUTO_RECONNECT:
                self._state.clear_scheduled_auto_reconnect(onion)

            self._broadcast(
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

        conn: Optional[socket.socket] = self._state.pop_any_connection(onion)

        if not conn and not inflight_outbound:
            self._discard_outbound_attempt_if_idle(onion)
            if initiated_by_self:
                self._broadcast(
                    create_event(
                        EventType.NO_CONNECTION_TO_REJECT,
                        {'alias': alias, 'onion': onion},
                    )
                )
            return

        if conn is not None and initiated_by_self:
            try:
                conn.sendall(
                    f'{TorCommand.REJECT.value} {self._tm.onion}\n'.encode('utf-8')
                )
            except Exception:
                pass

        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

        self._hm.log_event(status, onion, actor=reject_actor, trigger=origin)

        if origin is ConnectionOrigin.AUTO_RECONNECT or not initiated_by_self:
            self._state.clear_scheduled_auto_reconnect(onion)

        self._broadcast(
            ConnectionRejectedEvent(
                alias=alias,
                onion=onion,
                origin=origin,
                actor=(
                    ConnectionActor.LOCAL
                    if initiated_by_self
                    else ConnectionActor.REMOTE
                ),
            )
        )

    def disconnect(
        self,
        target: str,
        initiated_by_self: bool = True,
        is_fallback: bool = False,
        socket_to_close: Optional[socket.socket] = None,
        suppress_events: bool = False,
        origin: Optional[ConnectionOrigin] = None,
    ) -> None:
        """
        Terminates a connection safely and processes unacked fallbacks.
        Queues the peer for an auto-reconnect if it was an unexpected failure.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the disconnect.
            is_fallback (bool): Whether this is an unexpected network drop.
            socket_to_close (Optional[socket.socket]): Specific duplicate socket to safely terminate.
            suppress_events (bool): Whether transport lifecycle status events should be suppressed.
            origin (Optional[ConnectionOrigin]): The machine-readable source of the disconnected live flow.

        Returns:
            None
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(target)
        if not resolved:
            if initiated_by_self:
                self._broadcast(PeerNotFoundEvent(target=target))
            return
        alias, onion = resolved

        if initiated_by_self:
            self._state.clear_scheduled_auto_reconnect(onion)
            self._state.discard_outbound_attempt(onion)

        inflight_outbound: bool = False

        if socket_to_close and not self._state.is_known_socket(onion, socket_to_close):
            inflight_outbound = self._is_inflight_outbound_socket(
                onion, socket_to_close
            )
            if not inflight_outbound:
                if not initiated_by_self:
                    self._mark_live_reconnect_grace(onion)
                self._discard_outbound_attempt_if_idle(onion)
                try:
                    socket_to_close.close()
                except Exception:
                    pass
                return

        if inflight_outbound:
            self._state.discard_outbound_attempt(onion)
            if socket_to_close:
                try:
                    socket_to_close.close()
                except Exception:
                    pass

            if self._state.is_connected_or_pending(onion):
                return

            self._hm.log_event(
                HistoryEvent.LIVE_CONNECTION_LOST,
                onion,
                actor=HistoryActor.SYSTEM,
                trigger=origin,
                detail_code=(
                    HistoryReasonCode.OUTBOUND_ATTEMPT_CLOSED_BEFORE_ACCEPTANCE
                ),
            )
            if self._state.is_retunneling(onion):
                self._schedule_retunnel_recovery_retry(
                    alias,
                    onion,
                    'Outbound attempt closed before acceptance',
                )
            else:
                if origin is ConnectionOrigin.AUTO_RECONNECT:
                    self._state.clear_scheduled_auto_reconnect(onion)
                self._broadcast(
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

        conn: Optional[socket.socket] = self._state.pop_any_connection(onion)
        unacked: Dict[str, Tuple[str, str]] = {}

        if self._config.get_bool(SettingKey.FALLBACK_TO_DROP):
            unacked = self._state.pop_unacked_messages(onion)

        if not conn and not unacked and not inflight_outbound:
            if not initiated_by_self:
                self._mark_live_reconnect_grace(onion)
            self._discard_outbound_attempt_if_idle(onion)
            if initiated_by_self and not suppress_events:
                self._broadcast(
                    create_event(
                        EventType.NO_CONNECTION_TO_DISCONNECT,
                        {'alias': alias, 'onion': onion},
                    )
                )
            return

        if unacked:
            for msg_id, pending_msg in unacked.items():
                content, timestamp = pending_msg
                self._mm.queue_message(
                    contact_onion=onion,
                    direction=MessageDirection.OUT,
                    msg_type=MessageType.DROP_TEXT,
                    payload=content,
                    status=MessageStatus.PENDING,
                    msg_id=msg_id,
                    timestamp=timestamp,
                )
                self._hm.log_event(
                    HistoryEvent.DROP_QUEUED,
                    onion,
                    actor=HistoryActor.SYSTEM,
                    detail_text='Unacked msgs converted to drop',
                )
            if not suppress_events:
                self._broadcast(
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
                        f'{TorCommand.DISCONNECT.value} {self._tm.onion}\n'.encode(
                            'utf-8'
                        )
                    )
                    time.sleep(Constants.TCP_CLOSE_LINGER_SEC)
                    conn.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
            try:
                conn.close()
            except Exception:
                pass

        if is_fallback:
            status = HistoryEvent.LIVE_CONNECTION_LOST
            disconnect_actor: HistoryActor = HistoryActor.SYSTEM
        else:
            status = HistoryEvent.LIVE_DISCONNECTED
            disconnect_actor = (
                HistoryActor.LOCAL if initiated_by_self else HistoryActor.REMOTE
            )
        self._hm.log_event(
            status,
            onion,
            actor=disconnect_actor,
            trigger=origin,
        )

        if not suppress_events:
            self._broadcast(
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
            self._mark_live_reconnect_grace(onion)

        deleted_peers: List[Tuple[str, str]] = self._cm.cleanup_orphans(
            self._state.get_active_onions()
        )
        for removed_alias, removed_onion in deleted_peers:
            self._broadcast(
                ContactRemovedEvent(alias=removed_alias, onion=removed_onion)
            )

        if is_fallback and self._get_live_reconnect_delay() > 0:
            self._state.mark_scheduled_auto_reconnect(onion)
            was_scheduled: bool = self._enqueue_live_reconnect(onion)
            if was_scheduled:
                self._hm.log_event(
                    HistoryEvent.LIVE_AUTO_RECONNECT_SCHEDULED,
                    onion,
                    actor=HistoryActor.SYSTEM,
                    trigger=ConnectionOrigin.AUTO_RECONNECT,
                )
                self._broadcast(
                    AutoReconnectScheduledEvent(
                        alias=alias,
                        onion=onion,
                        origin=ConnectionOrigin.AUTO_RECONNECT,
                        actor=ConnectionActor.SYSTEM,
                    )
                )

    def on_live_consumer_available(self) -> None:
        """
        Re-evaluates internally deferred inbound live sockets when a consumer appears.

        Args:
            None

        Returns:
            None
        """
        for onion in self._state.get_pending_connections_with_reason(
            PendingConnectionReason.CONSUMER_ABSENT
        ):
            alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)
            if not alias:
                continue

            auto_accept_origin: ConnectionOrigin = (
                self._state.get_pending_connection_origin(onion)
                or ConnectionOrigin.INCOMING
            )

            self._broadcast(
                ConnectionAutoAcceptedEvent(
                    alias=alias,
                    onion=onion,
                    origin=auto_accept_origin,
                    actor=ConnectionActor.SYSTEM,
                )
            )
            self.accept(onion, origin=auto_accept_origin)

    def _live_reconnect_worker(self) -> None:
        """
        Background thread handling failure-only reconnect attempts with randomized backoff.
        Enforces Thread-Safety by catching unexpected states to prevent silent worker crashes.

        Args:
            None

        Returns:
            None
        """
        while not self._stop_flag.is_set():
            time.sleep(Constants.WORKER_SLEEP_SLOW_SEC)
            try:
                onion: Optional[str] = None

                with self._live_reconnect_lock:
                    if self._live_reconnect_queue:
                        onion = self._live_reconnect_queue.pop(0)

                if onion:
                    if not self._state.has_scheduled_auto_reconnect(onion):
                        continue

                    if self._state.get_connection(onion):
                        self._state.clear_scheduled_auto_reconnect(onion)
                        continue

                    pending_reason: Optional[PendingConnectionReason] = (
                        self._state.get_pending_connection_reason(onion)
                    )

                    if pending_reason is PendingConnectionReason.CONSUMER_ABSENT:
                        self._enqueue_live_reconnect(onion)
                        continue

                    if pending_reason is PendingConnectionReason.USER_ACCEPT:
                        self._state.clear_scheduled_auto_reconnect(onion)
                        continue

                    reconnect_delay_sec: float = self._get_live_reconnect_delay()
                    if reconnect_delay_sec <= 0:
                        self._state.clear_scheduled_auto_reconnect(onion)
                        continue

                    if not self._can_auto_accept_live():
                        self._enqueue_live_reconnect(onion)
                        continue

                    backoff: float = reconnect_delay_sec + (
                        secrets.randbelow(Constants.LIVE_RECONNECT_JITTER_MAX_MS)
                        / Constants.LIVE_RECONNECT_JITTER_DIVISOR
                    )

                    self._sleep_live_reconnect_delay(backoff)
                    if not self._state.has_scheduled_auto_reconnect(onion):
                        continue

                    if self._state.get_connection(onion):
                        self._state.clear_scheduled_auto_reconnect(onion)
                        continue

                    pending_reason = self._state.get_pending_connection_reason(onion)
                    if pending_reason is PendingConnectionReason.CONSUMER_ABSENT:
                        self._enqueue_live_reconnect(onion)
                        continue

                    if pending_reason is PendingConnectionReason.USER_ACCEPT:
                        self._state.clear_scheduled_auto_reconnect(onion)
                        continue

                    if (
                        not self._state.is_connected_or_pending(onion)
                        and not self._stop_flag.is_set()
                    ):
                        self.connect_to(
                            onion,
                            origin=ConnectionOrigin.AUTO_RECONNECT,
                        )
            except Exception:
                pass

    def disconnect_all(self) -> None:
        """
        Forcefully disconnects all active and pending peers safely upon daemon shutdown.

        Args:
            None

        Returns:
            None
        """
        for onion in self._state.get_active_onions():
            self.disconnect(onion, initiated_by_self=True)

    def retunnel(self, target: str) -> None:
        """
        Forces a Tor circuit rotation and reconnects to the target.

        Args:
            target (str): The target alias or onion address.

        Returns:
            None
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(target)
        if not resolved:
            self._broadcast(PeerNotFoundEvent(target=target))
            return
        alias, onion = resolved

        if not self._state.is_connected_or_pending(onion):
            self._broadcast(
                create_event(
                    EventType.RETUNNEL_FAILED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'error': 'No active connection to retunnel',
                    },
                )
            )
            return

        self._broadcast(RetunnelInitiatedEvent(alias=alias, onion=onion))
        self._hm.log_event(
            HistoryEvent.LIVE_RETUNNEL_INITIATED,
            onion,
            actor=HistoryActor.LOCAL,
        )

        success, event_type, params = self._tm.rotate_circuits()
        if not success:
            params['alias'] = alias
            params['onion'] = onion
            self._broadcast(
                create_event(event_type or EventType.RETUNNEL_FAILED, params)
            )
            return

        self._state.mark_retunnel_started(onion)
        self.disconnect(
            onion,
            initiated_by_self=True,
            suppress_events=True,
            origin=ConnectionOrigin.RETUNNEL,
        )
        self._mark_live_reconnect_grace(onion)
        self._sleep_retunnel_reconnect_delay()

        self._state.mark_retunnel_reconnect(onion)
        self.connect_to(onion, origin=ConnectionOrigin.RETUNNEL)
