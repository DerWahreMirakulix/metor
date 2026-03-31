"""
Module for managing asynchronous offline messages via SQLite.
Enforces Ephemeral Messaging policies (Burn-After-Read) and strict Enums.
Utilizes UUIDs for message consistency and network deduplication.
Yields raw domain models without applying CLI format dependencies.
"""

import secrets
from enum import Enum
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Optional

from metor.core.api import DomainCode, DbCode
from metor.utils import Constants, clean_onion

# Local Package Imports
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager, SqlParam
from metor.data.settings import Settings, SettingKey


class MessageStatus(str, Enum):
    """
    Represents the exact delivery and read status of an async message.
    """

    PENDING = 'pending'
    DELIVERED = 'delivered'
    UNREAD = 'unread'
    READ = 'read'


class MessageDirection(str, Enum):
    """Represents the flow direction of a message."""

    IN = 'in'
    OUT = 'out'


class MessageType(str, Enum):
    """Represents the payload type of a message."""

    TEXT = 'text'


class MessageManager:
    """Manages the persistence of asynchronous messages (inbox and outbox)."""

    def __init__(self, pm: ProfileManager, password: Optional[str] = None) -> None:
        """
        Initializes the MessageManager and ensures the database table exists.

        Args:
            pm (ProfileManager): The profile manager instance for context.
            password (Optional[str]): The master password for SQLCipher encryption.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._db_path: Path = Path(self._pm.get_config_dir()) / Constants.DB_FILE
        self._sql: SqlManager = SqlManager(self._db_path, password)
        self._initialize_table()

    def _initialize_table(self) -> None:
        """
        Creates the 'messages' table if it does not already exist.
        Migrates legacy databases to include the msg_id column for UUID tracking.

        Args:
            None

        Returns:
            None
        """
        query: str = """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id TEXT,
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
        msg_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        """
        Inserts a new message into the database securely.
        Enforces deduplication for incoming drops utilizing the network UUID.

        Args:
            contact_onion (str): The onion address of the remote peer.
            direction (MessageDirection): Whether the message is inbound or outbound.
            msg_type (MessageType): The type of payload (e.g., text or voice).
            payload (str): The actual message content or file path.
            status (MessageStatus): The initial status of the message.
            msg_id (Optional[str]): Network UUID. Generated if missing.
            timestamp (Optional[str]): Network ISO timestamp. Generated if missing.

        Returns:
            int: The inserted row ID or existing row ID if deduplicated.
        """
        contact_onion = clean_onion(contact_onion)
        actual_msg_id: str = msg_id if msg_id else secrets.token_hex(8)

        # Deduplication check for inbound payloads to prevent At-Least-Once replication faults
        if direction == MessageDirection.IN and actual_msg_id:
            existing: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
                'SELECT id FROM messages WHERE msg_id = ? AND contact_onion = ?',
                (actual_msg_id, contact_onion),
            )
            if existing:
                return int(str(existing[0][0]))

        ts: str = timestamp if timestamp else datetime.now(timezone.utc).isoformat()

        query: str = """
            INSERT INTO messages (msg_id, contact_onion, direction, msg_type, payload, timestamp, status) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        self._sql.execute(
            query,
            (
                actual_msg_id,
                contact_onion,
                direction.value,
                msg_type.value,
                payload,
                ts,
                status.value,
            ),
        )

        id_query: str = 'SELECT MAX(id) FROM messages'
        result: List[Tuple[SqlParam, ...]] = self._sql.fetchall(id_query)
        return int(str(result[0][0])) if result and result[0][0] else 0

    def get_pending_outbox(self) -> List[Tuple[int, str, str, str, str, str]]:
        """
        Retrieves all outbound messages that are waiting to be delivered.
        Fetches UUIDs and timestamps to construct accurate JSON Envelopes.

        Args:
            None

        Returns:
            List[Tuple[int, str, str, str, str, str]]: A list of tuples (id, onion, type, payload, msg_id, timestamp).
        """
        query: str = (
            'SELECT id, contact_onion, msg_type, payload, msg_id, timestamp '
            'FROM messages WHERE status = ? ORDER BY id ASC'
        )
        rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            query, (MessageStatus.PENDING.value,)
        )
        return [
            (
                int(str(r[0])),
                str(r[1]),
                str(r[2]),
                str(r[3]),
                str(r[4] or ''),
                str(r[5] or ''),
            )
            for r in rows
        ]

    def update_message_status(self, msg_id: int, new_status: MessageStatus) -> None:
        """
        Updates the delivery or read status of a specific message via internal SQLite ID.

        Args:
            msg_id (int): The unique internal database ID of the message.
            new_status (MessageStatus): The new status to apply.

        Returns:
            None
        """
        query: str = 'UPDATE messages SET status = ? WHERE id = ?'
        self._sql.execute(query, (new_status.value, msg_id))

    def get_unread_counts(self) -> Dict[str, int]:
        """
        Retrieves a count of unread messages grouped by contact onion.

        Args:
            None

        Returns:
            Dict[str, int]: A dictionary mapping onion addresses to their unread message count.
        """
        query: str = 'SELECT contact_onion, COUNT(*) FROM messages WHERE status = ? GROUP BY contact_onion'
        rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            query, (MessageStatus.UNREAD.value,)
        )

        counts: Dict[str, int] = {}
        for row in rows:
            onion, count = str(row[0]), int(str(row[1]))
            counts[onion] = count

        return counts

    def get_and_read_inbox(self, contact_onion: str) -> List[Tuple[int, str, str, str]]:
        """
        Retrieves all unread messages for a specific contact and executes the read policy.
        If EPHEMERAL_MESSAGES is active, data is permanently erased instead of flagged as read.

        Args:
            contact_onion (str): The target onion address.

        Returns:
            List[Tuple[int, str, str, str]]: A list of message rows (id, msg_type, payload, timestamp).
        """
        query: str = """
            SELECT id, msg_type, payload, timestamp 
            FROM messages 
            WHERE contact_onion = ? AND status = ?
            ORDER BY timestamp ASC
        """
        raw_messages: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            query, (contact_onion, MessageStatus.UNREAD.value)
        )
        messages: List[Tuple[int, str, str, str]] = [
            (int(str(r[0])), str(r[1]), str(r[2]), str(r[3])) for r in raw_messages
        ]

        if messages:
            if Settings.get(SettingKey.EPHEMERAL_MESSAGES):
                delete_query: str = (
                    'DELETE FROM messages WHERE contact_onion = ? AND status = ?'
                )
                self._sql.execute(
                    delete_query,
                    (contact_onion, MessageStatus.UNREAD.value),
                )
            else:
                update_query: str = 'UPDATE messages SET status = ? WHERE contact_onion = ? AND status = ?'
                self._sql.execute(
                    update_query,
                    (
                        MessageStatus.READ.value,
                        contact_onion,
                        MessageStatus.UNREAD.value,
                    ),
                )

        return messages

    def get_chat_history(
        self, contact_onion: str, limit: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """
        Retrieves the past message history for a specific contact, ordered chronologically.

        Args:
            contact_onion (str): The target onion address.
            limit (Optional[int]): The maximum number of past messages to fetch. Defaults to None.

        Returns:
            List[Dict[str, str]]: A list of dictionaries containing formatted message data.
        """
        actual_limit: int = (
            limit
            if limit is not None
            else int(str(Settings.get(SettingKey.MESSAGES_LIMIT)))
        )
        query: str = """
            SELECT direction, status, payload, timestamp 
            FROM messages 
            WHERE contact_onion = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            query, (contact_onion, actual_limit)
        )
        rows.reverse()

        result: List[Dict[str, str]] = []
        for row in rows:
            direction, status, payload, timestamp = (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
            )
            result.append(
                {
                    'direction': direction,
                    'status': status,
                    'payload': payload,
                    'timestamp': timestamp,
                }
            )
        return result

    def clear_messages(
        self, onion: Optional[str] = None, non_contacts_only: bool = False
    ) -> Tuple[bool, DomainCode, Dict[str, str]]:
        """
        Wipes the message table completely or just for a specific contact.
        Maintains domain boundaries by leaving contact deletion to the Daemon orchestrator.

        Args:
            onion (Optional[str]): The target onion identity. If None, deletes globally based on flags.
            non_contacts_only (bool): If True, only deletes messages from unsaved peers.

        Returns:
            Tuple[bool, DomainCode, Dict[str, str]]: A success flag, domain state code, and parameters.
        """
        try:
            if non_contacts_only:
                if onion:
                    query: str = """
                        DELETE FROM messages 
                        WHERE contact_onion = ? 
                        AND contact_onion NOT IN (SELECT onion FROM contacts WHERE is_saved = 1)
                    """
                    self._sql.execute(query, (onion,))
                    return (
                        True,
                        DbCode.MESSAGES_CLEARED_NON_CONTACTS,
                        {'target': onion},
                    )
                else:
                    query: str = """
                        DELETE FROM messages 
                        WHERE contact_onion NOT IN (SELECT onion FROM contacts WHERE is_saved = 1)
                    """
                    self._sql.execute(query)
                    return (
                        True,
                        DbCode.MESSAGES_CLEARED_NON_CONTACTS,
                        {'target': self._pm.profile_name},
                    )
            else:
                if onion:
                    self._sql.execute(
                        'DELETE FROM messages WHERE contact_onion = ?', (onion,)
                    )
                    return True, DbCode.MESSAGES_CLEARED, {'target': onion}
                else:
                    self._sql.execute('DELETE FROM messages')
                    return (
                        True,
                        DbCode.MESSAGES_CLEARED_ALL,
                        {'profile': self._pm.profile_name},
                    )

        except Exception:
            return False, DbCode.MESSAGES_CLEAR_FAILED, {}
