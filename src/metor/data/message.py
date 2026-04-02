"""
Module for managing persisted inbound and outbound message state via SQLite.
Enforces consume-time payload shredding policies, stable message identities,
and transport-safe deduplication across live and drop delivery paths.
Yields raw domain models without applying CLI format dependencies.
"""

from dataclasses import dataclass
import secrets
from enum import Enum
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Optional

from metor.core.api import EventType
from metor.utils import Constants, clean_onion

# Local Package Imports
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager, SqlParam
from metor.data.settings import SettingKey


class MessageStatus(str, Enum):
    """
    Represents the delivery and consume status of a persisted message.
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
    """Represents the transport role of a persisted message payload."""

    TEXT = 'text'
    DROP_TEXT = 'drop_text'
    LIVE_TEXT = 'live_text'


@dataclass(frozen=True)
class QueuedMessageResult:
    """Represents the result of a message queue operation."""

    row_id: int
    was_duplicate: bool = False


class MessageManager:
    """Manages the persistence of asynchronous messages (inbox and outbox)."""

    _DROP_VISIBLE_TYPES: tuple[str, str] = (
        MessageType.TEXT.value,
        MessageType.DROP_TEXT.value,
    )

    _DROP_VISIBLE_PLACEHOLDERS: str = ', '.join('?' for _ in _DROP_VISIBLE_TYPES)

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
        self._db_path: Path = self._pm.paths.get_db_file()
        self._sql: SqlManager = SqlManager(self._db_path, self._pm.config, password)
        self._initialize_table()

    def _initialize_table(self) -> None:
        """
        Creates the 'messages' table if it does not already exist.
        Enforces a unique inbound message identity per peer.

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
        self._sql.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_inbound_msg_id
            ON messages (contact_onion, msg_id)
            WHERE direction = 'in' AND msg_id IS NOT NULL
            """
        )

    def queue_message(
        self,
        contact_onion: str,
        direction: MessageDirection,
        msg_type: MessageType,
        payload: str,
        status: MessageStatus,
        msg_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> QueuedMessageResult:
        """
        Inserts a new message into the database securely.
        Enforces atomic deduplication for incoming drops utilizing the network UUID.

        Args:
            contact_onion (str): The onion address of the remote peer.
            direction (MessageDirection): Whether the message is inbound or outbound.
            msg_type (MessageType): The type of payload (e.g., text or voice).
            payload (str): The actual message content or file path.
            status (MessageStatus): The initial status of the message.
            msg_id (Optional[str]): Network UUID. Generated if missing.
            timestamp (Optional[str]): Network ISO timestamp. Generated if missing.

        Returns:
            QueuedMessageResult: The inserted row ID and duplicate flag.
        """
        contact_onion = clean_onion(contact_onion)
        actual_msg_id: str = (
            msg_id if msg_id else secrets.token_hex(Constants.UUID_MSG_BYTES)
        )

        ts: str = timestamp if timestamp else datetime.now(timezone.utc).isoformat()

        insert_query: str = """
            INSERT INTO messages (msg_id, contact_onion, direction, msg_type, payload, timestamp, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params: Tuple[SqlParam, ...] = (
            actual_msg_id,
            contact_onion,
            direction.value,
            msg_type.value,
            payload,
            ts,
            status.value,
        )

        if direction is MessageDirection.IN:
            inbound_query: str = insert_query.replace('INSERT', 'INSERT OR IGNORE', 1)
            self._sql.execute(inbound_query, params)

            change_rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
                'SELECT changes()'
            )
            was_duplicate: bool = bool(
                change_rows and int(str(change_rows[0][0] or 0)) == 0
            )
            result_rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
                'SELECT id FROM messages WHERE contact_onion = ? AND direction = ? AND msg_id = ?',
                (contact_onion, direction.value, actual_msg_id),
            )
            row_id: int = (
                int(str(result_rows[0][0])) if result_rows and result_rows[0][0] else 0
            )
            return QueuedMessageResult(row_id=row_id, was_duplicate=was_duplicate)

        self._sql.execute(insert_query, params)
        result_rows = self._sql.fetchall('SELECT last_insert_rowid()')
        row_id = int(str(result_rows[0][0])) if result_rows and result_rows[0][0] else 0
        return QueuedMessageResult(row_id=row_id)

    def has_inbound_message(self, contact_onion: str, msg_id: str) -> bool:
        """
        Checks whether one inbound logical message already exists durably.

        Args:
            contact_onion (str): The remote onion identity.
            msg_id (str): The stable logical message identifier.

        Returns:
            bool: True if a matching inbound row already exists.
        """
        query: str = (
            'SELECT 1 FROM messages '
            'WHERE contact_onion = ? AND direction = ? AND msg_id = ? LIMIT 1'
        )
        rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            query,
            (
                clean_onion(contact_onion),
                MessageDirection.IN.value,
                msg_id,
            ),
        )
        return bool(rows)

    def get_unread_live_count(self, contact_onion: str) -> int:
        """
        Counts crash-safe inbound live messages that still await explicit consume.

        Args:
            contact_onion (str): The remote onion identity.

        Returns:
            int: The unread inbound live-message backlog for the peer.
        """
        query: str = (
            'SELECT COUNT(*) FROM messages '
            'WHERE contact_onion = ? AND direction = ? AND msg_type = ? AND status = ?'
        )
        rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            query,
            (
                clean_onion(contact_onion),
                MessageDirection.IN.value,
                MessageType.LIVE_TEXT.value,
                MessageStatus.UNREAD.value,
            ),
        )
        return int(str(rows[0][0])) if rows and rows[0][0] is not None else 0

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
            f'FROM messages WHERE direction = ? AND status = ? AND msg_type IN ({self._DROP_VISIBLE_PLACEHOLDERS}) '
            'ORDER BY id ASC'
        )
        rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            query,
            (
                MessageDirection.OUT.value,
                MessageStatus.PENDING.value,
                *self._DROP_VISIBLE_TYPES,
            ),
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
        query: str = (
            'SELECT contact_onion, COUNT(*) FROM messages '
            'WHERE direction = ? AND status = ? GROUP BY contact_onion'
        )
        rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            query,
            (
                MessageDirection.IN.value,
                MessageStatus.UNREAD.value,
            ),
        )

        counts: Dict[str, int] = {}
        for row in rows:
            onion, count = str(row[0]), int(str(row[1]))
            counts[onion] = count

        return counts

    def get_and_read_inbox(self, contact_onion: str) -> List[Tuple[int, str, str, str]]:
        """
        Retrieves all unread messages for a specific contact and executes the consume policy.
        Live payloads are always shredded on consume while preserving a dedupe tombstone.
        Drop payloads are shredded only when EPHEMERAL_MESSAGES is enabled.

        Args:
            contact_onion (str): The target onion address.

        Returns:
            List[Tuple[int, str, str, str]]: A list of message rows (id, msg_type, payload, timestamp).
        """
        query: str = """
            SELECT id, msg_type, payload, timestamp 
            FROM messages 
            WHERE contact_onion = ? AND direction = ? AND status = ?
            ORDER BY timestamp ASC
        """
        raw_messages: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            query,
            (
                clean_onion(contact_onion),
                MessageDirection.IN.value,
                MessageStatus.UNREAD.value,
            ),
        )
        messages: List[Tuple[int, str, str, str]] = [
            (int(str(r[0])), str(r[1]), str(r[2]), str(r[3])) for r in raw_messages
        ]

        if messages:
            live_scrub_query: str = (
                'UPDATE messages SET status = ?, payload = ? '
                'WHERE contact_onion = ? AND direction = ? AND status = ? AND msg_type = ?'
            )
            self._sql.execute(
                live_scrub_query,
                (
                    MessageStatus.READ.value,
                    '',
                    clean_onion(contact_onion),
                    MessageDirection.IN.value,
                    MessageStatus.UNREAD.value,
                    MessageType.LIVE_TEXT.value,
                ),
            )

            if self._pm.config.get_bool(SettingKey.EPHEMERAL_MESSAGES):
                shred_drop_query: str = (
                    'UPDATE messages SET status = ?, payload = ? '
                    f'WHERE contact_onion = ? AND direction = ? AND status = ? AND msg_type IN ({self._DROP_VISIBLE_PLACEHOLDERS})'
                )
                self._sql.execute(
                    shred_drop_query,
                    (
                        MessageStatus.READ.value,
                        '',
                        clean_onion(contact_onion),
                        MessageDirection.IN.value,
                        MessageStatus.UNREAD.value,
                        *self._DROP_VISIBLE_TYPES,
                    ),
                )
            else:
                update_query: str = (
                    'UPDATE messages SET status = ? '
                    f'WHERE contact_onion = ? AND direction = ? AND status = ? AND msg_type IN ({self._DROP_VISIBLE_PLACEHOLDERS})'
                )
                self._sql.execute(
                    update_query,
                    (
                        MessageStatus.READ.value,
                        clean_onion(contact_onion),
                        MessageDirection.IN.value,
                        MessageStatus.UNREAD.value,
                        *self._DROP_VISIBLE_TYPES,
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
            else self._pm.config.get_int(SettingKey.MESSAGES_LIMIT)
        )
        query: str = f"""
            SELECT direction, status, payload, timestamp 
            FROM messages 
            WHERE contact_onion = ?
              AND payload != ''
              AND msg_type IN ({self._DROP_VISIBLE_PLACEHOLDERS})
            ORDER BY timestamp DESC
            LIMIT ?
        """
        rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            query,
            (
                clean_onion(contact_onion),
                *self._DROP_VISIBLE_TYPES,
                actual_limit,
            ),
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
    ) -> Tuple[bool, EventType, Dict[str, str]]:
        """
        Wipes the message table completely or just for a specific contact.
        Maintains domain boundaries by leaving contact deletion to the Daemon orchestrator.

        Args:
            onion (Optional[str]): The target onion identity. If None, deletes globally based on flags.
            non_contacts_only (bool): If True, only deletes messages from unsaved peers.

        Returns:
            Tuple[bool, EventType, Dict[str, str]]: A success flag, strict event type, and payload.
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
                        EventType.MESSAGES_CLEARED_NON_CONTACTS,
                        {'target': onion},
                    )
                else:
                    delete_all_query: str = """
                        DELETE FROM messages 
                        WHERE contact_onion NOT IN (SELECT onion FROM contacts WHERE is_saved = 1)
                    """
                    self._sql.execute(delete_all_query)
                    return (
                        True,
                        EventType.MESSAGES_CLEARED_NON_CONTACTS_ALL,
                        {'profile': self._pm.profile_name},
                    )
            else:
                if onion:
                    self._sql.execute(
                        'DELETE FROM messages WHERE contact_onion = ?', (onion,)
                    )
                    return True, EventType.MESSAGES_CLEARED, {'target': onion}
                else:
                    self._sql.execute('DELETE FROM messages')
                    return (
                        True,
                        EventType.MESSAGES_CLEARED_ALL,
                        {'profile': self._pm.profile_name},
                    )

        except Exception:
            return False, EventType.MESSAGES_CLEAR_FAILED, {}
