"""Message, buffer, and unauthenticated socket state mixins."""

import socket
import threading
from typing import Dict, List, Optional, Set, Tuple

from metor.utils import Constants


class StateTrackerMessagesMixin:
    """Encapsulates in-flight message and raw socket state."""

    _lock: threading.Lock
    _connections: Dict[str, socket.socket]
    _pending_connections: Dict[str, socket.socket]
    _outbound_sockets: Dict[str, socket.socket]
    _unacked_messages: Dict[str, Dict[str, Tuple[str, str]]]
    _message_request_ids: Dict[str, str]
    _recent_live_msg_ids: Dict[str, List[str]]
    _unauthenticated_connections: Set[socket.socket]

    def remember_message_request_id(
        self,
        msg_id: str,
        request_id: Optional[str],
    ) -> None:
        """
        Remembers which IPC request created one logical outbound message.

        Args:
            msg_id (str): The logical message identifier.
            request_id (Optional[str]): The originating IPC request identifier.

        Returns:
            None
        """
        if request_id is None:
            return

        with self._lock:
            self._message_request_ids[msg_id] = request_id

    def pop_message_request_id(self, msg_id: str) -> Optional[str]:
        """
        Retrieves and removes the originating IPC request identifier for one message.

        Args:
            msg_id (str): The logical message identifier.

        Returns:
            Optional[str]: The originating request identifier, if one was tracked.
        """
        with self._lock:
            return self._message_request_ids.pop(msg_id, None)

    def clear_message_request_id(self, msg_id: str) -> None:
        """
        Removes any tracked originating request identifier for one message.

        Args:
            msg_id (str): The logical message identifier.

        Returns:
            None
        """
        with self._lock:
            self._message_request_ids.pop(msg_id, None)

    def pop_unacked_messages(self, onion: str) -> Dict[str, Tuple[str, str]]:
        """
        Retrieves and removes all currently unacknowledged messages for one peer.

        Args:
            onion (str): The peer onion identity.

        Returns:
            Dict[str, Tuple[str, str]]: Mapping of message IDs to payload and timestamp.
        """
        with self._lock:
            return self._unacked_messages.pop(onion, {})

    def add_unacked_message(
        self, onion: str, msg_id: str, msg: str, timestamp: str
    ) -> None:
        """
        Tracks one outbound message until the peer confirms it with an ACK.

        Args:
            onion (str): The peer onion identity.
            msg_id (str): The logical message identifier.
            msg (str): The message payload stored for fallback handling.
            timestamp (str): The daemon-authored send timestamp.

        Returns:
            None
        """
        with self._lock:
            self._unacked_messages.setdefault(onion, {})[msg_id] = (msg, timestamp)

    def remove_unacked_message(
        self, onion: str, msg_id: str
    ) -> Optional[Tuple[str, str]]:
        """
        Removes one message from the unacknowledged queue after confirmation.

        Args:
            onion (str): The peer onion identity.
            msg_id (str): The logical message identifier.

        Returns:
            Optional[Tuple[str, str]]: The stored payload and timestamp when found.
        """
        with self._lock:
            if onion in self._unacked_messages:
                return self._unacked_messages[onion].pop(msg_id, None)
            return None

    def remember_live_msg_id(self, onion: str, msg_id: str) -> bool:
        """
        Stores one inbound live message ID to suppress duplicate processing.

        Args:
            onion (str): The peer onion identity.
            msg_id (str): The logical message identifier.

        Returns:
            bool: True if the ID was newly recorded, False if it was already known.
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
        Checks whether one socket is still tracked as active or pending.

        Args:
            onion (str): The peer onion identity.
            sock (socket.socket): The socket instance to inspect.

        Returns:
            bool: True if the socket is currently tracked for the peer.
        """
        with self._lock:
            return (
                self._connections.get(onion) == sock
                or self._pending_connections.get(onion) == sock
            )

    def add_unauthenticated_connection(self, conn: socket.socket) -> None:
        """
        Tracks one raw socket before the handshake has completed.

        Args:
            conn (socket.socket): The unauthenticated socket instance.

        Returns:
            None
        """
        with self._lock:
            self._unauthenticated_connections.add(conn)

    def remove_unauthenticated_connection(self, conn: socket.socket) -> None:
        """
        Removes one raw socket from unauthenticated tracking.

        Args:
            conn (socket.socket): The unauthenticated socket instance.

        Returns:
            None
        """
        with self._lock:
            self._unauthenticated_connections.discard(conn)

    def get_unauthenticated_count(self) -> int:
        """
        Returns the current number of sockets awaiting handshake completion.

        Args:
            None

        Returns:
            int: The number of unauthenticated socket connections.
        """
        with self._lock:
            return len(self._unauthenticated_connections)

    def get_tracked_live_socket_count(self) -> int:
        """
        Returns the total number of live sockets currently tracked by the daemon.

        Args:
            None

        Returns:
            int: Active, pending, outbound, and unauthenticated live sockets.
        """
        with self._lock:
            return (
                len(self._connections)
                + len(self._pending_connections)
                + len(self._outbound_sockets)
                + len(self._unauthenticated_connections)
            )
