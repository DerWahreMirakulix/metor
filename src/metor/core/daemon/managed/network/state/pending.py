"""Exact pending-request identities, expiry and atomic socket admission."""

from dataclasses import dataclass
import socket
import secrets
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

from metor.core.api import ConnectionOrigin
from metor.core.daemon.managed.network.state.types import PendingConnectionReason
from metor.utils import Constants


@dataclass(frozen=True)
class PendingConnectionSnapshot:
    """Represents one pending live-request snapshot for startup rendering."""

    onion: str
    reason: Optional[PendingConnectionReason]
    origin: Optional[ConnectionOrigin]
    expires_at: Optional[float]
    action_handle: Optional[str] = None


class StateTrackerPendingMixin:
    """Owns pending request operations within the shared state coordinator lock."""

    _lock: threading.RLock

    _connections: Dict[str, socket.socket]

    _pending_connections: Dict[str, socket.socket]

    _pending_connection_reasons: Dict[str, PendingConnectionReason]

    _pending_connection_origins: Dict[str, ConnectionOrigin]

    _pending_connection_deadlines: Dict[str, float]

    _pending_connection_tokens: Dict[str, str]

    _outbound_attempts: Set[str]
    _outbound_attempt_ids: Dict[str, str]

    _outbound_attempt_origins: Dict[str, ConnectionOrigin]

    _outbound_sockets: Dict[str, socket.socket]

    _outbound_connected_origin_overrides: Dict[str, ConnectionOrigin]

    _recent_outbound_attempts: Dict[str, float]

    _initial_buffers: Dict[str, bytes]

    _expired_pending_connections: Dict[str, float]

    _live_reconnect_grace: Dict[str, float]

    _retunnel_in_progress: Set[str]

    def retire_connection(
        self, conn: socket.socket, *, preserve_final: bool = False
    ) -> None:
        """Delegates exact socket retirement to the state coordinator.

        Args:
            conn (socket.socket): Retiring transport.
            preserve_final (bool): Preserve admitted local final control.

        Returns:
            None
        """
        raise NotImplementedError

    def add_pending_connection(
        self,
        onion: str,
        conn: socket.socket,
        initial_buffer: bytes,
        reason: PendingConnectionReason = PendingConnectionReason.USER_ACCEPT,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
        expiry_deadline: Optional[float] = None,
    ) -> bool:
        """
        Registers a socket connection awaiting local user acceptance.

        Args:
            onion (str): The peer onion address.
            conn (socket.socket): The pending socket to track.
            initial_buffer (bytes): Any leftover unread stream bytes.
            reason (PendingConnectionReason): The reason why the connection is pending.
            origin (ConnectionOrigin): The semantic origin of the live flow.
            expiry_deadline (Optional[float]): Optional expiry timestamp for the pending request.

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
                if replaced_pending is not conn:
                    self._pending_connection_tokens[onion] = secrets.token_hex(
                        Constants.PENDING_CALL_TOKEN_BYTES
                    )
                self._initial_buffers[onion] = initial_buffer
                self._pending_connection_reasons[onion] = reason
                self._pending_connection_origins[onion] = origin
                if expiry_deadline is None:
                    self._pending_connection_deadlines.pop(onion, None)
                else:
                    self._pending_connection_deadlines[onion] = expiry_deadline
                self._outbound_attempts.discard(onion)
                self._outbound_attempt_ids.pop(onion, None)
                self._outbound_attempt_origins.pop(onion, None)
                self._outbound_sockets.pop(onion, None)
                self._outbound_connected_origin_overrides.pop(onion, None)
                self._recent_outbound_attempts.pop(onion, None)
                self._expired_pending_connections.pop(onion, None)
                self._live_reconnect_grace.pop(onion, None)

        if replaced_pending is not None and replaced_pending is not conn:
            self.retire_connection(replaced_pending)

        if not should_track:
            self.retire_connection(conn)

        return should_track

    def pop_pending_connection(
        self, onion: str, expected_socket: Optional[socket.socket] = None
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
            if (
                expected_socket is not None
                and self._pending_connections.get(onion) is not expected_socket
            ):
                return None, b'', None, None
            conn: Optional[socket.socket] = self._pending_connections.pop(onion, None)
            self._pending_connection_tokens.pop(onion, None)
            buf: bytes = self._initial_buffers.pop(onion, b'')
            reason: Optional[PendingConnectionReason] = (
                self._pending_connection_reasons.pop(onion, None)
            )
            origin: Optional[ConnectionOrigin] = self._pending_connection_origins.pop(
                onion, None
            )
            self._pending_connection_deadlines.pop(onion, None)
            if conn is not None:
                self._expired_pending_connections.pop(onion, None)
            return conn, buf, reason, origin

    def pending_token(
        self, onion: str, expected_socket: Optional[socket.socket] = None
    ) -> Optional[str]:
        """Returns the opaque identity of exactly the still-pending request.

        Args:
            onion: Canonical peer identity.
            expected_socket: Optional source socket guard for event publication.
        Returns:
            Optional[str]: Runtime-only token, absent after replacement or expiry.
        """
        with self._lock:
            current = self._pending_connections.get(onion)
            deadline = self._pending_connection_deadlines.get(onion)
            if (
                current is None
                or (expected_socket is not None and current is not expected_socket)
                or (deadline is not None and deadline <= time.time())
            ):
                return None
            return self._pending_connection_tokens.get(onion)

    def pending_identity(self, onion: str) -> tuple[socket.socket, float] | None:
        """Returns exact pending socket ownership with its bounded deadline.

        Args:
            onion (str): The onion input.

        Returns:
            tuple[socket.socket, float] | None: The resulting value.
        """
        with self._lock:
            conn = self._pending_connections.get(onion)
            deadline = self._pending_connection_deadlines.get(onion)
            if conn is None:
                return None
            if deadline is not None and deadline <= time.time():
                return None
            return (
                conn,
                deadline
                if deadline is not None
                else time.time() + Constants.PENDING_EXPIRY_FEEDBACK_WINDOW_SEC,
            )

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

    def get_pending_connection_snapshots(self) -> List[PendingConnectionSnapshot]:
        """
        Returns startup-oriented pending connection snapshots for all tracked peers.

        Args:
            None

        Returns:
            List[PendingConnectionSnapshot]: Pending connection snapshots.
        """
        with self._lock:
            return [
                PendingConnectionSnapshot(
                    onion=onion,
                    reason=self._pending_connection_reasons.get(onion),
                    origin=self._pending_connection_origins.get(onion),
                    expires_at=self._pending_connection_deadlines.get(onion),
                    action_handle=self._pending_connection_tokens.get(onion),
                )
                for onion in self._pending_connections.keys()
            ]

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
            self._pending_connection_tokens.pop(onion, None)
            self._initial_buffers.pop(onion, None)
            self._pending_connection_reasons.pop(onion, None)
            self._pending_connection_origins.pop(onion, None)
            self._pending_connection_deadlines.pop(onion, None)
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
