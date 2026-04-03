"""Connection and pending-session state mixins."""

import socket
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

from metor.core.api import ConnectionOrigin
from metor.core.daemon.models import LiveTransportState
from metor.core.daemon.network.state.types import PendingConnectionReason
from metor.utils import Constants


class StateTrackerConnectionsMixin:
    """Encapsulates live, pending, and outbound connection state operations."""

    _lock: threading.Lock
    _connections: Dict[str, socket.socket]
    _pending_connections: Dict[str, socket.socket]
    _pending_connection_reasons: Dict[str, PendingConnectionReason]
    _pending_connection_origins: Dict[str, ConnectionOrigin]
    _outbound_attempts: Set[str]
    _outbound_attempt_origins: Dict[str, ConnectionOrigin]
    _outbound_sockets: Dict[str, socket.socket]
    _outbound_connected_origin_overrides: Dict[str, ConnectionOrigin]
    _recent_outbound_attempts: Dict[str, float]
    _initial_buffers: Dict[str, str]
    _expired_pending_connections: Dict[str, float]
    _scheduled_auto_reconnects: Set[str]
    _live_reconnect_grace: Dict[str, float]
    _retunnel_in_progress: Set[str]

    def get_active_onions(self) -> List[str]:
        """Returns a snapshot of all active and pending onion addresses."""
        with self._lock:
            return list(self._connections.keys()) + list(
                self._pending_connections.keys()
            )

    def get_active_connections_keys(self) -> List[str]:
        """Returns a snapshot of fully connected onion addresses."""
        with self._lock:
            return list(self._connections.keys())

    def get_pending_connections_keys(self) -> List[str]:
        """Returns a snapshot of pending connection onion addresses."""
        with self._lock:
            return list(self._pending_connections.keys())

    def is_connected_or_pending(self, onion: str) -> bool:
        """Checks if an onion address is currently tracked in any live session state."""
        with self._lock:
            return onion in self._connections or onion in self._pending_connections

    def is_live_active(self, onion: str) -> bool:
        """Checks whether a peer currently has an active live socket."""
        with self._lock:
            return onion in self._connections

    def get_live_state(self, onion: str) -> LiveTransportState:
        """Derives the live transport lifecycle state for one peer."""
        with self._lock:
            if onion in self._connections:
                return LiveTransportState.CONNECTED
            if onion in self._pending_connections:
                return LiveTransportState.PENDING
            if onion in self._retunnel_in_progress:
                return LiveTransportState.RETUNNELING
            if onion in self._outbound_attempts:
                return LiveTransportState.CONNECTING
            return LiveTransportState.DISCONNECTED

    def has_outbound_attempt(self, onion: str) -> bool:
        """Checks if an outbound connection attempt is currently in flight."""
        with self._lock:
            return onion in self._outbound_attempts

    def has_active_or_recent_outbound_attempt(self, onion: str) -> bool:
        """Checks if an outbound attempt is still active or only very recently ended."""
        with self._lock:
            if onion in self._outbound_attempts:
                return True

            deadline: Optional[float] = self._recent_outbound_attempts.get(onion)
            if deadline is None:
                return False

            if deadline > time.time():
                return True

            self._recent_outbound_attempts.pop(onion, None)
            return False

    def add_outbound_attempt(
        self,
        onion: str,
        origin: ConnectionOrigin = ConnectionOrigin.MANUAL,
    ) -> None:
        """Registers a new outbound connection attempt."""
        with self._lock:
            self._outbound_attempts.add(onion)
            self._outbound_attempt_origins[onion] = origin

    def get_outbound_attempt_origin(self, onion: str) -> Optional[ConnectionOrigin]:
        """Returns the semantic origin of one tracked outbound attempt."""
        with self._lock:
            return self._outbound_attempt_origins.get(onion)

    def override_outbound_connected_origin(
        self,
        onion: str,
        origin: ConnectionOrigin,
    ) -> None:
        """Overrides the origin to use once one outbound attempt connects."""
        with self._lock:
            if onion in self._outbound_attempts:
                self._outbound_connected_origin_overrides[onion] = origin

    def consume_outbound_connected_origin(
        self,
        onion: str,
    ) -> Optional[ConnectionOrigin]:
        """Consumes one pending outbound connected-origin override."""
        with self._lock:
            return self._outbound_connected_origin_overrides.pop(onion, None)

    def discard_outbound_attempt(self, onion: str) -> None:
        """Cleans up a tracked outbound attempt safely."""
        with self._lock:
            self._outbound_attempts.discard(onion)
            self._outbound_attempt_origins.pop(onion, None)
            self._outbound_sockets.pop(onion, None)
            self._outbound_connected_origin_overrides.pop(onion, None)

    def bind_outbound_socket(self, onion: str, conn: socket.socket) -> None:
        """Associates the current outbound attempt with its concrete socket instance."""
        with self._lock:
            self._outbound_attempts.add(onion)
            self._outbound_sockets[onion] = conn
            self._recent_outbound_attempts[onion] = (
                time.time() + Constants.MUTUAL_CONNECT_RACE_WINDOW_SEC
            )

    def is_current_outbound_socket(self, onion: str, sock: socket.socket) -> bool:
        """Checks whether a socket is the current tracked outbound attempt."""
        with self._lock:
            return self._outbound_sockets.get(onion) == sock

    def add_active_connection(self, onion: str, conn: socket.socket) -> None:
        """Registers a fully authenticated, live socket connection."""
        with self._lock:
            self._connections[onion] = conn
            self._outbound_attempts.discard(onion)
            self._outbound_attempt_origins.pop(onion, None)
            self._outbound_sockets.pop(onion, None)
            self._outbound_connected_origin_overrides.pop(onion, None)
            self._recent_outbound_attempts.pop(onion, None)
            self._scheduled_auto_reconnects.discard(onion)
            self._live_reconnect_grace.pop(onion, None)
            if onion in self._pending_connections:
                self._pending_connections.pop(onion)
            self._pending_connection_reasons.pop(onion, None)
            self._pending_connection_origins.pop(onion, None)
            self._initial_buffers.pop(onion, None)
            self._expired_pending_connections.pop(onion, None)

    def add_pending_connection(
        self,
        onion: str,
        conn: socket.socket,
        initial_buffer: str,
        reason: PendingConnectionReason = PendingConnectionReason.USER_ACCEPT,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        """Registers a socket connection awaiting local user acceptance."""
        with self._lock:
            self._pending_connections[onion] = conn
            self._initial_buffers[onion] = initial_buffer
            self._pending_connection_reasons[onion] = reason
            self._pending_connection_origins[onion] = origin
            self._outbound_attempts.discard(onion)
            self._outbound_attempt_origins.pop(onion, None)
            self._outbound_sockets.pop(onion, None)
            self._outbound_connected_origin_overrides.pop(onion, None)
            self._recent_outbound_attempts.pop(onion, None)
            self._expired_pending_connections.pop(onion, None)
            self._live_reconnect_grace.pop(onion, None)

    def pop_pending_connection(
        self, onion: str
    ) -> Tuple[
        Optional[socket.socket],
        str,
        Optional[PendingConnectionReason],
        Optional[ConnectionOrigin],
    ]:
        """Retrieves and removes a pending connection for acceptance processing."""
        with self._lock:
            conn: Optional[socket.socket] = self._pending_connections.pop(onion, None)
            buf: str = self._initial_buffers.pop(onion, '')
            reason: Optional[PendingConnectionReason] = (
                self._pending_connection_reasons.pop(onion, None)
            )
            origin: Optional[ConnectionOrigin] = self._pending_connection_origins.pop(
                onion, None
            )
            if conn is not None:
                self._expired_pending_connections.pop(onion, None)
            return conn, buf, reason, origin

    def get_pending_connection_reason(
        self, onion: str
    ) -> Optional[PendingConnectionReason]:
        """Returns the internal reason for one pending inbound connection."""
        with self._lock:
            return self._pending_connection_reasons.get(onion)

    def get_pending_connection_origin(self, onion: str) -> Optional[ConnectionOrigin]:
        """Returns the semantic origin for one pending inbound connection."""
        with self._lock:
            return self._pending_connection_origins.get(onion)

    def set_pending_connection_reason(
        self, onion: str, reason: PendingConnectionReason
    ) -> bool:
        """Updates the internal reason for one pending inbound connection."""
        with self._lock:
            if onion not in self._pending_connections:
                return False
            self._pending_connection_reasons[onion] = reason
            return True

    def get_pending_connections_with_reason(
        self, reason: PendingConnectionReason
    ) -> List[str]:
        """Returns all pending onions with one specific internal reason."""
        with self._lock:
            return [
                onion
                for onion, pending_reason in self._pending_connection_reasons.items()
                if pending_reason is reason and onion in self._pending_connections
            ]

    def is_pending_socket(self, onion: str, sock: socket.socket) -> bool:
        """Checks whether a socket is the currently tracked pending connection."""
        with self._lock:
            return self._pending_connections.get(onion) == sock

    def remove_pending_connection_if_socket(
        self, onion: str, sock: socket.socket
    ) -> bool:
        """Removes a pending connection only if the tracked socket still matches."""
        with self._lock:
            if self._pending_connections.get(onion) != sock:
                return False

            self._pending_connections.pop(onion, None)
            self._initial_buffers.pop(onion, None)
            self._pending_connection_reasons.pop(onion, None)
            self._pending_connection_origins.pop(onion, None)
            return True

    def mark_recent_pending_expiry(self, onion: str) -> None:
        """Remembers that a pending live request just expired."""
        with self._lock:
            self._expired_pending_connections[onion] = (
                time.time() + Constants.PENDING_EXPIRY_FEEDBACK_WINDOW_SEC
            )

    def consume_recent_pending_expiry(self, onion: str) -> bool:
        """Consumes one recent pending-expiry marker if it is still valid."""
        with self._lock:
            deadline: Optional[float] = self._expired_pending_connections.get(onion)
            if deadline is None:
                return False

            self._expired_pending_connections.pop(onion, None)
            return deadline > time.time()

    def get_connection(self, onion: str) -> Optional[socket.socket]:
        """Retrieves a fully active socket connection without removing it."""
        with self._lock:
            return self._connections.get(onion)

    def pop_any_connection(self, onion: str) -> Optional[socket.socket]:
        """Removes and returns any tracked socket connection for teardown."""
        with self._lock:
            conn: Optional[socket.socket] = self._connections.pop(
                onion, None
            ) or self._pending_connections.pop(onion, None)
            self._outbound_attempt_origins.pop(onion, None)
            self._outbound_sockets.pop(onion, None)
            self._outbound_connected_origin_overrides.pop(onion, None)
            self._recent_outbound_attempts.pop(onion, None)
            self._scheduled_auto_reconnects.discard(onion)
            self._live_reconnect_grace.pop(onion, None)
            self._initial_buffers.pop(onion, None)
            self._pending_connection_reasons.pop(onion, None)
            self._pending_connection_origins.pop(onion, None)
            self._expired_pending_connections.pop(onion, None)
            return conn

    def mark_scheduled_auto_reconnect(self, onion: str) -> None:
        """Marks that the daemon still intends to reconnect to one peer automatically."""
        with self._lock:
            self._scheduled_auto_reconnects.add(onion)

    def clear_scheduled_auto_reconnect(self, onion: str) -> None:
        """Clears one automatic reconnect intent."""
        with self._lock:
            self._scheduled_auto_reconnects.discard(onion)

    def has_scheduled_auto_reconnect(self, onion: str) -> bool:
        """Checks whether one peer still has a live auto-reconnect intent."""
        with self._lock:
            return onion in self._scheduled_auto_reconnects
