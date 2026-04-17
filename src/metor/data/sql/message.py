"""Centralized durable message spool, archive, and receipt helpers."""

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, cast

from metor.utils import Constants, clean_onion
from metor.data.message.models import (
    MessageDirection,
    MessageStatus,
    MessageType,
    QueuedMessageResult,
    StoredMessageRecord,
)

# Local Package Imports
from metor.data.sql.backends import SqlCipherCursor, SqlParam

if TYPE_CHECKING:
    from metor.data.sql.manager import SqlManager


@dataclass(frozen=True)
class MessageReceiptRow:
    """Represents one persisted message receipt row."""

    receipt_id: int
    msg_id: str
    peer_onion: str
    direction: MessageDirection
    transport_kind: MessageType
    status: MessageStatus
    visible_in_history: bool
    created_at: str
    updated_at: str


class MessageRepository:
    """Centralized durable message spool, archive, and receipt helpers."""

    _DROP_VISIBLE_TYPES: tuple[str, str] = (
        MessageType.TEXT.value,
        MessageType.DROP_TEXT.value,
    )
    _DROP_VISIBLE_PLACEHOLDERS: str = ', '.join('?' for _ in _DROP_VISIBLE_TYPES)

    def __init__(self, sql: 'SqlManager') -> None:
        """
        Initializes the message repository.

        Args:
            sql (SqlManager): The owning SQL manager.

        Returns:
            None
        """
        self._sql: SqlManager = sql

    @staticmethod
    def _now() -> str:
        """
        Returns one UTC ISO timestamp.

        Args:
            None

        Returns:
            str: The timestamp string.
        """
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _placeholders(count: int) -> str:
        """
        Creates one SQL placeholder sequence.

        Args:
            count (int): The number of placeholders.

        Returns:
            str: The placeholder string.
        """
        return ', '.join('?' for _ in range(count))

    def _receipt_from_row(self, row: Tuple[SqlParam, ...]) -> MessageReceiptRow:
        """
        Casts one SQL row into one typed receipt row.

        Args:
            row (Tuple[SqlParam, ...]): The raw SQL row.

        Returns:
            MessageReceiptRow: The typed receipt row.
        """
        return MessageReceiptRow(
            receipt_id=int(str(row[0])),
            msg_id=str(row[1]),
            peer_onion=str(row[2]),
            direction=MessageDirection(str(row[3])),
            transport_kind=MessageType(str(row[4])),
            status=MessageStatus(str(row[5])),
            visible_in_history=int(str(row[6])) == 1,
            created_at=str(row[7]),
            updated_at=str(row[8]),
        )

    def _get_receipt(
        self,
        contact_onion: str,
        direction: MessageDirection,
        msg_id: str,
        cursor: Optional[SqlCipherCursor] = None,
    ) -> Optional[MessageReceiptRow]:
        """
        Retrieves one logical message receipt by stable identity.

        Args:
            contact_onion (str): The normalized peer onion.
            direction (MessageDirection): The message direction.
            msg_id (str): The stable message identifier.
            cursor (Optional[SqlCipherCursor]): Optional active transaction cursor.

        Returns:
            Optional[MessageReceiptRow]: The matching receipt, if present.
        """
        query = (
            'SELECT id, msg_id, peer_onion, direction, transport_kind, status, '
            'visible_in_history, created_at, updated_at '
            'FROM message_receipts WHERE peer_onion = ? AND direction = ? AND msg_id = ?'
        )
        if cursor is None:
            rows = self._sql.fetchall(query, (contact_onion, direction.value, msg_id))
        else:
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(
                    query,
                    (contact_onion, direction.value, msg_id),
                ).fetchall(),
            )
        if not rows:
            return None
        return self._receipt_from_row(rows[0])

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
        Stores one durable logical message across receipt, spool, and archive tables.

        Args:
            contact_onion (str): The peer onion identity.
            direction (MessageDirection): The message direction.
            msg_type (MessageType): The transport role of the payload.
            payload (str): The stored payload.
            status (MessageStatus): The persisted delivery state.
            msg_id (Optional[str]): The stable message identifier.
            timestamp (Optional[str]): The authored message timestamp.

        Returns:
            QueuedMessageResult: The stored receipt id and duplicate flag.
        """
        normalized_onion: str = clean_onion(contact_onion)
        actual_msg_id: str = (
            msg_id if msg_id else secrets.token_hex(Constants.UUID_MSG_BYTES)
        )
        created_at: str = timestamp if timestamp else self._now()
        visible_in_history: int = 1 if msg_type.value in self._DROP_VISIBLE_TYPES else 0

        with self._sql.transaction() as cursor:
            existing = self._get_receipt(
                normalized_onion,
                direction,
                actual_msg_id,
                cursor,
            )
            if existing is not None:
                if direction is MessageDirection.IN:
                    return QueuedMessageResult(existing.receipt_id, was_duplicate=True)

                updated_at: str = self._now()
                cursor.execute(
                    'UPDATE message_receipts '
                    'SET transport_kind = ?, status = ?, visible_in_history = ?, updated_at = ? '
                    'WHERE id = ?',
                    (
                        msg_type.value,
                        status.value,
                        visible_in_history,
                        updated_at,
                        existing.receipt_id,
                    ),
                )

                if visible_in_history == 1:
                    cursor.execute(
                        'INSERT INTO message_archive (receipt_id, payload) VALUES (?, ?) '
                        'ON CONFLICT(receipt_id) DO UPDATE SET payload = excluded.payload',
                        (existing.receipt_id, payload),
                    )
                else:
                    cursor.execute(
                        'DELETE FROM message_archive WHERE receipt_id = ?',
                        (existing.receipt_id,),
                    )

                if (
                    direction is MessageDirection.OUT
                    and status is MessageStatus.PENDING
                ):
                    cursor.execute(
                        'INSERT INTO outbox_spool (receipt_id, payload) VALUES (?, ?) '
                        'ON CONFLICT(receipt_id) DO UPDATE SET payload = excluded.payload',
                        (existing.receipt_id, payload),
                    )
                else:
                    cursor.execute(
                        'DELETE FROM outbox_spool WHERE receipt_id = ?',
                        (existing.receipt_id,),
                    )

                return QueuedMessageResult(existing.receipt_id)

            cursor.execute(
                'INSERT INTO message_receipts '
                '(msg_id, peer_onion, direction, transport_kind, status, visible_in_history, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    actual_msg_id,
                    normalized_onion,
                    direction.value,
                    msg_type.value,
                    status.value,
                    visible_in_history,
                    created_at,
                    created_at,
                ),
            )
            raw_receipt_id = cursor.execute('SELECT last_insert_rowid()').fetchall()[0][
                0
            ]
            receipt_id: int = int(str(raw_receipt_id))

            if direction is MessageDirection.IN:
                cursor.execute(
                    'INSERT INTO inbound_spool (receipt_id, payload) VALUES (?, ?)',
                    (receipt_id, payload),
                )

            if direction is MessageDirection.OUT and status is MessageStatus.PENDING:
                cursor.execute(
                    'INSERT INTO outbox_spool (receipt_id, payload) VALUES (?, ?)',
                    (receipt_id, payload),
                )

            if visible_in_history == 1:
                cursor.execute(
                    'INSERT INTO message_archive (receipt_id, payload) VALUES (?, ?)',
                    (receipt_id, payload),
                )

        return QueuedMessageResult(receipt_id)

    def has_inbound_message(self, contact_onion: str, msg_id: str) -> bool:
        """
        Checks whether one inbound logical message already exists durably.

        Args:
            contact_onion (str): The remote onion identity.
            msg_id (str): The stable logical message identifier.

        Returns:
            bool: True if a matching inbound row already exists.
        """
        return (
            self._get_receipt(
                clean_onion(contact_onion),
                MessageDirection.IN,
                msg_id,
            )
            is not None
        )

    def count_unread_by_type(self, contact_onion: str, msg_type: MessageType) -> int:
        """
        Counts unread inbound messages of one transport kind for one peer.

        Args:
            contact_onion (str): The remote onion identity.
            msg_type (MessageType): The message transport kind.

        Returns:
            int: The unread count.
        """
        rows = self._sql.fetchall(
            'SELECT COUNT(*) FROM message_receipts '
            'WHERE peer_onion = ? AND direction = ? AND transport_kind = ? AND status = ?',
            (
                clean_onion(contact_onion),
                MessageDirection.IN.value,
                msg_type.value,
                MessageStatus.UNREAD.value,
            ),
        )
        return int(str(rows[0][0])) if rows and rows[0][0] is not None else 0

    def get_pending_outbox(self) -> List[Tuple[int, str, str, str, str, str]]:
        """
        Retrieves the durable drop outbox queue.

        Args:
            None

        Returns:
            List[Tuple[int, str, str, str, str, str]]: Pending outbox rows.
        """
        query = (
            'SELECT r.id, r.peer_onion, r.transport_kind, o.payload, r.msg_id, r.created_at '
            'FROM message_receipts AS r '
            'INNER JOIN outbox_spool AS o ON o.receipt_id = r.id '
            f'WHERE r.direction = ? AND r.status = ? AND r.transport_kind IN ({self._DROP_VISIBLE_PLACEHOLDERS}) '
            'ORDER BY r.id ASC'
        )
        rows = self._sql.fetchall(
            query,
            (
                MessageDirection.OUT.value,
                MessageStatus.PENDING.value,
                *self._DROP_VISIBLE_TYPES,
            ),
        )
        return [
            (
                int(str(row[0])),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
            )
            for row in rows
        ]

    def update_message_status(self, receipt_id: int, new_status: MessageStatus) -> None:
        """
        Updates one persisted message status.

        Args:
            receipt_id (int): The durable receipt id.
            new_status (MessageStatus): The new status.

        Returns:
            None
        """
        with self._sql.transaction() as cursor:
            cursor.execute(
                'UPDATE message_receipts SET status = ?, updated_at = ? WHERE id = ?',
                (new_status.value, self._now(), receipt_id),
            )
            if new_status is not MessageStatus.PENDING:
                cursor.execute(
                    'DELETE FROM outbox_spool WHERE receipt_id = ?',
                    (receipt_id,),
                )

    def get_unread_counts(self) -> Dict[str, int]:
        """
        Returns unread inbound counts grouped by peer onion.

        Args:
            None

        Returns:
            Dict[str, int]: Unread counts per peer.
        """
        rows = self._sql.fetchall(
            'SELECT peer_onion, COUNT(*) FROM message_receipts '
            'WHERE direction = ? AND status = ? GROUP BY peer_onion',
            (
                MessageDirection.IN.value,
                MessageStatus.UNREAD.value,
            ),
        )
        return {str(row[0]): int(str(row[1])) for row in rows}

    def get_and_read_inbox(
        self,
        contact_onion: str,
        ephemeral_messages: bool,
    ) -> List[Tuple[int, str, str, str]]:
        """
        Retrieves unread inbox rows and applies consume semantics atomically.

        Args:
            contact_onion (str): The peer onion identity.
            ephemeral_messages (bool): Whether consumed drop payloads should be shredded.

        Returns:
            List[Tuple[int, str, str, str]]: The unread rows as receipt id, type, payload, timestamp.
        """
        normalized_onion: str = clean_onion(contact_onion)
        query = (
            'SELECT r.id, r.transport_kind, s.payload, r.created_at '
            'FROM message_receipts AS r '
            'INNER JOIN inbound_spool AS s ON s.receipt_id = r.id '
            'WHERE r.peer_onion = ? AND r.direction = ? AND r.status = ? '
            'ORDER BY r.created_at ASC, r.id ASC'
        )

        with self._sql.transaction() as cursor:
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(
                    query,
                    (
                        normalized_onion,
                        MessageDirection.IN.value,
                        MessageStatus.UNREAD.value,
                    ),
                ).fetchall(),
            )

            messages: List[Tuple[int, str, str, str]] = [
                (int(str(row[0])), str(row[1]), str(row[2]), str(row[3]))
                for row in rows
            ]
            if not messages:
                return messages

            receipt_ids: List[int] = [message[0] for message in messages]
            live_ids: List[int] = [
                message[0]
                for message in messages
                if message[1] == MessageType.LIVE_TEXT.value
            ]
            drop_visible_ids: List[int] = [
                message[0]
                for message in messages
                if message[1] in self._DROP_VISIBLE_TYPES
            ]

            placeholder_block = self._placeholders(len(receipt_ids))
            cursor.execute(
                f'UPDATE message_receipts SET status = ?, updated_at = ? WHERE id IN ({placeholder_block})',
                (
                    MessageStatus.READ.value,
                    self._now(),
                    *receipt_ids,
                ),
            )
            cursor.execute(
                f'DELETE FROM inbound_spool WHERE receipt_id IN ({placeholder_block})',
                tuple(receipt_ids),
            )

            if ephemeral_messages and drop_visible_ids:
                drop_block = self._placeholders(len(drop_visible_ids))
                cursor.execute(
                    f'DELETE FROM message_archive WHERE receipt_id IN ({drop_block})',
                    tuple(drop_visible_ids),
                )

            if live_ids:
                live_block = self._placeholders(len(live_ids))
                cursor.execute(
                    f'DELETE FROM message_archive WHERE receipt_id IN ({live_block})',
                    tuple(live_ids),
                )

        return messages

    def get_chat_history(
        self,
        contact_onion: str,
        limit: int,
    ) -> List[StoredMessageRecord]:
        """
        Retrieves visible chat history rows for one peer.

        Args:
            contact_onion (str): The peer onion identity.
            limit (int): The result limit.

        Returns:
            List[StoredMessageRecord]: Visible chat history rows ordered chronologically.
        """
        query = f"""
            SELECT r.direction, r.status, a.payload, r.created_at
            FROM message_receipts AS r
            INNER JOIN message_archive AS a ON a.receipt_id = r.id
            WHERE r.peer_onion = ?
              AND a.payload != ''
              AND r.transport_kind IN ({self._DROP_VISIBLE_PLACEHOLDERS})
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT ?
        """
        rows = self._sql.fetchall(
            query,
            (
                clean_onion(contact_onion),
                *self._DROP_VISIBLE_TYPES,
                limit,
            ),
        )
        rows.reverse()
        return [
            StoredMessageRecord(
                direction=str(row[0]),
                status=str(row[1]),
                payload=str(row[2]),
                timestamp=str(row[3]),
            )
            for row in rows
        ]

    def clear_messages(
        self,
        onion: Optional[str] = None,
        non_contacts_only: bool = False,
    ) -> None:
        """
        Clears durable message state according to the requested scope.

        Args:
            onion (Optional[str]): Optional peer onion filter.
            non_contacts_only (bool): Whether only discovered peers should be affected.

        Returns:
            None
        """
        if non_contacts_only:
            if onion:
                self._sql.execute(
                    'DELETE FROM message_receipts '
                    "WHERE peer_onion = ? AND peer_onion NOT IN (SELECT onion FROM peers WHERE alias_state = 'saved')",
                    (clean_onion(onion),),
                )
                return

            self._sql.execute(
                'DELETE FROM message_receipts '
                "WHERE peer_onion NOT IN (SELECT onion FROM peers WHERE alias_state = 'saved')"
            )
            return

        if onion:
            self._sql.execute(
                'DELETE FROM message_receipts WHERE peer_onion = ?',
                (clean_onion(onion),),
            )
            return

        self._sql.execute('DELETE FROM message_receipts')
