"""Centralized durable message spool, archive, and receipt helpers."""

import secrets
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional, Tuple, cast

from metor.utils import Constants, clean_onion
from metor.core.api import ContentType, Delivery, is_valid_message_id
from metor.data.message.models import (
    MessageDirection,
    MessageStatus,
    QueuedMessageResult,
)

# Local Package Imports
from metor.data.sql.backends import SqlCipherCursor, SqlParam
from .history import MessageHistoryMixin
from .inbound import MessageInboundMixin
from .outbox import MessageOutboxMixin

if TYPE_CHECKING:
    from metor.data.sql.manager import SqlManager


@dataclass(frozen=True)
class MessageReceiptRow:
    """Represents one persisted message receipt row."""

    receipt_id: int
    msg_id: str
    peer_onion: str
    direction: MessageDirection
    delivery: Delivery
    content_type: ContentType
    retained_bytes: int
    status: MessageStatus
    visible_in_history: bool
    created_at: str
    updated_at: str


class MessageRepository(MessageInboundMixin, MessageOutboxMixin, MessageHistoryMixin):
    """Centralized durable message spool, archive, and receipt helpers."""

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

    @staticmethod
    def _voice_payload_finalized(payload: str) -> bool:
        """Checks whether compact Voice metadata represents a complete turn."""
        try:
            metadata = json.loads(payload)
        except (TypeError, ValueError):
            return False
        return isinstance(metadata, dict) and metadata.get('finalized') is True

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
            delivery=Delivery(str(row[4])),
            content_type=ContentType(str(row[5])),
            retained_bytes=int(str(row[6])),
            status=MessageStatus(str(row[7])),
            visible_in_history=int(str(row[8])) == 1,
            created_at=str(row[9]),
            updated_at=str(row[10]),
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
            'SELECT id, msg_id, peer_onion, direction, delivery, content_type, retained_bytes, status, '
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
        delivery: Delivery,
        content_type: ContentType,
        payload: str,
        status: MessageStatus,
        msg_id: Optional[str] = None,
        timestamp: Optional[str] = None,
        retained_bytes: int = 0,
    ) -> QueuedMessageResult:
        """
        Stores one durable logical message across receipt, spool, and archive tables.

        Args:
            contact_onion (str): The peer onion identity.
            direction (MessageDirection): The message direction.
            delivery (Delivery): Live or persistent delivery semantics.
            content_type (ContentType): The payload discriminator.
            payload (str): The stored payload.
            status (MessageStatus): The persisted delivery state.
            msg_id (Optional[str]): The stable message identifier.
            timestamp (Optional[str]): The authored message timestamp.
            retained_bytes (int): Binary payload bytes retained outside SQL.

        Returns:
            QueuedMessageResult: The stored receipt id and duplicate flag.
        """
        normalized_onion: str = clean_onion(contact_onion)
        actual_msg_id: str = (
            msg_id if msg_id else secrets.token_hex(Constants.UUID_MSG_BYTES)
        )
        if not is_valid_message_id(actual_msg_id):
            raise ValueError('Invalid message ID.')
        created_at: str = timestamp if timestamp else self._now()
        visible_in_history: int = int(
            delivery is Delivery.DROP
            and (
                content_type is not ContentType.VOICE
                or self._voice_payload_finalized(payload)
            )
        )

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
                    'SET delivery = ?, content_type = ?, retained_bytes = ?, status = ?, visible_in_history = ?, updated_at = ? '
                    'WHERE id = ?',
                    (
                        delivery.value,
                        content_type.value,
                        retained_bytes,
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

                if direction is MessageDirection.OUT and status in {
                    MessageStatus.PENDING,
                    MessageStatus.DRAFT,
                }:
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
                '(msg_id, peer_onion, direction, delivery, content_type, retained_bytes, status, visible_in_history, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    actual_msg_id,
                    normalized_onion,
                    direction.value,
                    delivery.value,
                    content_type.value,
                    retained_bytes,
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

            if direction is MessageDirection.OUT and status in {
                MessageStatus.PENDING,
                MessageStatus.DRAFT,
            }:
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

    def _apply_message_status_update(
        self,
        cursor: SqlCipherCursor,
        receipt_id: int,
        new_status: MessageStatus,
    ) -> None:
        """
        Applies one status transition and maintains spool consistency.

        Args:
            cursor (SqlCipherCursor): The active SQL cursor.
            receipt_id (int): The durable receipt id.
            new_status (MessageStatus): The new status.

        Returns:
            None
        """
        cursor.execute(
            'UPDATE message_receipts SET status = ?, updated_at = ? WHERE id = ?',
            (new_status.value, self._now(), receipt_id),
        )
        if new_status is not MessageStatus.PENDING:
            cursor.execute(
                'DELETE FROM outbox_spool WHERE receipt_id = ?',
                (receipt_id,),
            )

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
            self._apply_message_status_update(cursor, receipt_id, new_status)

    def mark_drop_delivered(
        self,
        contact_onion: str,
        msg_id: str,
    ) -> Optional[str]:
        """
        Marks one pending drop-visible outbound receipt as delivered.

        Matches only outbound receipts whose transport kind is drop-visible and
        whose status is still PENDING, so live-visible receipts and already
        terminal rows are left untouched.

        Args:
            contact_onion (str): The peer onion identity.
            msg_id (str): The stable logical message identifier.

        Returns:
            Optional[str]: The original receipt timestamp when a pending drop
                row was marked delivered, or None if no pending drop row matched.
        """
        normalized_onion: str = clean_onion(contact_onion)
        with self._sql.transaction() as cursor:
            receipt: Optional[MessageReceiptRow] = self._get_receipt(
                normalized_onion,
                MessageDirection.OUT,
                msg_id,
                cursor,
            )
            if receipt is None:
                return None
            if receipt.delivery is not Delivery.DROP:
                return None
            if receipt.status is not MessageStatus.PENDING:
                return None

            self._apply_message_status_update(
                cursor,
                receipt.receipt_id,
                MessageStatus.DELIVERED,
            )
            return receipt.created_at

    def mark_live_text_delivered(
        self,
        contact_onion: str,
        msg_id: str,
    ) -> Optional[str]:
        """Marks only one pending LIVE text receipt delivered.

        Args:
            contact_onion (str): Peer onion identity.
            msg_id (str): Stable logical message identity.

        Returns:
            Optional[str]: Authored timestamp when an eligible row transitioned.
        """
        normalized_onion = clean_onion(contact_onion)
        with self._sql.transaction() as cursor:
            receipt = self._get_receipt(
                normalized_onion, MessageDirection.OUT, msg_id, cursor
            )
            if (
                receipt is None
                or receipt.delivery is not Delivery.LIVE
                or receipt.content_type is not ContentType.TEXT
                or receipt.status is not MessageStatus.PENDING
            ):
                return None
            self._apply_message_status_update(
                cursor, receipt.receipt_id, MessageStatus.DELIVERED
            )
            return receipt.created_at

    def update_outbound_message_status(
        self,
        contact_onion: str,
        msg_id: str,
        new_status: MessageStatus,
    ) -> bool:
        """
        Updates one outbound logical message status using its stable message id.

        Args:
            contact_onion (str): The peer onion identity.
            msg_id (str): The logical message identifier.
            new_status (MessageStatus): The new status.

        Returns:
            bool: True if the outbound receipt was found and updated.
        """
        normalized_onion: str = clean_onion(contact_onion)
        with self._sql.transaction() as cursor:
            receipt: Optional[MessageReceiptRow] = self._get_receipt(
                normalized_onion,
                MessageDirection.OUT,
                msg_id,
                cursor,
            )
            if receipt is None:
                return False

            self._apply_message_status_update(
                cursor,
                receipt.receipt_id,
                new_status,
            )
            return True
