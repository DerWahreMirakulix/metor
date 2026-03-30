"""
Module for thread-safe network state tracking.
Enforces strict locking during dictionary mutations and iteration to prevent race conditions.
Implements Reference Counting to track IPC clients focusing on specific peers for Tunnel Keep-Alive logic.
"""

import socket
import threading
from typing import Dict, List, Optional, Set, Tuple


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
        self._outbound_attempts: Set[str] = set()
        self._initial_buffers: Dict[str, str] = {}
        self._unacked_messages: Dict[str, Dict[str, str]] = {}
        self._ram_buffers: Dict[str, List[Tuple[str, str]]] = {}

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
            if onion in self._pending_connections:
                self._pending_connections.pop(onion)

    def add_pending_connection(
        self, onion: str, conn: socket.socket, initial_buffer: str
    ) -> None:
        """
        Registers a socket connection awaiting local user acceptance.

        Args:
            onion (str): The peer's onion identity.
            conn (socket.socket): The pending socket.
            initial_buffer (str): Any leftover stream data after the handshake.

        Returns:
            None
        """
        with self._lock:
            self._pending_connections[onion] = conn
            self._initial_buffers[onion] = initial_buffer

    def pop_pending_connection(self, onion: str) -> Tuple[Optional[socket.socket], str]:
        """
        Retrieves and removes a pending connection for acceptance processing.

        Args:
            onion (str): The target onion identity.

        Returns:
            Tuple[Optional[socket.socket], str]: The socket (if found) and its buffer.
        """
        with self._lock:
            conn: Optional[socket.socket] = self._pending_connections.pop(onion, None)
            buf: str = self._initial_buffers.pop(onion, '')
            return conn, buf

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
            self._initial_buffers.pop(onion, None)
            self._ram_buffers.pop(onion, None)
            return conn

    def pop_unacked_messages(self, onion: str) -> Dict[str, str]:
        """
        Retrieves and removes all pending un-ACKed messages for a disconnected peer.

        Args:
            onion (str): The target onion identity.

        Returns:
            Dict[str, str]: Dictionary mapping message IDs to their payload content.
        """
        with self._lock:
            return self._unacked_messages.pop(onion, {})

    def add_unacked_message(self, onion: str, msg_id: str, msg: str) -> None:
        """
        Tracks a sent message awaiting an ACK from the peer.

        Args:
            onion (str): The peer's onion identity.
            msg_id (str): The unique message identifier.
            msg (str): The message payload.

        Returns:
            None
        """
        with self._lock:
            self._unacked_messages.setdefault(onion, {})[msg_id] = msg

    def remove_unacked_message(self, onion: str, msg_id: str) -> None:
        """
        Removes a message from the un-ACKed queue once confirmation is received.

        Args:
            onion (str): The peer's onion identity.
            msg_id (str): The unique message identifier.

        Returns:
            None
        """
        with self._lock:
            if onion in self._unacked_messages:
                self._unacked_messages[onion].pop(msg_id, None)

    def pop_ram_buffer(self, onion: str) -> List[Tuple[str, str]]:
        """
        Retrieves and removes the headless RAM buffer containing unseen messages.

        Args:
            onion (str): The peer's onion identity.

        Returns:
            List[Tuple[str, str]]: A list of (msg_id, content) tuples.
        """
        with self._lock:
            return self._ram_buffers.pop(onion, [])

    def push_ram_buffer(self, onion: str, msg_id: str, content: str) -> int:
        """
        Adds a newly received message to the headless RAM buffer for deferred display.

        Args:
            onion (str): The peer's onion identity.
            msg_id (str): The unique message identifier.
            content (str): The message payload.

        Returns:
            int: The current size of the RAM buffer.
        """
        with self._lock:
            if onion not in self._ram_buffers:
                self._ram_buffers[onion] = []
            self._ram_buffers[onion].append((msg_id, content))
            return len(self._ram_buffers[onion])

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
