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
    _unacked_messages: Dict[str, Dict[str, Tuple[str, str]]]
    _recent_live_msg_ids: Dict[str, List[str]]
    _unauthenticated_connections: Set[socket.socket]

    def pop_unacked_messages(self, onion: str) -> Dict[str, Tuple[str, str]]:
        """Retrieves and removes all pending unacked messages for one peer."""
        with self._lock:
            return self._unacked_messages.pop(onion, {})

    def add_unacked_message(
        self, onion: str, msg_id: str, msg: str, timestamp: str
    ) -> None:
        """Tracks a sent message awaiting an ACK from the peer."""
        with self._lock:
            self._unacked_messages.setdefault(onion, {})[msg_id] = (msg, timestamp)

    def remove_unacked_message(
        self, onion: str, msg_id: str
    ) -> Optional[Tuple[str, str]]:
        """Removes a message from the unacked queue once confirmation is received."""
        with self._lock:
            if onion in self._unacked_messages:
                return self._unacked_messages[onion].pop(msg_id, None)
            return None

    def remember_live_msg_id(self, onion: str, msg_id: str) -> bool:
        """Tracks one inbound live message ID to suppress duplicate UI delivery."""
        with self._lock:
            cache: List[str] = self._recent_live_msg_ids.setdefault(onion, [])
            if msg_id in cache:
                return False

            cache.append(msg_id)
            if len(cache) > Constants.LIVE_MSG_DEDUPE_CACHE_SIZE:
                cache.pop(0)

            return True

    def is_known_socket(self, onion: str, sock: socket.socket) -> bool:
        """Checks if a specific socket instance is actively tracked."""
        with self._lock:
            return (
                self._connections.get(onion) == sock
                or self._pending_connections.get(onion) == sock
            )

    def add_unauthenticated_connection(self, conn: socket.socket) -> None:
        """Tracks a raw socket before the handshake is completed."""
        with self._lock:
            self._unauthenticated_connections.add(conn)

    def remove_unauthenticated_connection(self, conn: socket.socket) -> None:
        """Removes a raw socket from the unauthenticated tracking set."""
        with self._lock:
            self._unauthenticated_connections.discard(conn)

    def get_unauthenticated_count(self) -> int:
        """Retrieves the current number of unauthenticated connections."""
        with self._lock:
            return len(self._unauthenticated_connections)
