"""Connection and pending-session state mixins."""

import socket
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

from metor.core.api import ConnectionOrigin
from metor.core.daemon.managed.models import LiveTransportState
from metor.core.daemon.managed.network.state.types import PendingConnectionReason
from metor.utils import Constants


def _close_socket(sock: socket.socket) -> None:
    """
    Closes one superseded socket while suppressing teardown noise.

    Args:
        sock (socket.socket): The socket to close.

    Returns:
        None
    """
    try:
        sock.close()
    except OSError:
        pass


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
    _initial_buffers: Dict[str, bytes]
    _expired_pending_connections: Dict[str, float]
    _scheduled_auto_reconnects: Set[str]
    _live_reconnect_grace: Dict[str, float]
    _local_recovery_opt_outs: Dict[str, float]
    _retunnel_in_progress: Set[str]

    def get_active_onions(self) -> List[str]:
        """
        Returns a snapshot of all onion identities with active or pending live state.

        Args:
            None

        Returns:
            List[str]: Active and pending onion identities.
        """
        with self._lock:
            return list(self._connections.keys()) + list(
                self._pending_connections.keys()
            )

    def get_active_connections_keys(self) -> List[str]:
        """
        Returns a snapshot of onion identities with fully active live sockets.

        Args:
            None

        Returns:
            List[str]: Onion identities with active live connections.
        """
        with self._lock:
            return list(self._connections.keys())

    def get_pending_connections_keys(self) -> List[str]:
        """
        Returns a snapshot of onion identities with pending live connections.

        Args:
            None

        Returns:
            List[str]: Onion identities with pending live connections.
        """
        with self._lock:
            return list(self._pending_connections.keys())

    def is_connected_or_pending(self, onion: str) -> bool:
        """
        Checks whether one onion identity is tracked in any live session state.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if the peer is active or pending.
        """
        with self._lock:
            return onion in self._connections or onion in self._pending_connections

    def is_live_active(self, onion: str) -> bool:
        """
        Checks whether one peer currently has an active live socket.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if the peer has an active live socket.
        """
        with self._lock:
            return onion in self._connections

    def get_live_state(self, onion: str) -> LiveTransportState:
        """
        Derives the current live transport lifecycle state for one peer.

        Args:
            onion (str): The peer onion identity.

        Returns:
            LiveTransportState: The derived live transport lifecycle state.
        """
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
        """
        Checks whether an outbound connection attempt is currently in flight.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if an outbound attempt is currently tracked.
        """
        with self._lock:
            return onion in self._outbound_attempts

    def has_active_or_recent_outbound_attempt(self, onion: str) -> bool:
        """
        Checks whether an outbound attempt is active or only very recently ended.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if the peer still has active or recent outbound-attempt state.
        """
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
        """
        Registers a new outbound connection attempt for one peer.

        Args:
            onion (str): The peer onion identity.
            origin (ConnectionOrigin): The semantic origin of the outbound attempt.

        Returns:
            None
        """
        with self._lock:
            self._outbound_attempts.add(onion)
            self._outbound_attempt_origins[onion] = origin

    def get_outbound_attempt_origin(self, onion: str) -> Optional[ConnectionOrigin]:
        """
        Returns the semantic origin of one tracked outbound attempt.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Optional[ConnectionOrigin]: The recorded attempt origin, if present.
        """
        with self._lock:
            return self._outbound_attempt_origins.get(onion)

    def override_outbound_connected_origin(
        self,
        onion: str,
        origin: ConnectionOrigin,
    ) -> None:
        """
        Overrides the origin to use when one outbound attempt later connects.

        Args:
            onion (str): The peer onion identity.
            origin (ConnectionOrigin): The replacement semantic origin.

        Returns:
            None
        """
        with self._lock:
            if onion in self._outbound_attempts:
                self._outbound_connected_origin_overrides[onion] = origin

    def consume_outbound_connected_origin(
        self,
        onion: str,
    ) -> Optional[ConnectionOrigin]:
        """
        Consumes one pending outbound connected-origin override.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Optional[ConnectionOrigin]: The override origin, if one was recorded.
        """
        with self._lock:
            return self._outbound_connected_origin_overrides.pop(onion, None)

    def discard_outbound_attempt(self, onion: str) -> None:
        """
        Cleans up the bookkeeping for one tracked outbound attempt.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        with self._lock:
            self._outbound_attempts.discard(onion)
            self._outbound_attempt_origins.pop(onion, None)
            self._outbound_sockets.pop(onion, None)
            self._recent_outbound_attempts.pop(onion, None)
            self._outbound_connected_origin_overrides.pop(onion, None)

    def bind_outbound_socket(self, onion: str, conn: socket.socket) -> None:
        """
        Associates the current outbound attempt with its concrete socket instance.

        Args:
            onion (str): The peer onion identity.
            conn (socket.socket): The outbound socket instance.

        Returns:
            None
        """
        with self._lock:
            self._outbound_attempts.add(onion)
            self._outbound_sockets[onion] = conn
            self._recent_outbound_attempts[onion] = (
                time.time() + Constants.MUTUAL_CONNECT_RACE_WINDOW_SEC
            )

    def clear_bound_outbound_socket(
        self,
        onion: str,
        conn: Optional[socket.socket] = None,
    ) -> None:
        """
        Removes one bound outbound socket while keeping the attempt bookkeeping intact.

        Args:
            onion (str): The peer onion identity.
            conn (Optional[socket.socket]): Optional guard socket that must still match
                the tracked outbound socket.

        Returns:
            None
        """
        with self._lock:
            current_conn: Optional[socket.socket] = self._outbound_sockets.get(onion)
            if conn is not None and current_conn is not conn:
                return

            self._outbound_sockets.pop(onion, None)

    def pop_outbound_socket(self, onion: str) -> Optional[socket.socket]:
        """
        Removes and returns the current outbound-attempt socket while clearing its bookkeeping.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Optional[socket.socket]: The bound outbound socket, if present.
        """
        with self._lock:
            conn: Optional[socket.socket] = self._outbound_sockets.pop(onion, None)
            self._outbound_attempts.discard(onion)
            self._outbound_attempt_origins.pop(onion, None)
            self._recent_outbound_attempts.pop(onion, None)
            self._outbound_connected_origin_overrides.pop(onion, None)
            return conn

    def is_current_outbound_socket(self, onion: str, sock: socket.socket) -> bool:
        """
        Checks whether one socket is the current tracked outbound attempt.

        Args:
            onion (str): The peer onion identity.
            sock (socket.socket): The socket instance to inspect.

        Returns:
            bool: True if the socket is the current outbound attempt.
        """
        with self._lock:
            return self._outbound_sockets.get(onion) == sock

    def add_active_connection(self, onion: str, conn: socket.socket) -> None:
        """
        Registers one fully authenticated live socket as the active connection.

        Args:
            onion (str): The peer onion identity.
            conn (socket.socket): The authenticated live socket.

        Returns:
            None
        """
        replaced_active: Optional[socket.socket] = None
        replaced_pending: Optional[socket.socket] = None
        with self._lock:
            replaced_active = self._connections.get(onion)
            replaced_pending = self._pending_connections.pop(onion, None)
            self._connections[onion] = conn
            self._outbound_attempts.discard(onion)
            self._outbound_attempt_origins.pop(onion, None)
            self._outbound_sockets.pop(onion, None)
            self._outbound_connected_origin_overrides.pop(onion, None)
            self._recent_outbound_attempts.pop(onion, None)
            self._scheduled_auto_reconnects.discard(onion)
            self._live_reconnect_grace.pop(onion, None)
            self._local_recovery_opt_outs.pop(onion, None)
            self._pending_connection_reasons.pop(onion, None)
            self._pending_connection_origins.pop(onion, None)
            self._initial_buffers.pop(onion, None)
            self._expired_pending_connections.pop(onion, None)

        if replaced_active is not None and replaced_active is not conn:
            _close_socket(replaced_active)

        if replaced_pending is not None and replaced_pending is not conn:
            _close_socket(replaced_pending)

    def add_pending_connection(
        self,
        onion: str,
        conn: socket.socket,
        initial_buffer: bytes,
        reason: PendingConnectionReason = PendingConnectionReason.USER_ACCEPT,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> bool:
        """
        Registers a socket connection awaiting local user acceptance.

        Args:
            onion (str): The peer onion address.
            conn (socket.socket): The pending socket to track.
            initial_buffer (bytes): Any leftover unread stream bytes.
            reason (PendingConnectionReason): The reason why the connection is pending.
            origin (ConnectionOrigin): The semantic origin of the live flow.

        Returns:
            bool: True if the socket was tracked, False if an active connection already won the race.
        """
        active_conn: Optional[socket.socket] = None
        replaced_pending: Optional[socket.socket] = None
        should_track: bool = True
        with self._lock:
            active_conn = self._connections.get(onion)
            allow_recovery_replacement: bool = (
                onion in self._retunnel_in_progress
                or origin
                in {
                    ConnectionOrigin.AUTO_RECONNECT,
                    ConnectionOrigin.GRACE_RECONNECT,
                    ConnectionOrigin.RETUNNEL,
                }
            )
            if (
                active_conn is not None
                and active_conn is not conn
                and not allow_recovery_replacement
            ):
                should_track = False
            else:
                replaced_pending = self._pending_connections.get(onion)
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

        if replaced_pending is not None and replaced_pending is not conn:
            _close_socket(replaced_pending)

        if not should_track:
            _close_socket(conn)

        return should_track

    def pop_pending_connection(
        self, onion: str
    ) -> Tuple[
        Optional[socket.socket],
        bytes,
        Optional[PendingConnectionReason],
        Optional[ConnectionOrigin],
    ]:
        """
        Retrieves and removes one pending connection for acceptance processing.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Tuple[Optional[socket.socket], bytes, Optional[PendingConnectionReason], Optional[ConnectionOrigin]]:
                The pending socket, initial buffer, pending reason, and origin.
        """
        with self._lock:
            conn: Optional[socket.socket] = self._pending_connections.pop(onion, None)
            buf: bytes = self._initial_buffers.pop(onion, b'')
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
        """
        Returns the internal reason recorded for one pending inbound connection.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Optional[PendingConnectionReason]: The pending reason, if the peer is pending.
        """
        with self._lock:
            return self._pending_connection_reasons.get(onion)

    def get_pending_connection_origin(self, onion: str) -> Optional[ConnectionOrigin]:
        """
        Returns the semantic origin recorded for one pending inbound connection.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Optional[ConnectionOrigin]: The pending connection origin, if present.
        """
        with self._lock:
            return self._pending_connection_origins.get(onion)

    def set_pending_connection_reason(
        self, onion: str, reason: PendingConnectionReason
    ) -> bool:
        """
        Updates the internal reason recorded for one pending inbound connection.

        Args:
            onion (str): The peer onion identity.
            reason (PendingConnectionReason): The new pending reason.

        Returns:
            bool: True if the pending connection still existed and was updated.
        """
        with self._lock:
            if onion not in self._pending_connections:
                return False
            self._pending_connection_reasons[onion] = reason
            return True

    def get_pending_connections_with_reason(
        self, reason: PendingConnectionReason
    ) -> List[str]:
        """
        Returns all pending peers matching one specific internal pending reason.

        Args:
            reason (PendingConnectionReason): The pending reason to filter by.

        Returns:
            List[str]: Pending peer onion identities with the requested reason.
        """
        with self._lock:
            return [
                onion
                for onion, pending_reason in self._pending_connection_reasons.items()
                if pending_reason is reason and onion in self._pending_connections
            ]

    def is_pending_socket(self, onion: str, sock: socket.socket) -> bool:
        """
        Checks whether one socket is the currently tracked pending connection.

        Args:
            onion (str): The peer onion identity.
            sock (socket.socket): The socket instance to inspect.

        Returns:
            bool: True if the socket matches the tracked pending connection.
        """
        with self._lock:
            return self._pending_connections.get(onion) == sock

    def remove_pending_connection_if_socket(
        self, onion: str, sock: socket.socket
    ) -> bool:
        """
        Removes a pending connection only if the tracked socket still matches.

        Args:
            onion (str): The peer onion identity.
            sock (socket.socket): The socket instance expected to be pending.

        Returns:
            bool: True if the pending entry was removed.
        """
        with self._lock:
            if self._pending_connections.get(onion) != sock:
                return False

            self._pending_connections.pop(onion, None)
            self._initial_buffers.pop(onion, None)
            self._pending_connection_reasons.pop(onion, None)
            self._pending_connection_origins.pop(onion, None)
            return True

    def mark_recent_pending_expiry(self, onion: str) -> None:
        """
        Remembers that one pending live request just expired.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        with self._lock:
            self._expired_pending_connections[onion] = (
                time.time() + Constants.PENDING_EXPIRY_FEEDBACK_WINDOW_SEC
            )

    def consume_recent_pending_expiry(self, onion: str) -> bool:
        """
        Consumes one recent pending-expiry marker if it is still valid.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if a still-valid expiry marker was consumed.
        """
        with self._lock:
            deadline: Optional[float] = self._expired_pending_connections.get(onion)
            if deadline is None:
                return False

            self._expired_pending_connections.pop(onion, None)
            return deadline > time.time()

    def get_connection(self, onion: str) -> Optional[socket.socket]:
        """
        Retrieves one fully active socket connection without removing it.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Optional[socket.socket]: The active live socket, if present.
        """
        with self._lock:
            return self._connections.get(onion)

    def pop_any_connection(self, onion: str) -> Optional[socket.socket]:
        """
        Removes and returns any tracked socket connection for teardown.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Optional[socket.socket]: The active or pending socket selected for teardown.
        """
        active_conn: Optional[socket.socket] = None
        pending_conn: Optional[socket.socket] = None
        with self._lock:
            active_conn = self._connections.pop(onion, None)
            pending_conn = self._pending_connections.pop(onion, None)
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

        conn: Optional[socket.socket] = active_conn or pending_conn
        if (
            active_conn is not None
            and pending_conn is not None
            and pending_conn is not active_conn
        ):
            _close_socket(pending_conn)

        return conn

    def mark_scheduled_auto_reconnect(self, onion: str) -> None:
        """
        Marks that the daemon still intends to reconnect to one peer automatically.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        with self._lock:
            self._scheduled_auto_reconnects.add(onion)

    def clear_scheduled_auto_reconnect(self, onion: str) -> None:
        """
        Clears one automatic reconnect intent.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        with self._lock:
            self._scheduled_auto_reconnects.discard(onion)

    def has_scheduled_auto_reconnect(self, onion: str) -> bool:
        """
        Checks whether one peer still has a live auto-reconnect intent.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if an automatic reconnect is still scheduled.
        """
        with self._lock:
            return onion in self._scheduled_auto_reconnects
