"""
Module executing the continuous read-loop for active Tor live connections.
Parses incoming data streams and delegates payloads to the Application Layer (Router).
"""

import socket
import threading
from typing import Optional, Callable, List, cast, TYPE_CHECKING

from metor.core.api import (
    IpcEvent,
    ConnectedEvent,
    ConnectionPendingEvent,
    RetunnelSuccessEvent,
)
from metor.core.daemon.models import TorCommand
from metor.data import (
    HistoryManager,
    HistoryEvent,
    ContactManager,
    SettingKey,
)

# Local Package Imports
from metor.core.daemon.network.state import StateTracker
from metor.core.daemon.network.stream import TcpStreamReader
from metor.core.daemon.network.router import MessageRouter

if TYPE_CHECKING:
    from metor.data.profile.config import Config


class StreamReceiver:
    """Manages the background read-loop for fully established Tor sockets."""

    def __init__(
        self,
        cm: ContactManager,
        hm: HistoryManager,
        state: StateTracker,
        router: MessageRouter,
        broadcast_callback: Callable[[IpcEvent], None],
        has_clients_callback: Callable[[], bool],
        disconnect_cb: Callable[[str, bool, bool, Optional[socket.socket]], None],
        reject_cb: Callable[[str, bool, Optional[socket.socket]], None],
        config: 'Config',
    ) -> None:
        """
        Initializes the StreamReceiver.

        Args:
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            state (StateTracker): The thread-safe state container.
            router (MessageRouter): The application-layer message router.
            broadcast_callback (Callable): IPC broadcaster.
            has_clients_callback (Callable): Checks for active UI clients.
            disconnect_cb (Callable): Controller callback to handle safe disconnections.
            reject_cb (Callable): Controller callback to handle safe rejections.
            config (Config): The profile configuration instance.

        Returns:
            None
        """
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._state: StateTracker = state
        self._router: MessageRouter = router
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._has_clients_callback: Callable[[], bool] = has_clients_callback
        self._config: 'Config' = config

        self._disconnect_cb: Callable[
            [str, bool, bool, Optional[socket.socket]], None
        ] = disconnect_cb
        self._reject_cb: Callable[[str, bool, Optional[socket.socket]], None] = (
            reject_cb
        )

    def start_receiving(
        self,
        onion: str,
        conn: socket.socket,
        initial_buffer: str = '',
        awaiting_acceptance: bool = False,
    ) -> None:
        """
        Starts a background thread to listen for data securely.

        Args:
            onion (str): The connected remote onion.
            conn (socket.socket): The active socket connection.
            initial_buffer (str): Leftover TCP stream buffer.
            awaiting_acceptance (bool): Whether the socket is still waiting for live acceptance.

        Returns:
            None
        """
        threading.Thread(
            target=self._receiver_target,
            args=(onion, conn, initial_buffer, awaiting_acceptance),
            daemon=True,
        ).start()

    def _receiver_target(
        self,
        onion: str,
        conn: socket.socket,
        initial_buffer: str = '',
        awaiting_acceptance: bool = False,
    ) -> None:
        """
        Target processing incoming live messages via the memory-safe reader.

        Args:
            onion (str): The remote onion.
            conn (socket.socket): The active socket connection.
            initial_buffer (str): Leftover TCP stream buffer.
            awaiting_acceptance (bool): Whether the socket is still waiting for live acceptance.

        Returns:
            None
        """
        remote_rejected: bool = False
        remote_disconnected: bool = False

        idle_timeout: float = self._config.get_float(SettingKey.STREAM_IDLE_TIMEOUT)
        late_acceptance_timeout: float = self._config.get_float(
            SettingKey.LATE_ACCEPTANCE_TIMEOUT
        )
        conn.settimeout(
            late_acceptance_timeout if awaiting_acceptance else idle_timeout
        )

        stream: TcpStreamReader = TcpStreamReader(conn, initial_buffer)

        try:
            while True:
                try:
                    msg: Optional[str] = stream.read_line()
                except socket.timeout:
                    if awaiting_acceptance:
                        break
                    continue

                if not msg:
                    break

                if msg == TorCommand.ACCEPTED.value:
                    awaiting_acceptance = False
                    conn.settimeout(idle_timeout)
                    self._state.add_active_connection(onion, conn)
                    alias: str = cast(str, self._cm.ensure_alias_for_onion(onion))
                    self._hm.log_event(HistoryEvent.LIVE_CONNECTED, onion)
                    if self._state.consume_retunnel_reconnect(onion):
                        self._hm.log_event(HistoryEvent.LIVE_RETUNNEL_SUCCESS, onion)
                        self._state.clear_retunnel_flow(onion)
                        self._broadcast(RetunnelSuccessEvent(alias=alias))
                    else:
                        self._broadcast(ConnectedEvent(alias=alias, onion=onion))

                elif msg == TorCommand.PENDING.value:
                    awaiting_acceptance = True
                    conn.settimeout(late_acceptance_timeout)
                    if not self._state.is_retunneling(onion):
                        alias = cast(str, self._cm.ensure_alias_for_onion(onion))
                        self._broadcast(ConnectionPendingEvent(alias=alias))

                elif msg.startswith(f'{TorCommand.DISCONNECT.value} '):
                    remote_disconnected = True
                    break
                elif msg.startswith(f'{TorCommand.REJECT.value} '):
                    remote_rejected = True
                    break
                elif msg.startswith(f'{TorCommand.ACK.value} '):
                    msg_id: str = msg.split(' ')[1]
                    self._router.process_incoming_ack(onion, msg_id)

                elif msg.startswith(f'{TorCommand.MSG.value} '):
                    parts: List[str] = msg.split(' ', 2)
                    if len(parts) == 3:
                        msg_id = parts[1]
                        content: str = parts[2]

                        should_disconnect: bool = self._router.process_incoming_msg(
                            conn, onion, msg_id, content
                        )
                        if should_disconnect:
                            self._disconnect_cb(onion, True, False, None)
                            break
        except Exception:
            pass
        finally:
            if remote_rejected:
                self._reject_cb(onion, False, conn)
            elif remote_disconnected:
                self._disconnect_cb(onion, False, False, conn)
            else:
                self._disconnect_cb(onion, False, True, conn)
