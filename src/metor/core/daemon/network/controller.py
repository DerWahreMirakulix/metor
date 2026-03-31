"""
Module orchestrating active connection states initiated by the user.
Manages explicit connect, accept, reject, disconnect operations, the Auto-Reconnect logic, and Retunneling.
"""

import socket
import threading
import time
import secrets
from typing import List, Optional, Callable, Dict, TYPE_CHECKING

from metor.core import TorManager
from metor.core.api import (
    IpcEvent,
    NetworkCode,
    ConnectedEvent,
    DisconnectedEvent,
    FallbackSuccessEvent,
    ConnectionPendingEvent,
    ConnectionAutoAcceptedEvent,
    ConnectionRetryEvent,
    ConnectionFailedEvent,
    ConnectionRejectedEvent,
    ContactRemovedEvent,
    ActionErrorEvent,
    MaxConnectionsReachedEvent,
    PeerNotFoundEvent,
    RetunnelInitiatedEvent,
    RetunnelSuccessEvent,
    AutoReconnectAttemptEvent,
)
from metor.core.daemon.models import TorCommand
from metor.core.daemon.crypto import Crypto
from metor.data import (
    HistoryManager,
    HistoryEvent,
    ContactManager,
    MessageManager,
    MessageDirection,
    MessageType,
    MessageStatus,
    Settings,
    SettingKey,
)

# Local Package Imports
from metor.core.daemon.network.state import StateTracker
from metor.core.daemon.network.stream import TcpStreamReader
from metor.core.daemon.network.router import MessageRouter

