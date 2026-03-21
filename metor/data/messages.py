"""
Module for managing asynchronous offline messages (SMS/Voice) via SQLite.
Uses strict Enums to represent message states and types.
"""

import os
from enum import Enum
from typing import List, Tuple, Dict

from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.utils.constants import Constants


class MessageStatus(str, Enum):
    """Represents the delivery and read status of an async message."""

    PENDING = 'pending'
    SENT = 'sent'
    DELIVERED = 'delivered'
    UNREAD = 'unread'
    READ = 'read'
    FAILED = 'failed'


class MessageDirection(str, Enum):
    """Represents the flow direction of a message."""

    IN = 'in'
    OUT = 'out'


class MessageType(str, Enum):
    """Represents the payload type of a message."""

    TEXT = 'text'
    VOICE = 'voice'


class MessageManager:
    """Manages the persistence of asynchronous messages (inbox and outbox)."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the MessageManager and ensures the database table exists.

        Args:
            pm (ProfileManager): The profile manager instance for context.
        """
        self._pm: ProfileManager = pm
        self._db_path: str = os.path.join(self._pm.get_config_dir(), Constants.DB_FILE)
        self._sql: SqlManager = SqlManager(self._db_path)
        self._initialize_table()

    def _initialize_table(self) -> None:
        """
        Creates the 'messages' table if it does not already exist.

        Returns:
            None
        """
        query: str = """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_onion TEXT NOT NULL,
                direction TEXT NOT NULL,
                msg_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL
            )
        """
        self._sql.execute(query)

    def queue_message(
        self,
        contact_onion: str,
        direction: MessageDirection,
        msg_type: MessageType,
        payload: str,
        status: MessageStatus,
    ) -> int:
        """
        Inserts a new message into the database.

        Args:
            contact_onion (str): The onion address of the remote peer.
            direction (MessageDirection): Whether the message is inbound or outbound.
            msg_type (MessageType): The type of payload (e.g., text or voice).
            payload (str): The actual message content or file path.
            status (MessageStatus): The initial status of the message.

        Returns:
            int: The inserted row ID.
        """
        query: str = """
            INSERT INTO messages (contact_onion, direction, msg_type, payload, status) 
            VALUES (?, ?, ?, ?, ?)
        """
        self._sql.execute(
            query,
            (contact_onion, direction.value, msg_type.value, payload, status.value),
        )

        id_query: str = 'SELECT MAX(id) FROM messages'
        result: List[Tuple] = self._sql.fetchall(id_query)
        return int(result[0][0]) if result and result[0][0] else 0

    def get_pending_outbox(self) -> List[Tuple]:
        """
        Retrieves all outbound messages that are waiting to be delivered.

        Returns:
            List[Tuple]: A list of database rows representing pending messages.
        """
        query: str = (
            'SELECT id, contact_onion, msg_type, payload FROM messages WHERE status = ?'
        )
        return self._sql.fetchall(query, (MessageStatus.PENDING.value,))

    def update_message_status(self, msg_id: int, new_status: MessageStatus) -> None:
        """
        Updates the delivery or read status of a specific message.

        Args:
            msg_id (int): The unique ID of the message.
            new_status (MessageStatus): The new status to apply.

        Returns:
            None
        """
        query: str = 'UPDATE messages SET status = ? WHERE id = ?'
        self._sql.execute(query, (new_status.value, msg_id))

    def get_unread_counts(self) -> Dict[str, int]:
        """
        Retrieves a count of unread messages grouped by contact onion.

        Returns:
            Dict[str, int]: A dictionary mapping onion addresses to their unread message count.
        """
        query: str = 'SELECT contact_onion, COUNT(*) FROM messages WHERE status = ? GROUP BY contact_onion'
        rows: List[Tuple] = self._sql.fetchall(query, (MessageStatus.UNREAD.value,))

        counts: Dict[str, int] = {}
        for row in rows:
            onion, count = row
            counts[onion] = int(count)

        return counts

    def get_and_read_inbox(self, contact_onion: str) -> List[Tuple]:
        """
        Retrieves all unread messages for a specific contact and marks them as read.

        Args:
            contact_onion (str): The target onion address.

        Returns:
            List[Tuple]: A list of message rows (id, msg_type, payload, timestamp).
        """
        query: str = """
            SELECT id, msg_type, payload, timestamp 
            FROM messages 
            WHERE contact_onion = ? AND status = ?
            ORDER BY timestamp ASC
        """
        messages: List[Tuple] = self._sql.fetchall(
            query, (contact_onion, MessageStatus.UNREAD.value)
        )

        if messages:
            update_query: str = (
                'UPDATE messages SET status = ? WHERE contact_onion = ? AND status = ?'
            )
            self._sql.execute(
                update_query,
                (MessageStatus.READ.value, contact_onion, MessageStatus.UNREAD.value),
            )

        return messages
