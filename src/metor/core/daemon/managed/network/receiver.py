"""
Module executing the continuous read-loop for active Tor live connections.
Parses incoming data streams and delegates payloads to the Application Layer (Router).
"""

import socket
import threading
from typing import Optional, Callable, List, cast, TYPE_CHECKING

from metor.core.api import (
    ConnectionActor,
    ConnectionOrigin,
    IpcEvent,
    ConnectedEvent,
    ConnectionPendingEvent,
    RetunnelSuccessEvent,
)
from metor.core.daemon.managed.models import TorCommand
from metor.data import (
    HistoryActor,
    HistoryManager,
    HistoryEvent,
    ContactManager,
    SettingKey,
)

# Local Package Imports
from metor.core.daemon.managed.network.state import StateTracker
from metor.core.daemon.managed.network.stream import TcpStreamReader
from metor.core.daemon.managed.network.router import MessageRouter

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
        disconnect_cb: Callable[
            [
                str,
                bool,
                bool,
                Optional[socket.socket],
                bool,
                Optional[ConnectionOrigin],
            ],
            None,
        ],
        reject_cb: Callable[
            [str, bool, Optional[socket.socket], ConnectionOrigin],
            None,
        ],
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
        self._config: 'Config' = config

        self._disconnect_cb: Callable[
            [
                str,
                bool,
                bool,
                Optional[socket.socket],
                bool,
                Optional[ConnectionOrigin],
            ],
            None,
        ] = disconnect_cb
        self._reject_cb: Callable[
            [str, bool, Optional[socket.socket], ConnectionOrigin],
            None,
        ] = reject_cb

    @staticmethod
    def _parse_ack_msg_id(msg: str) -> Optional[str]:
        """
        Validates one live ACK frame and returns its message identifier.

        Args:
            msg (str): The raw newline-delimited frame.

        Returns:
            Optional[str]: The acknowledged message ID, or None if the frame is malformed.
        """
        parts: list[str] = msg.split()
        if len(parts) != 2 or parts[0] != TorCommand.ACK.value:
            return None

        return parts[1]

    def start_receiving(
        self,
        onion: str,
        conn: socket.socket,
        initial_buffer: bytes = b'',
        awaiting_acceptance: bool = False,
        connection_origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        """
        Starts a background thread to listen for data securely.

        Args:
            onion (str): The connected remote onion.
            conn (socket.socket): The active socket connection.
            initial_buffer (bytes): Leftover TCP stream buffer.
            awaiting_acceptance (bool): Whether the socket is still waiting for live acceptance.
            connection_origin (ConnectionOrigin): The machine-readable origin of the flow.

        Returns:
            None
        """
        threading.Thread(
            target=self._receiver_target,
            args=(onion, conn, initial_buffer, awaiting_acceptance, connection_origin),
            daemon=True,
        ).start()

    def _receiver_target(
        self,
        onion: str,
        conn: socket.socket,
        initial_buffer: bytes = b'',
        awaiting_acceptance: bool = False,
        connection_origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        """
        Target processing incoming live messages via the memory-safe reader.

        Args:
            onion (str): The remote onion.
            conn (socket.socket): The active socket connection.
            initial_buffer (bytes): Leftover TCP stream buffer.
            awaiting_acceptance (bool): Whether the socket is still waiting for live acceptance.
            connection_origin (ConnectionOrigin): The machine-readable origin of the flow.

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
                    effective_origin: ConnectionOrigin = (
                        self._state.consume_outbound_connected_origin(onion)
                        or connection_origin
                    )
                    awaiting_acceptance = False
                    conn.settimeout(idle_timeout)
                    self._state.add_active_connection(onion, conn)
                    alias: str = cast(str, self._cm.ensure_alias_for_onion(onion))
                    self._hm.log_event(
                        HistoryEvent.CONNECTED,
                        onion,
                        actor=(
                            HistoryActor.SYSTEM
                            if effective_origin is ConnectionOrigin.MUTUAL_CONNECT
                            else HistoryActor.REMOTE
                        ),
                        trigger=effective_origin,
                    )
                    if self._state.consume_retunnel_reconnect(onion):
                        self._hm.log_event(
                            HistoryEvent.RETUNNEL_SUCCEEDED,
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
                                origin=effective_origin,
                                actor=(
                                    ConnectionActor.SYSTEM
                                    if effective_origin
                                    is ConnectionOrigin.MUTUAL_CONNECT
                                    else ConnectionActor.REMOTE
                                ),
                            )
                        )

                elif msg == TorCommand.PENDING.value:
                    awaiting_acceptance = True
                    conn.settimeout(late_acceptance_timeout)
                    alias = cast(str, self._cm.ensure_alias_for_onion(onion))
                    self._broadcast(
                        ConnectionPendingEvent(
                            alias=alias,
                            onion=onion,
                            origin=connection_origin,
                            actor=ConnectionActor.REMOTE,
                        )
                    )

                elif msg == TorCommand.DISCONNECT.value or msg.startswith(
                    f'{TorCommand.DISCONNECT.value} '
                ):
                    remote_disconnected = True
                    break
                elif msg == TorCommand.REJECT.value or msg.startswith(
                    f'{TorCommand.REJECT.value} '
                ):
                    remote_rejected = True
                    break
                else:
                    ack_msg_id: Optional[str] = self._parse_ack_msg_id(msg)
                    if ack_msg_id is not None:
                        self._router.process_incoming_ack(onion, ack_msg_id)

                    elif msg.startswith(f'{TorCommand.MSG.value} '):
                        parts: List[str] = msg.split(' ', 2)
                        if len(parts) == 3:
                            msg_id = parts[1]
                            content: str = parts[2]

                            should_disconnect: bool = self._router.process_incoming_msg(
                                conn, onion, msg_id, content
                            )
                            if should_disconnect:
                                self._disconnect_cb(
                                    onion,
                                    True,
                                    False,
                                    None,
                                    False,
                                    connection_origin,
                                )
                                break
        except Exception:
            pass
        finally:
            if remote_rejected:
                self._reject_cb(onion, False, conn, connection_origin)
            elif remote_disconnected:
                self._disconnect_cb(
                    onion,
                    False,
                    False,
                    conn,
                    False,
                    connection_origin,
                )
            else:
                self._disconnect_cb(
                    onion,
                    False,
                    True,
                    conn,
                    False,
                    connection_origin,
                )