if TYPE_CHECKING:
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
        stop_flag: threading.Event,
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
            stop_flag (threading.Event): Global daemon termination flag.

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
        self._stop_flag: threading.Event = stop_flag

        self._receiver: Optional['StreamReceiver'] = None

        # Reconnect Queue Management
        self._reconnect_queue: List[str] = []
        self._reconnect_lock: threading.Lock = threading.Lock()
        threading.Thread(target=self._reconnect_worker, daemon=True).start()

    def set_receiver(self, receiver: 'StreamReceiver') -> None:
        """
        Injects the StreamReceiver dependency to avoid circular imports.

        Args:
            receiver (StreamReceiver): The StreamReceiver instance.

        Returns:
            None
        """
        self._receiver = receiver

    def connect_to(self, target: str) -> None:
        """
        Initiates an outbound Tor connection securely utilizing the explicit Stream Reader.
        Receiver handles the Late Acceptance timeout. Protects against outbound FD/RAM exhaustion.

        Args:
            target (str): The alias or onion address to connect to.

        Returns:
            None
        """
        alias, onion, exists = self._cm.resolve_target(target)
        if not exists or not onion or onion == self._tm.onion:
            return

        if self._state.get_connection(onion):
            return

        # OPSEC: Guard against outbound RAM/FD resource exhaustion attacks
        max_conn: int = Settings.get(SettingKey.MAX_CONCURRENT_CONNECTIONS)
        if len(self._state.get_active_onions()) >= max_conn:
            self._broadcast(
                MaxConnectionsReachedEvent(
                    target=str(alias or onion),
                    max_conn=max_conn,
                )
            )
            return

        implicit_accept: bool = False
        if onion in self._state.get_pending_connections_keys():
            implicit_accept = True
        else:
            self._state.add_outbound_attempt(onion)

        if implicit_accept:
            self._broadcast(ConnectionAutoAcceptedEvent(alias=alias))
            self.accept(target)
            return

        handshake_success: bool = False
        try:
            max_retries: int = Settings.get(SettingKey.MAX_CONNECT_RETRIES)
            for attempt in range(1, max_retries + 1):
                if self._stop_flag.is_set():
                    break
                try:
                    conn: socket.socket = self._tm.connect(onion)
                    conn.settimeout(15.0)

                    stream = TcpStreamReader(conn)
                    challenge_line: Optional[str] = stream.read_line()

                    if not challenge_line:
                        raise ConnectionError('Handshake incomplete.')

                    challenge: str = challenge_line.strip().split(' ')[1]
                    signature: Optional[str] = self._crypto.sign_challenge(challenge)

                    conn.sendall(
                        f'{TorCommand.AUTH.value} {self._tm.onion} {signature}\n'.encode(
                            'utf-8'
                        )
                    )

                    # Do not set blocking to None yet. The receiver will enforce the Late Acceptance
                    # Timeout natively via its read operations on the Pending socket.
                    conn.settimeout(60.0)

                    self._hm.log_event(HistoryEvent.LIVE_REQUESTED, onion)
                    self._broadcast(ConnectionPendingEvent(alias=alias))
                    if self._receiver:
                        self._receiver.start_receiving(onion, conn, stream.get_buffer())
                    handshake_success = True
                    return
                except Exception:
                    if attempt < max_retries:
                        self._broadcast(
                            ConnectionRetryEvent(
                                alias=alias, attempt=attempt, max_retries=max_retries
                            )
                        )
                        for _ in range(3):
                            if self._stop_flag.is_set():
                                break
                            time.sleep(1.0)
                    else:
                        self._hm.log_event(
                            HistoryEvent.DROP_FAILED,
                            onion,
                            'Connection timeout/exhausted',
                        )
                        self._broadcast(
                            ConnectionFailedEvent(alias=alias, reason='timeout')
                        )
        finally:
            if not handshake_success:
                self._state.discard_outbound_attempt(onion)

    def accept(self, target: str) -> None:
        """
        Approves a pending incoming connection. Safely handles if the socket has
        died in the meantime due to Late Acceptance Timeout.

        Args:
            target (str): The target alias or onion.

        Returns:
            None
        """
        alias, onion, exists = self._cm.resolve_target(target)
        if not exists or not onion:
            self._broadcast(PeerNotFoundEvent(target=target))
            return

        conn, initial_buffer = self._state.pop_pending_connection(onion)
        if not conn:
            self._broadcast(
                ActionErrorEvent(
                    code=NetworkCode.NO_PENDING_CONNECTION,
                    alias=str(alias or onion),
                )
            )
            return

        try:
            conn.sendall(f'{TorCommand.ACCEPTED.value}\n'.encode('utf-8'))
        except Exception:
            # Late Acceptance failure: Remote dropped before we accepted.
            self._hm.log_event(
                HistoryEvent.LIVE_CONNECTION_LOST, onion, 'Late acceptance timeout'
            )
            self._broadcast(DisconnectedEvent(alias=str(alias or onion)))
            try:
                conn.close()
            except Exception:
                pass
            return

        self._state.add_active_connection(onion, conn)
        self._hm.log_event(HistoryEvent.LIVE_CONNECTED, onion)
        self._broadcast(ConnectedEvent(alias=str(alias or onion), onion=onion))

        if self._receiver:
            self._receiver.start_receiving(onion, conn, initial_buffer)

    def reject(
        self,
        target: str,
        initiated_by_self: bool = True,
        socket_to_close: Optional[socket.socket] = None,
    ) -> None:
        """
        Rejects a connection request and drops the socket using state tracker safeguards.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the rejection.
            socket_to_close (Optional[socket.socket]): Specific duplicate socket to terminate safely.

        Returns:
            None
        """
        alias, onion, exists = self._cm.resolve_target(target)
        if not exists or not onion:
            if initiated_by_self:
                self._broadcast(PeerNotFoundEvent(target=target))
            return

        if initiated_by_self:
            self._state.discard_outbound_attempt(onion)

        if socket_to_close and not self._state.is_known_socket(onion, socket_to_close):
            try:
                socket_to_close.close()
            except Exception:
                pass
            return

        conn: Optional[socket.socket] = self._state.pop_any_connection(onion)

        if not conn:
            if initiated_by_self:
                self._broadcast(
                    ActionErrorEvent(
                        code=NetworkCode.NO_CONNECTION_TO_REJECT,
                        alias=str(alias or onion),
                    )
                )
            return

        if initiated_by_self:
            try:
                conn.sendall(
                    f'{TorCommand.REJECT.value} {self._tm.onion}\n'.encode('utf-8')
                )
            except Exception:
                pass

        try:
            conn.close()
        except Exception:
            pass

        status: HistoryEvent = (
            HistoryEvent.LIVE_REJECTED
            if initiated_by_self
            else HistoryEvent.LIVE_REJECTED_BY_REMOTE
        )
        self._hm.log_event(status, onion)

        self._broadcast(
            ConnectionRejectedEvent(
                alias=str(alias or onion), by_remote=not initiated_by_self
            )
        )

    def disconnect(
        self,
        target: str,
        initiated_by_self: bool = True,
        is_fallback: bool = False,
        socket_to_close: Optional[socket.socket] = None,
    ) -> None:
        """
        Terminates a connection safely and processes unacked fallbacks.
        Queues the peer for an auto-reconnect if it was an unexpected failure.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the disconnect.
            is_fallback (bool): Whether this is an unexpected network drop.
            socket_to_close (Optional[socket.socket]): Specific duplicate socket to safely terminate.

        Returns:
            None
        """
        alias, onion, exists = self._cm.resolve_target(target)
        if not exists or not onion:
            if initiated_by_self:
                self._broadcast(PeerNotFoundEvent(target=target))
            return

        if initiated_by_self:
            self._state.discard_outbound_attempt(onion)

        if socket_to_close and not self._state.is_known_socket(onion, socket_to_close):
            try:
                socket_to_close.close()
            except Exception:
                pass
            return

        conn: Optional[socket.socket] = self._state.pop_any_connection(onion)
        unacked: Dict[str, str] = {}

        if Settings.get(SettingKey.FALLBACK_TO_DROP):
            unacked = self._state.pop_unacked_messages(onion)

        if not conn and not unacked:
            if initiated_by_self:
                self._broadcast(
                    ActionErrorEvent(
                        code=NetworkCode.NO_CONNECTION_TO_DISCONNECT,
                        alias=str(alias or onion),
                    )
                )
            return

        if unacked:
            for content in unacked.values():
                self._mm.queue_message(
                    contact_onion=onion,
                    direction=MessageDirection.OUT,
                    msg_type=MessageType.TEXT,
                    payload=content,
                    status=MessageStatus.PENDING,
                )
                self._hm.log_event(
                    HistoryEvent.DROP_QUEUED, onion, 'Unacked msgs converted to drop'
                )
            self._broadcast(
                FallbackSuccessEvent(
                    code=NetworkCode.FALLBACK_SUCCESS,
                    alias=str(alias or onion),
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
                    time.sleep(0.2)
                    conn.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
            try:
                conn.close()
            except Exception:
                pass

        status: HistoryEvent = (
            HistoryEvent.LIVE_CONNECTION_LOST
            if is_fallback
            else (
                HistoryEvent.LIVE_DISCONNECTED
                if initiated_by_self
                else HistoryEvent.LIVE_DISCONNECTED_BY_REMOTE
            )
        )
        self._hm.log_event(status, onion)

        self._broadcast(DisconnectedEvent(alias=str(alias or onion)))

        deleted_aliases: List[str] = self._cm.cleanup_orphans(
            self._state.get_active_onions()
        )
        for a in deleted_aliases:
            self._broadcast(ContactRemovedEvent(alias=a))

        # Enqueue for Auto-Reconnect if unexpected failure
        if is_fallback and Settings.get(SettingKey.AUTO_RECONNECT_LIVE):
            with self._reconnect_lock:
                if onion not in self._reconnect_queue:
                    self._reconnect_queue.append(onion)

    def _reconnect_worker(self) -> None:
        """
        Background thread handling failure-only reconnect attempts with randomized backoff.

        Args:
            None

        Returns:
            None
        """
        while not self._stop_flag.is_set():
            time.sleep(2.0)
            onion: Optional[str] = None

            with self._reconnect_lock:
                if self._reconnect_queue:
                    onion = self._reconnect_queue.pop(0)

            if onion:
                # OPSEC: Randomized backoff using cryptographically secure PRNG to prevent fingerprinting
                backoff: float = 10.0 + (
                    secrets.randbelow(2001) / 100.0
                )  # Generates 10.00 to 30.00
                alias: Optional[str] = self._cm.get_alias_by_onion(onion)

                self._hm.log_event(HistoryEvent.LIVE_AUTO_RECONNECT_ATTEMPT, onion)
                self._broadcast(AutoReconnectAttemptEvent(alias=str(alias or onion)))

                # Check if UI/Daemon has naturally reconnected in the meantime
                time.sleep(backoff)
                if (
                    not self._state.is_connected_or_pending(onion)
                    and not self._stop_flag.is_set()
                ):
                    self.connect_to(onion)

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
        alias, onion, exists = self._cm.resolve_target(target)
        if not exists or not onion:
            self._broadcast(PeerNotFoundEvent(target=target))
            return

        self._broadcast(RetunnelInitiatedEvent(alias=str(alias or onion)))
        self._hm.log_event(HistoryEvent.LIVE_RETUNNEL_INITIATED, onion)

        # Disconnect existing connection forcefully
        self.disconnect(onion, initiated_by_self=True)

        # Rotate circuits
        success, code, params = self._tm.rotate_circuits()
        if not success:
            self._broadcast(ActionErrorEvent(code=code))
            return

        self._hm.log_event(HistoryEvent.LIVE_RETUNNEL_SUCCESS, onion)
        self._broadcast(RetunnelSuccessEvent(alias=str(alias or onion)))

        # Initiate fresh connection
        self.connect_to(onion)
