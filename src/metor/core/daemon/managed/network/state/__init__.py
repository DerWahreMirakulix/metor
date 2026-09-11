"""Thread-safe network state tracking facade and coordinator."""

import socket
import threading
from typing import Callable, Dict, List, Optional, Set, Tuple

from metor.core.api import ConnectionActor, ConnectionOrigin, ConnectionReasonCode
from metor.utils import Constants
from metor.core.daemon.managed.models import TunnelState
from metor.core.daemon.managed.writer import BoundedSocketWriter
from metor.core.daemon.managed.network.state.connections import (
    PendingConnectionSnapshot,
    StateTrackerConnectionsMixin,
)
from metor.core.daemon.managed.network.state.messages import StateTrackerMessagesMixin
from metor.core.daemon.managed.network.state.retunnel import StateTrackerRetunnelMixin
from metor.core.daemon.managed.network.state.transport import StateTrackerTransportMixin
from metor.core.daemon.managed.network.state.types import PendingConnectionReason


class StateTracker(
    StateTrackerConnectionsMixin,
    StateTrackerMessagesMixin,
    StateTrackerTransportMixin,
    StateTrackerRetunnelMixin,
):
    """Tracks active sockets, pending connections, queues, and UI focus states safely."""

    def __init__(self) -> None:
        """
        Initializes the thread-safe dictionaries and lock-backed state containers.

        Args:
            None

        Returns:
            None
        """
        self._lock: threading.Lock = threading.Lock()
        self._connections: Dict[str, socket.socket] = {}
        self._pending_connections: Dict[str, socket.socket] = {}
        self._pending_connection_reasons: Dict[str, PendingConnectionReason] = {}
        self._pending_connection_origins: Dict[str, ConnectionOrigin] = {}
        self._pending_connection_deadlines: Dict[str, float] = {}
        self._unauthenticated_connections: Set[socket.socket] = set()
        self._outbound_attempts: Set[str] = set()
        self._outbound_attempt_origins: Dict[str, ConnectionOrigin] = {}
        self._outbound_sockets: Dict[str, socket.socket] = {}
        self._outbound_connected_origin_overrides: Dict[str, ConnectionOrigin] = {}
        self._recent_outbound_attempts: Dict[str, float] = {}
        self._initial_buffers: Dict[str, bytes] = {}
        self._expired_pending_connections: Dict[str, float] = {}
        self._scheduled_auto_reconnects: Set[str] = set()
        self._unacked_messages: Dict[str, Dict[str, Tuple[str, str]]] = {}
        self._message_request_ids: Dict[str, str] = {}
        self._recent_live_msg_ids: Dict[str, List[str]] = {}
        self._locally_terminated_sockets: Set[socket.socket] = set()
        self._drop_tunnels: Dict[str, TunnelState] = {}
        self._live_reconnect_grace: Dict[str, float] = {}
        self._local_recovery_opt_outs: Dict[str, float] = {}
        self._retunnel_reconnects: Set[str] = set()
        self._retunnel_in_progress: Set[str] = set()
        self._retunnel_recovery_retry_counts: Dict[str, int] = {}
        self._retunnel_recovery_retry_pending: Set[str] = set()
        self._ui_focus_counts: Dict[str, int] = {}
        self._session_last_activity: Dict[str, float] = {}
        self._last_disconnect_reasons: Dict[str, ConnectionReasonCode] = {}
        self._last_disconnect_actors: Dict[str, ConnectionActor] = {}
        self._socket_write_locks: Dict[socket.socket, threading.Lock] = {}
        self._socket_writers: Dict[socket.socket, BoundedSocketWriter] = {}
        self._live_generations: Dict[Tuple[str, str], int] = {}
        self._next_live_generation = 1

    def _writer_exited(self, conn: socket.socket, writer: BoundedSocketWriter) -> None:
        """Drops an idle or failed socket writer without retaining bookkeeping."""
        with self._lock:
            if self._socket_writers.get(conn) is writer:
                self._socket_writers.pop(conn, None)

    def send_frame(
        self,
        conn: socket.socket,
        frame: bytes,
        claim: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Serializes one complete application frame per shared peer socket.

        Args:
            conn (socket.socket): Authenticated peer socket.
            frame (bytes): Complete bounded application frame.

        Returns:
            None
        """
        if not isinstance(conn, socket.socket):
            if claim is not None and not claim():
                return
            with self._lock:
                write_lock = self._socket_write_locks.setdefault(conn, threading.Lock())
            with write_lock:
                conn.sendall(frame)
            return
        with self._lock:
            writer = self._socket_writers.get(conn)
            if writer is None:
                writer = BoundedSocketWriter(
                    conn,
                    capacity=Constants.PEER_WRITER_QUEUE_FRAMES,
                    on_exit=lambda exited: self._writer_exited(conn, exited),
                )
                self._socket_writers[conn] = writer
        writer.enqueue(frame, claim)

    def live_generation(self, onion: str, msg_id: str) -> int:
        """Returns the current emission generation for one LIVE identity."""
        with self._lock:
            key = (onion, msg_id)
            generation = self._live_generations.get(key)
            if generation is None:
                generation = self._next_live_generation
                self._next_live_generation += 1
                self._live_generations[key] = generation
            return generation

    def is_live_generation(self, onion: str, msg_id: str, generation: int) -> bool:
        """Checks a queued LIVE frame claim at the writer boundary."""
        with self._lock:
            return self._live_generations.get((onion, msg_id)) == generation

    def invalidate_live_generations(
        self, onion: str, msg_ids: Optional[List[str]] = None
    ) -> None:
        """Invalidates queued LIVE frames for selected durable identities."""
        with self._lock:
            selected = (
                msg_ids
                if msg_ids is not None
                else [
                    msg_id for peer, msg_id in self._live_generations if peer == onion
                ]
            )
            for msg_id in selected:
                self._live_generations.pop((onion, msg_id), None)

    def invalidate_all_live_generations(self) -> None:
        """Invalidates all queued LIVE work at a destructive/runtime fence."""
        with self._lock:
            self._live_generations.clear()

    def snapshot_token(self) -> Tuple[object, ...]:
        """Returns an atomic content-free fingerprint of projected LIVE state."""
        with self._lock:
            return (
                tuple(
                    sorted((key, id(value)) for key, value in self._connections.items())
                ),
                tuple(
                    sorted(
                        (key, id(value))
                        for key, value in self._pending_connections.items()
                    )
                ),
                tuple(sorted(self._outbound_attempts)),
                tuple(sorted(self._scheduled_auto_reconnects)),
                tuple(sorted(self._live_reconnect_grace.items())),
                tuple(sorted(self._retunnel_in_progress)),
                tuple(
                    sorted(
                        (peer, tuple(sorted(messages)))
                        for peer, messages in self._unacked_messages.items()
                    )
                ),
                tuple(sorted(self._last_disconnect_reasons.items())),
                tuple(sorted(self._last_disconnect_actors.items())),
                tuple(sorted(self._ui_focus_counts.items())),
            )


__all__ = ['PendingConnectionReason', 'PendingConnectionSnapshot', 'StateTracker']
