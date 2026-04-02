"""
Module wrapping the server socket binding and authentication validation.
Routes inbound connections to the application drops or the live connection state pool.
Enforces Max Concurrent Connection Limits to mitigate RAM/FD Exhaustion attacks.
"""

import select
import socket
import threading
import secrets
import time
from typing import Optional, Callable, List, TYPE_CHECKING

from metor.core import TorManager
from metor.core.api import (
    EventType,
    IpcEvent,
    ConnectedEvent,
    DisconnectedEvent,
    IncomingConnectionEvent,
    RetunnelSuccessEvent,
    TiebreakerRejectedEvent,
    MaxConnectionsReachedEvent,
    create_event,
)
from metor.core.daemon.models import TorCommand
from metor.core.daemon.crypto import Crypto
from metor.data import (
    HistoryManager,
    HistoryEvent,
    ContactManager,
    SettingKey,
)
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.network.state import PendingConnectionReason, StateTracker
from metor.core.daemon.network.stream import TcpStreamReader
from metor.core.daemon.network.handshake import HandshakeProtocol
from metor.core.daemon.network.router import MessageRouter

if TYPE_CHECKING:
    from metor.core.daemon.network.receiver import StreamReceiver
    from metor.data.profile.config import Config


class InboundListener:
    """Manages the passive Tor listener socket and initial peer handshakes."""

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        crypto: Crypto,
        state: StateTracker,
        router: MessageRouter,
        receiver: 'StreamReceiver',
        broadcast_callback: Callable[[IpcEvent], None],
        has_live_consumers_callback: Callable[[], bool],
        stop_flag: threading.Event,
        config: 'Config',
    ) -> None:
        """
        Initializes the InboundListener.

        Args:
            tm (TorManager): Tor process manager.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            crypto (Crypto): Cryptographic engine.
            state (StateTracker): The thread-safe state container.
            router (MessageRouter): The application-layer message router.
            receiver (StreamReceiver): The stream receiver to instantiate upon acceptance.
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
        self._crypto: Crypto = crypto
        self._state: StateTracker = state
        self._router: MessageRouter = router
        self._receiver: 'StreamReceiver' = receiver
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._has_live_consumers: Callable[[], bool] = has_live_consumers_callback
        self._stop_flag: threading.Event = stop_flag
        self._config: 'Config' = config

    def _allows_headless_live_backlog(self) -> bool:
        """
        Determines whether inbound live may be auto-accepted without an interactive consumer.

        Args:
            None

        Returns:
            bool: True if headless live backlog is allowed.
        """
        return self._config.get_int(SettingKey.MAX_UNSEEN_LIVE_MSGS) != 0

    def start_listener(self) -> None:
        """
        Starts the local Tor listener in a background thread.

        Args:
            None

        Returns:
            None
        """
        threading.Thread(target=self._listener_target, daemon=True).start()

    def _listener_target(self) -> None:
        """
        Background loop accepting raw incoming Tor sockets.
        Enforces maximum connection limits to prevent DoS.

        Args:
            None

        Returns:
            None
        """
        listener: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind((Constants.LOCALHOST, self._tm.incoming_port or 0))
        listener.listen(Constants.SERVER_BACKLOG)

        while not self._stop_flag.is_set():
            try:
                listener.settimeout(Constants.THREAD_POLL_TIMEOUT)
                conn, _ = listener.accept()

                max_conn: int = self._config.get_int(
                    SettingKey.MAX_CONCURRENT_CONNECTIONS
                )
                active_count: int = len(self._state.get_active_onions())
                unauth_count: int = self._state.get_unauthenticated_count()

                if active_count + unauth_count >= max_conn:
                    self._hm.log_event(
                        HistoryEvent.LIVE_REJECTED_MAX_CONNECTIONS,
                        None,
                        'Listener drop',
                    )
                    self._broadcast(
                        MaxConnectionsReachedEvent(
                            target='Unknown (Listener)', max_conn=max_conn
                        )
                    )
                    try:
                        conn.close()
                    except Exception:
                        pass
                    continue

                self._state.add_unauthenticated_connection(conn)
                threading.Thread(
                    target=self._handle_incoming, args=(conn,), daemon=True
                ).start()
            except MemoryError as e:
                self._hm.log_event(HistoryEvent.LIVE_STREAM_CORRUPTED, None, str(e))
            except Exception:
                continue

    def _handle_incoming(self, conn: socket.socket) -> None:
        """
        Authenticates inbound requests using the constrained stream reader.

        Args:
            conn (socket.socket): The incoming socket connection.

        Returns:
            None
        """
        auth_successful: bool = False
        onion: Optional[str] = None
        is_async: bool = False
        stream: Optional[TcpStreamReader] = None

        try:
            tor_timeout: float = self._config.get_float(SettingKey.TOR_TIMEOUT)
            conn.settimeout(tor_timeout)
            challenge: str = secrets.token_hex(32)
            conn.sendall(f'{TorCommand.CHALLENGE.value} {challenge}\n'.encode('utf-8'))

            stream = TcpStreamReader(conn)
            line: Optional[str] = stream.read_line()

            if line and line.startswith(f'{TorCommand.AUTH.value} '):
                parts: List[str] = line.split(' ')
                if len(parts) >= 3 and self._crypto.verify_signature(
                    parts[1], challenge, parts[2]
                ):
                    onion = parts[1]
                    auth_successful = True
                    if len(parts) >= 4 and parts[3] == 'ASYNC':
                        is_async = True
        except MemoryError as e:
            self._hm.log_event(HistoryEvent.LIVE_STREAM_CORRUPTED, onion, str(e))
        except Exception:
            pass
        finally:
            self._state.remove_unauthenticated_connection(conn)

        if not auth_successful or not onion or not stream:
            try:
                conn.close()
            except Exception:
                pass
            return

        if is_async:
            self._router.process_async_drop(conn, stream, onion)
            return

        self._handle_live_incoming(conn, stream, onion)

    def _watch_pending_connection(
        self, onion: str, alias: str, conn: socket.socket
    ) -> None:
        """
        Expires a pending inbound live socket once the remote side disappears or the
        late-acceptance window elapses.

        Args:
            onion (str): The peer onion identity.
            alias (str): The strict alias for UI feedback.
            conn (socket.socket): The pending socket to supervise.

        Returns:
            None
        """
        deadline: float = time.time() + self._config.get_float(
            SettingKey.LATE_ACCEPTANCE_TIMEOUT
        )

        while not self._stop_flag.is_set():
            if not self._state.is_pending_socket(onion, conn):
                return

            remaining_sec: float = deadline - time.time()
            if remaining_sec <= 0:
                break

            wait_sec: float = min(Constants.THREAD_POLL_TIMEOUT, remaining_sec)
            try:
                readable, _, exceptional = select.select([conn], [], [conn], wait_sec)
            except Exception:
                break

            if not self._state.is_pending_socket(onion, conn):
                return

            if exceptional:
                break

            if not readable:
                continue

            try:
                peek: bytes = conn.recv(1, socket.MSG_PEEK)
            except (BlockingIOError, InterruptedError):
                continue
            except Exception:
                break

            if peek == b'' or peek:
                break

        if not self._state.remove_pending_connection_if_socket(onion, conn):
            return

        self._hm.log_event(
            HistoryEvent.LIVE_CONNECTION_LOST,
            onion,
            'Pending acceptance expired',
        )

        try:
            conn.close()
        except Exception:
            pass

        if self._state.is_retunneling(onion):
            self._state.clear_retunnel_flow(onion)
            self._broadcast(DisconnectedEvent(alias=alias, onion=onion))
            self._broadcast(
                create_event(
                    EventType.RETUNNEL_FAILED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'error': 'Pending acceptance expired',
                    },
                )
            )

    def _handle_live_incoming(
        self, conn: socket.socket, stream: TcpStreamReader, onion: str
    ) -> None:
        """
        Evaluates tie-breakers and manages interactive live connections.

        Args:
            conn (socket.socket): The active socket connection.
            stream (TcpStreamReader): The constrained byte stream.
            onion (str): The peer's onion identity.

        Returns:
            None
        """
        alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)
        if not alias:
            conn.close()
            return

        is_outbound_attempt: bool = self._state.has_outbound_attempt(onion)
        should_reject, is_mutual_winner = HandshakeProtocol.evaluate_tie_breaker(
            self._tm.onion, onion, is_outbound_attempt
        )

        grace_reconnect: bool = self._state.has_live_reconnect_grace(onion)

        if self._state.is_connected_or_pending(onion) and not grace_reconnect:
            should_reject = True

        if should_reject:
            try:
                conn.sendall(
                    f'{TorCommand.REJECT.value} {self._tm.onion}\n'.encode('utf-8')
                )
            except Exception:
                pass
            conn.close()

            self._hm.log_event(
                HistoryEvent.TIEBREAKER_REJECTED,
                onion,
                'Mutual connection collision resolved',
            )
            self._broadcast(TiebreakerRejectedEvent(alias=alias, onion=onion))
            return

        should_auto_accept_now: bool = (
            grace_reconnect
            or is_mutual_winner
            or (
                (alias in self._cm.get_all_contacts())
                and self._config.get_bool(SettingKey.AUTO_ACCEPT_CONTACTS)
            )
        )

        accepted_now: bool = False
        pending_reason: PendingConnectionReason = PendingConnectionReason.USER_ACCEPT
        if should_auto_accept_now and (
            self._has_live_consumers() or self._allows_headless_live_backlog()
        ):
            if grace_reconnect:
                self._state.consume_live_reconnect_grace(onion)
            self._state.add_active_connection(onion, conn)
            accepted_now = True
        else:
            try:
                conn.sendall(f'{TorCommand.PENDING.value}\n'.encode('utf-8'))
            except Exception:
                pass
            if should_auto_accept_now:
                pending_reason = PendingConnectionReason.CONSUMER_ABSENT
            self._state.add_pending_connection(
                onion,
                conn,
                stream.get_buffer(),
                reason=pending_reason,
            )
            threading.Thread(
                target=self._watch_pending_connection,
                args=(onion, alias, conn),
                daemon=True,
            ).start()

        if accepted_now:
            try:
                conn.sendall(f'{TorCommand.ACCEPTED.value}\n'.encode('utf-8'))
            except Exception:
                pass

            self._hm.log_event(HistoryEvent.LIVE_CONNECTED, onion)
            if self._state.consume_retunnel_reconnect(onion):
                self._hm.log_event(HistoryEvent.LIVE_RETUNNEL_SUCCESS, onion)
                self._state.clear_retunnel_flow(onion)
                self._broadcast(RetunnelSuccessEvent(alias=alias, onion=onion))
            else:
                self._broadcast(ConnectedEvent(alias=alias, onion=onion))

            if self._receiver:
                self._receiver.start_receiving(onion, conn, stream.get_buffer())
        else:
            self._hm.log_event(HistoryEvent.LIVE_REQUESTED_BY_REMOTE, onion)
            if pending_reason is PendingConnectionReason.USER_ACCEPT:
                self._broadcast(IncomingConnectionEvent(alias=alias, onion=onion))
