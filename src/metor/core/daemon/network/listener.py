"""
Module wrapping the server socket binding and authentication validation.
Routes inbound connections to the application drops or the live connection state pool.
Enforces Max Concurrent Connection Limits to mitigate RAM/FD Exhaustion attacks.
"""

import socket
import threading
import secrets
from typing import Optional, Callable, List, TYPE_CHECKING

from metor.core import TorManager
from metor.core.api import (
    IpcEvent,
    ConnectedEvent,
    IncomingConnectionEvent,
    TiebreakerRejectedEvent,
    MaxConnectionsReachedEvent,
)
from metor.core.daemon.models import TorCommand
from metor.core.daemon.crypto import Crypto
from metor.data import (
    HistoryManager,
    HistoryEvent,
    ContactManager,
    Settings,
    SettingKey,
)
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.network.state import StateTracker
from metor.core.daemon.network.stream import TcpStreamReader
from metor.core.daemon.network.handshake import HandshakeProtocol
from metor.core.daemon.network.router import MessageRouter

if TYPE_CHECKING:
    from metor.core.daemon.network.receiver import StreamReceiver


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
        stop_flag: threading.Event,
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
            stop_flag (threading.Event): Global daemon termination flag.

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
        self._stop_flag: threading.Event = stop_flag

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
        listener.listen(5)

        while not self._stop_flag.is_set():
            try:
                listener.settimeout(1.0)
                conn, _ = listener.accept()

                # OPSEC: Guard against RAM/FD resource exhaustion attacks
                max_conn: int = Settings.get(SettingKey.MAX_CONCURRENT_CONNECTIONS)
                if len(self._state.get_active_onions()) >= max_conn:
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
            conn.settimeout(10.0)
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
        conn.settimeout(None)
        alias: Optional[str] = self._cm.get_alias_by_onion(onion)
        if not alias:
            conn.close()
            return

        is_outbound_attempt: bool = self._state.has_outbound_attempt(onion)
        should_reject, is_mutual_winner = HandshakeProtocol.evaluate_tie_breaker(
            self._tm.onion, onion, is_outbound_attempt
        )

        if self._state.is_connected_or_pending(onion):
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
            self._broadcast(TiebreakerRejectedEvent(alias=alias))
            return

        accepted_now: bool = False
        if is_mutual_winner or (
            (alias in self._cm.get_all_contacts())
            and Settings.get(SettingKey.AUTO_ACCEPT_CONTACTS)
        ):
            self._state.add_active_connection(onion, conn)
            accepted_now = True
        else:
            self._state.add_pending_connection(onion, conn, stream.get_buffer())

        if accepted_now:
            try:
                conn.sendall(f'{TorCommand.ACCEPTED.value}\n'.encode('utf-8'))
            except Exception:
                pass

            self._hm.log_event(HistoryEvent.LIVE_CONNECTED, onion)
            self._broadcast(ConnectedEvent(alias=alias, onion=onion))

            if self._receiver:
                self._receiver.start_receiving(onion, conn, stream.get_buffer())
        else:
            self._hm.log_event(HistoryEvent.LIVE_REQUESTED_BY_REMOTE, onion)
            self._broadcast(IncomingConnectionEvent(alias=alias))
