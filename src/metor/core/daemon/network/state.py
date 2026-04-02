"""
Module for thread-safe network state tracking.
Enforces strict locking during dictionary mutations and iteration to prevent race conditions.
Implements Reference Counting to track IPC clients focusing on specific peers for Tunnel Keep-Alive logic.
"""

import socket
import threading
import time
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from metor.utils import Constants

from metor.core.daemon.models import (
    DropTunnelState,
    LiveTransportState,
    PeerTransportState,
    PrimaryTransport,
)


class PendingConnectionReason(str, Enum):
    """Describes why an inbound live socket currently remains pending."""

    USER_ACCEPT = 'user_accept'
    CONSUMER_ABSENT = 'consumer_absent'


class StateTracker:
    """Tracks active sockets, pending connections, offline queues, and UI focus states safely."""

    def __init__(self) -> None:
        """
        Initializes the thread-safe dictionaries and locking mechanism.

        Args:
            None

        Returns:
            None
        """
        self._lock: threading.Lock = threading.Lock()
        self._connections: Dict[str, socket.socket] = {}
        self._pending_connections: Dict[str, socket.socket] = {}
        self._pending_connection_reasons: Dict[str, PendingConnectionReason] = {}
        self._unauthenticated_connections: Set[socket.socket] = set()
        self._outbound_attempts: Set[str] = set()
        self._outbound_sockets: Dict[str, socket.socket] = {}
        self._initial_buffers: Dict[str, str] = {}
        self._unacked_messages: Dict[str, Dict[str, Tuple[str, str]]] = {}
        self._ram_buffers: Dict[str, List[Tuple[str, str, str]]] = {}
        self._recent_live_msg_ids: Dict[str, List[str]] = {}
        self._drop_tunnels: Dict[str, DropTunnelState] = {}
        self._live_reconnect_grace: Dict[str, float] = {}
        self._retunnel_reconnects: Set[str] = set()
        self._retunnel_in_progress: Set[str] = set()

        # Reference counting for UI clients currently focusing an onion
        self._ui_focus_counts: Dict[str, int] = {}

    def get_active_onions(self) -> List[str]:
        """
        Returns a snapshot of all active and pending onion addresses.

        Args:
            None

        Returns:
            List[str]: A list of active and pending onion identities.
        """
        with self._lock:
            return list(self._connections.keys()) + list(
                self._pending_connections.keys()
            )

    def get_active_connections_keys(self) -> List[str]:
        """
        Returns a snapshot of fully connected onion addresses.

        Args:
            None

        Returns:
            List[str]: A list of connected onion identities.
        """
        with self._lock:
            return list(self._connections.keys())

    def get_pending_connections_keys(self) -> List[str]:
        """
        Returns a snapshot of pending connection onion addresses.

        Args:
            None

        Returns:
            List[str]: A list of pending onion identities.
        """
        with self._lock:
            return list(self._pending_connections.keys())

    def is_connected_or_pending(self, onion: str) -> bool:
        """
        Checks if an onion address is currently tracked in any active session state.

        Args:
            onion (str): The target onion identity.

        Returns:
            bool: True if the connection exists.
        """
        with self._lock:
            return onion in self._connections or onion in self._pending_connections

    def is_live_active(self, onion: str) -> bool:
        """
        Checks whether a peer currently has an active live socket.

        Args:
            onion (str): The target onion identity.

        Returns:
            bool: True if the peer is fully connected.
        """
        with self._lock:
            return onion in self._connections

    def get_live_state(self, onion: str) -> LiveTransportState:
        """
        Derives the live transport lifecycle state for one peer.

        Args:
            onion (str): The target onion identity.

        Returns:
            LiveTransportState: The derived live state.
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
        Checks if an outbound connection attempt is currently in flight for the onion.

        Args:
            onion (str): The target onion identity.

        Returns:
            bool: True if an attempt is pending.
        """
        with self._lock:
            return onion in self._outbound_attempts

    def add_outbound_attempt(self, onion: str) -> None:
        """
        Registers a new outbound connection attempt.

        Args:
            onion (str): The target onion identity.

        Returns:
            None
        """
        with self._lock:
            self._outbound_attempts.add(onion)

    def discard_outbound_attempt(self, onion: str) -> None:
        """
        Cleans up a tracked outbound attempt safely.

        Args:
            onion (str): The target onion identity.

        Returns:
            None
        """
        with self._lock:
            self._outbound_attempts.discard(onion)
            self._outbound_sockets.pop(onion, None)

    def bind_outbound_socket(self, onion: str, conn: socket.socket) -> None:
        """
        Associates the current outbound attempt with its concrete socket instance.

        Args:
            onion (str): The target onion identity.
            conn (socket.socket): The in-flight outbound socket.

        Returns:
            None
        """
        with self._lock:
            self._outbound_attempts.add(onion)
            self._outbound_sockets[onion] = conn

    def is_current_outbound_socket(self, onion: str, sock: socket.socket) -> bool:
        """
        Checks whether a socket is the current tracked outbound attempt.

        Args:
            onion (str): The target onion identity.
            sock (socket.socket): The socket instance to compare.

        Returns:
            bool: True if the socket is the currently tracked outbound attempt.
        """
        with self._lock:
            return self._outbound_sockets.get(onion) == sock

    def add_active_connection(self, onion: str, conn: socket.socket) -> None:
        """
        Registers a fully authenticated, live socket connection.

        Args:
            onion (str): The peer's onion identity.
            conn (socket.socket): The established socket.

        Returns:
            None
        """
        with self._lock:
            self._connections[onion] = conn
            self._outbound_attempts.discard(onion)
            self._outbound_sockets.pop(onion, None)
            if onion in self._pending_connections:
                self._pending_connections.pop(onion)
            self._pending_connection_reasons.pop(onion, None)
            self._initial_buffers.pop(onion, None)

    def add_pending_connection(
        self,
        onion: str,
        conn: socket.socket,
        initial_buffer: str,
        reason: PendingConnectionReason = PendingConnectionReason.USER_ACCEPT,
    ) -> None:
        """
        Registers a socket connection awaiting local user acceptance.

        Args:
            onion (str): The peer's onion identity.
            conn (socket.socket): The pending socket.
            initial_buffer (str): Any leftover stream data after the handshake.
            reason (PendingConnectionReason): The internal reason for the pending state.

        Returns:
            None
        """
        with self._lock:
            self._pending_connections[onion] = conn
            self._initial_buffers[onion] = initial_buffer
            self._pending_connection_reasons[onion] = reason
            self._outbound_attempts.discard(onion)
            self._outbound_sockets.pop(onion, None)

    def pop_pending_connection(
        self, onion: str
    ) -> Tuple[Optional[socket.socket], str, Optional[PendingConnectionReason]]:
        """
        Retrieves and removes a pending connection for acceptance processing.

        Args:
            onion (str): The target onion identity.

        Returns:
            Tuple[Optional[socket.socket], str, Optional[PendingConnectionReason]]: The socket (if found), its buffer, and the pending reason.
        """
        with self._lock:
            conn: Optional[socket.socket] = self._pending_connections.pop(onion, None)
            buf: str = self._initial_buffers.pop(onion, '')
            reason: Optional[PendingConnectionReason] = (
                self._pending_connection_reasons.pop(onion, None)
            )
            return conn, buf, reason

    def get_pending_connection_reason(
        self, onion: str
    ) -> Optional[PendingConnectionReason]:
        """
        Returns the internal reason for one pending inbound connection.

        Args:
            onion (str): The target onion identity.

        Returns:
            Optional[PendingConnectionReason]: The pending reason if tracked.
        """
        with self._lock:
            return self._pending_connection_reasons.get(onion)

    def set_pending_connection_reason(
        self, onion: str, reason: PendingConnectionReason
    ) -> bool:
        """
        Updates the internal reason for one pending inbound connection.

        Args:
            onion (str): The target onion identity.
            reason (PendingConnectionReason): The new reason.

        Returns:
            bool: True if the pending entry exists and was updated.
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
        Returns all pending onions with one specific internal reason.

        Args:
            reason (PendingConnectionReason): The reason to filter by.

        Returns:
            List[str]: Matching pending onion identities.
        """
        with self._lock:
            return [
                onion
                for onion, pending_reason in self._pending_connection_reasons.items()
                if pending_reason is reason and onion in self._pending_connections
            ]

    def is_pending_socket(self, onion: str, sock: socket.socket) -> bool:
        """
        Checks whether a socket is the currently tracked pending connection.

        Args:
            onion (str): The target onion identity.
            sock (socket.socket): The socket instance to compare.

        Returns:
            bool: True if the socket is the current pending entry.
        """
        with self._lock:
            return self._pending_connections.get(onion) == sock

    def remove_pending_connection_if_socket(
        self, onion: str, sock: socket.socket
    ) -> bool:
        """
        Removes a pending connection only if the tracked socket still matches.

        Args:
            onion (str): The target onion identity.
            sock (socket.socket): The socket expected to be pending.

        Returns:
            bool: True if the pending connection was removed.
        """
        with self._lock:
            if self._pending_connections.get(onion) != sock:
                return False

            self._pending_connections.pop(onion, None)
            self._initial_buffers.pop(onion, None)
            self._pending_connection_reasons.pop(onion, None)
            return True

    def get_connection(self, onion: str) -> Optional[socket.socket]:
        """
        Retrieves a fully active socket connection without removing it.

        Args:
            onion (str): The target onion identity.

        Returns:
            Optional[socket.socket]: The socket connection if found.
        """
        with self._lock:
            return self._connections.get(onion)

    def pop_any_connection(self, onion: str) -> Optional[socket.socket]:
        """
        Removes and returns any tracked socket connection (active or pending) for teardown.
        Also cleans up associated RAM buffers.

        Args:
            onion (str): The target onion identity.

        Returns:
            Optional[socket.socket]: The removed socket if found.
        """
        with self._lock:
            conn: Optional[socket.socket] = self._connections.pop(
                onion, None
            ) or self._pending_connections.pop(onion, None)
            self._outbound_sockets.pop(onion, None)
            self._initial_buffers.pop(onion, None)
            self._pending_connection_reasons.pop(onion, None)
            self._ram_buffers.pop(onion, None)
            return conn

    def pop_unacked_messages(self, onion: str) -> Dict[str, Tuple[str, str]]:
        """
        Retrieves and removes all pending un-ACKed messages for a disconnected peer.

        Args:
            onion (str): The target onion identity.

        Returns:
            Dict[str, Tuple[str, str]]: Mapping of message IDs to payload and timestamp.
        """
        with self._lock:
            return self._unacked_messages.pop(onion, {})

    def add_unacked_message(
        self, onion: str, msg_id: str, msg: str, timestamp: str
    ) -> None:
        """
        Tracks a sent message awaiting an ACK from the peer.

        Args:
            onion (str): The peer's onion identity.
            msg_id (str): The unique message identifier.
            msg (str): The message payload.
            timestamp (str): The daemon-authored message timestamp.

        Returns:
            None
        """
        with self._lock:
            self._unacked_messages.setdefault(onion, {})[msg_id] = (msg, timestamp)

    def remove_unacked_message(
        self, onion: str, msg_id: str
    ) -> Optional[Tuple[str, str]]:
        """
        Removes a message from the un-ACKed queue once confirmation is received.

        Args:
            onion (str): The peer's onion identity.
            msg_id (str): The unique message identifier.

        Returns:
            Optional[Tuple[str, str]]: The removed payload and timestamp, if found.
        """
        with self._lock:
            if onion in self._unacked_messages:
                return self._unacked_messages[onion].pop(msg_id, None)
            return None

    def pop_ram_buffer(self, onion: str) -> List[Tuple[str, str, str]]:
        """
        Retrieves and removes the headless RAM buffer containing unseen messages.

        Args:
            onion (str): The peer's onion identity.

        Returns:
            List[Tuple[str, str, str]]: A list of (msg_id, content, timestamp) tuples.
        """
        with self._lock:
            return self._ram_buffers.pop(onion, [])

    def push_ram_buffer(
        self, onion: str, msg_id: str, content: str, timestamp: str = ''
    ) -> int:
        """
        Adds a newly received message to the headless RAM buffer for deferred display.

        Args:
            onion (str): The peer's onion identity.
            msg_id (str): The unique message identifier.
            content (str): The message payload.
            timestamp (str): The sender timestamp carried with the message.

        Returns:
            int: The current size of the RAM buffer.
        """
        with self._lock:
            if onion not in self._ram_buffers:
                self._ram_buffers[onion] = []
            self._ram_buffers[onion].append((msg_id, content, timestamp))
            return len(self._ram_buffers[onion])

    def remember_live_msg_id(self, onion: str, msg_id: str) -> bool:
        """
        Tracks one inbound live message ID to suppress duplicate UI delivery.

        Args:
            onion (str): The peer's onion identity.
            msg_id (str): The inbound live message identifier.

        Returns:
            bool: True if the message ID was new, False if it was already seen.
        """
        with self._lock:
            cache: List[str] = self._recent_live_msg_ids.setdefault(onion, [])
            if msg_id in cache:
                return False

            cache.append(msg_id)
            if len(cache) > Constants.LIVE_MSG_DEDUPE_CACHE_SIZE:
                cache.pop(0)

            return True

    def is_known_socket(self, onion: str, sock: socket.socket) -> bool:
        """
        Checks if a specific socket instance is actively tracked to prevent closing newer sessions.

        Args:
            onion (str): The peer's onion identity.
            sock (socket.socket): The specific socket object.

        Returns:
            bool: True if the socket is actively managed.
        """
        with self._lock:
            return (
                self._connections.get(onion) == sock
                or self._pending_connections.get(onion) == sock
            )

    def add_unauthenticated_connection(self, conn: socket.socket) -> None:
        """
        Tracks a raw socket before the handshake is completed.

        Args:
            conn (socket.socket): The raw unauthenticated socket.

        Returns:
            None
        """
        with self._lock:
            self._unauthenticated_connections.add(conn)

    def remove_unauthenticated_connection(self, conn: socket.socket) -> None:
        """
        Removes a raw socket from the unauthenticated tracking set.

        Args:
            conn (socket.socket): The socket to remove.

        Returns:
            None
        """
        with self._lock:
            self._unauthenticated_connections.discard(conn)

    def get_unauthenticated_count(self) -> int:
        """
        Retrieves the current number of unauthenticated connections.

        Args:
            None

        Returns:
            int: The count of unauthenticated sockets.
        """
        with self._lock:
            return len(self._unauthenticated_connections)

    # --- UI Focus Management for Persistent Drop Tunnels ---

    def add_ui_focus(self, onion: str) -> None:
        """
        Increments the reference count of UI clients focusing on a specific peer.

        Args:
            onion (str): The focused onion identity.

        Returns:
            None
        """
        with self._lock:
            self._ui_focus_counts[onion] = self._ui_focus_counts.get(onion, 0) + 1

    def get_focus_count(self, onion: str) -> int:
        """
        Returns the current number of UI clients focusing one peer.

        Args:
            onion (str): The target onion identity.

        Returns:
            int: The focus reference count.
        """
        with self._lock:
            return self._ui_focus_counts.get(onion, 0)

    def remove_ui_focus(self, onion: str) -> None:
        """
        Decrements the reference count of UI clients focusing on a specific peer.

        Args:
            onion (str): The unfocused onion identity.

        Returns:
            None
        """
        with self._lock:
            if onion in self._ui_focus_counts:
                self._ui_focus_counts[onion] -= 1
                if self._ui_focus_counts[onion] <= 0:
                    del self._ui_focus_counts[onion]

    def is_focused_by_ui(self, onion: str) -> bool:
        """
        Checks if any connected UI client currently has focus on the specified peer.

        Args:
            onion (str): The target onion identity.

        Returns:
            bool: True if at least one client is focusing the peer.
        """
        with self._lock:
            return self._ui_focus_counts.get(onion, 0) > 0

    def mark_drop_tunnel_open(
        self, onion: str, opened_at: Optional[float] = None
    ) -> None:
        """
        Marks a cached drop tunnel as active for one peer.

        Args:
            onion (str): The target onion identity.
            opened_at (Optional[float]): Optional timestamp override.

        Returns:
            None
        """
        timestamp: float = opened_at if opened_at is not None else time.time()
        with self._lock:
            self._drop_tunnels[onion] = DropTunnelState(
                opened_at=timestamp,
                last_used_at=timestamp,
            )

    def touch_drop_tunnel(self, onion: str, touched_at: Optional[float] = None) -> None:
        """
        Updates the last-used timestamp for a cached drop tunnel.

        Args:
            onion (str): The target onion identity.
            touched_at (Optional[float]): Optional timestamp override.

        Returns:
            None
        """
        timestamp: float = touched_at if touched_at is not None else time.time()
        with self._lock:
            tunnel: Optional[DropTunnelState] = self._drop_tunnels.get(onion)
            if not tunnel:
                self._drop_tunnels[onion] = DropTunnelState(
                    opened_at=timestamp,
                    last_used_at=timestamp,
                )
                return

            self._drop_tunnels[onion] = DropTunnelState(
                opened_at=tunnel.opened_at,
                last_used_at=timestamp,
            )

    def clear_drop_tunnel(self, onion: str) -> None:
        """
        Removes cached drop tunnel metadata for one peer.

        Args:
            onion (str): The target onion identity.

        Returns:
            None
        """
        with self._lock:
            self._drop_tunnels.pop(onion, None)

    def has_drop_tunnel(self, onion: str) -> bool:
        """
        Checks whether a cached drop tunnel exists for one peer.

        Args:
            onion (str): The target onion identity.

        Returns:
            bool: True if a cached drop tunnel exists.
        """
        with self._lock:
            return onion in self._drop_tunnels

    def get_drop_tunnel_state(self, onion: str) -> Optional[DropTunnelState]:
        """
        Returns the cached drop tunnel metadata for one peer.

        Args:
            onion (str): The target onion identity.

        Returns:
            Optional[DropTunnelState]: The cached tunnel metadata if present.
        """
        with self._lock:
            return self._drop_tunnels.get(onion)

    def get_primary_transport(
        self, onion: str, standby_drop_allowed: bool = False
    ) -> PrimaryTransport:
        """
        Derives the primary transport for one peer.

        Args:
            onion (str): The target onion identity.
            standby_drop_allowed (bool): Whether drop standby is enabled while live exists.

        Returns:
            PrimaryTransport: The derived primary transport.
        """
        live_state: LiveTransportState = self.get_live_state(onion)
        if live_state is not LiveTransportState.DISCONNECTED:
            return PrimaryTransport.LIVE

        if self.has_drop_tunnel(onion):
            return PrimaryTransport.DROP

        return PrimaryTransport.NONE

    def get_peer_transport_state(
        self, onion: str, standby_drop_allowed: bool = False
    ) -> PeerTransportState:
        """
        Returns a derived peer transport snapshot.

        Args:
            onion (str): The target onion identity.
            standby_drop_allowed (bool): Whether drop standby is enabled while live exists.

        Returns:
            PeerTransportState: The derived snapshot.
        """
        return PeerTransportState(
            onion=onion,
            live_state=self.get_live_state(onion),
            primary_transport=self.get_primary_transport(
                onion,
                standby_drop_allowed=standby_drop_allowed,
            ),
            has_drop_tunnel=self.has_drop_tunnel(onion),
            focus_count=self.get_focus_count(onion),
            standby_drop_allowed=standby_drop_allowed,
            is_retunneling=self.is_retunneling(onion),
        )

    def mark_live_reconnect_grace(self, onion: str, grace_timeout_sec: float) -> None:
        """
        Marks a peer as eligible for a short incoming auto-accept reconnect window.

        Args:
            onion (str): The remote onion identity.
            grace_timeout_sec (float): Grace duration in seconds, where 0 disables grace.

        Returns:
            None
        """
        with self._lock:
            if grace_timeout_sec <= 0:
                self._live_reconnect_grace.pop(onion, None)
                return

            self._live_reconnect_grace[onion] = time.time() + grace_timeout_sec

    def consume_live_reconnect_grace(self, onion: str) -> bool:
        """
        Consumes an incoming reconnect grace window if it is still valid.

        Args:
            onion (str): The remote onion identity.

        Returns:
            bool: True if the reconnect should be auto-accepted.
        """
        with self._lock:
            expires_at: Optional[float] = self._live_reconnect_grace.get(onion)
            if expires_at is None:
                return False

            if expires_at < time.time():
                del self._live_reconnect_grace[onion]
                return False

            del self._live_reconnect_grace[onion]
            return True

    def has_live_reconnect_grace(self, onion: str) -> bool:
        """
        Checks whether an inbound reconnect grace window is still valid.

        Args:
            onion (str): The remote onion identity.

        Returns:
            bool: True if the reconnect should still be auto-accepted.
        """
        with self._lock:
            expires_at: Optional[float] = self._live_reconnect_grace.get(onion)
            if expires_at is None:
                return False

            if expires_at < time.time():
                del self._live_reconnect_grace[onion]
                return False

            return True

    def mark_retunnel_reconnect(self, onion: str) -> None:
        """
        Marks that the next successful connection should finalize a retunnel flow.

        Args:
            onion (str): The remote onion identity.

        Returns:
            None
        """
        with self._lock:
            self._retunnel_reconnects.add(onion)

    def mark_retunnel_started(self, onion: str) -> None:
        """
        Marks a peer as currently executing a retunnel flow.

        Args:
            onion (str): The remote onion identity.

        Returns:
            None
        """
        with self._lock:
            self._retunnel_in_progress.add(onion)

    def is_retunneling(self, onion: str) -> bool:
        """
        Checks whether a peer is currently inside a retunnel flow.

        Args:
            onion (str): The remote onion identity.

        Returns:
            bool: True if the peer is retunneling.
        """
        with self._lock:
            return onion in self._retunnel_in_progress

    def consume_retunnel_reconnect(self, onion: str) -> bool:
        """
        Consumes a pending retunnel completion marker.

        Args:
            onion (str): The remote onion identity.

        Returns:
            bool: True if the connection finalizes a retunnel.
        """
        with self._lock:
            if onion not in self._retunnel_reconnects:
                return False
            self._retunnel_reconnects.discard(onion)
            return True

    def discard_retunnel_reconnect(self, onion: str) -> None:
        """
        Clears a pending retunnel completion marker.

        Args:
            onion (str): The remote onion identity.

        Returns:
            None
        """
        with self._lock:
            self._retunnel_reconnects.discard(onion)

    def clear_retunnel_flow(self, onion: str) -> None:
        """
        Clears all retunnel markers for one peer.

        Args:
            onion (str): The remote onion identity.

        Returns:
            None
        """
        with self._lock:
            self._retunnel_reconnects.discard(onion)
            self._retunnel_in_progress.discard(onion)
