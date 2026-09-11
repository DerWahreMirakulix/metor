"""Centralized durable message spool, archive, and receipt helpers."""

import secrets
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, cast

from metor.utils import Constants, clean_onion
from metor.core.api import ContentType, Delivery, is_valid_message_id
from metor.data.message.models import (
    MessageDeleteOutcome,
    MessageDirection,
    MessageStatus,
    QueuedMessageResult,
    StoredMessageRecord,
    PendingLiveRecord,
    InboundVoiceRecord,
    UnreadInboxSummaryRecord,
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
    delivery: Delivery
    content_type: ContentType
    retained_bytes: int
    status: MessageStatus
    visible_in_history: bool
    created_at: str
    updated_at: str


class MessageRepository:
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

    def get_inbound_voice(
        self, contact_onion: str, msg_id: str
    ) -> Optional[InboundVoiceRecord]:
        """Loads one inbound Voice receipt and its resumable spool metadata."""
        rows = self._sql.fetchall(
            'SELECT r.id, r.peer_onion, r.delivery, i.payload, r.msg_id, '
            'r.created_at, r.retained_bytes, r.status '
            'FROM message_receipts AS r '
            'INNER JOIN inbound_spool AS i ON i.receipt_id = r.id '
            'WHERE r.peer_onion = ? AND r.direction = ? AND r.msg_id = ? '
            'AND r.content_type = ?',
            (
                clean_onion(contact_onion),
                MessageDirection.IN.value,
                msg_id,
                ContentType.VOICE.value,
            ),
        )
        if not rows:
            return None
        row = rows[0]
        return InboundVoiceRecord(
            receipt_id=int(str(row[0])),
            peer_onion=str(row[1]),
            delivery=str(row[2]),
            payload=str(row[3]),
            msg_id=str(row[4]),
            timestamp=str(row[5]),
            retained_bytes=int(str(row[6])),
            status=str(row[7]),
        )

    def get_unread_inbound_live_voices(self) -> List[InboundVoiceRecord]:
        """Loads crash-safe inbound LIVE Voice items still awaiting consume."""
        rows = self._sql.fetchall(
            'SELECT r.id, r.peer_onion, r.delivery, i.payload, r.msg_id, '
            'r.created_at, r.retained_bytes, r.status '
            'FROM message_receipts AS r '
            'INNER JOIN inbound_spool AS i ON i.receipt_id = r.id '
            'WHERE r.direction = ? AND r.delivery = ? AND r.content_type = ? '
            'AND r.status = ? ORDER BY r.id ASC',
            (
                MessageDirection.IN.value,
                Delivery.LIVE.value,
                ContentType.VOICE.value,
                MessageStatus.UNREAD.value,
            ),
        )
        return [
            InboundVoiceRecord(
                receipt_id=int(str(row[0])),
                peer_onion=str(row[1]),
                delivery=str(row[2]),
                payload=str(row[3]),
                msg_id=str(row[4]),
                timestamp=str(row[5]),
                retained_bytes=int(str(row[6])),
                status=str(row[7]),
            )
            for row in rows
        ]

    def count_unread_by_delivery(self, contact_onion: str, delivery: Delivery) -> int:
        """
        Counts unread inbound messages of one transport kind for one peer.

        Args:
            contact_onion (str): The remote onion identity.
            delivery (Delivery): The delivery semantics to count.

        Returns:
            int: The unread count.
        """
        rows = self._sql.fetchall(
            'SELECT COUNT(*) FROM message_receipts '
            'WHERE peer_onion = ? AND direction = ? AND delivery = ? AND status = ?',
            (
                clean_onion(contact_onion),
                MessageDirection.IN.value,
                delivery.value,
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
            'SELECT r.id, r.peer_onion, r.content_type, o.payload, r.msg_id, r.created_at '
            'FROM message_receipts AS r '
            'INNER JOIN outbox_spool AS o ON o.receipt_id = r.id '
            'WHERE r.direction = ? AND r.status = ? AND r.delivery = ? '
            'ORDER BY r.id ASC'
        )
        rows = self._sql.fetchall(
            query,
            (
                MessageDirection.OUT.value,
                MessageStatus.PENDING.value,
                Delivery.DROP.value,
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

    def get_pending_live_outbox(
        self,
        contact_onion: Optional[str] = None,
    ) -> List[PendingLiveRecord]:
        """
        Retrieves the durable pending live outbox queue.

        Args:
            contact_onion (Optional[str]): Optional peer onion filter.

        Returns:
            List[PendingLiveRecord]: Pending live rows.
        """
        filters: list[SqlParam] = [
            MessageDirection.OUT.value,
            MessageStatus.PENDING.value,
            Delivery.LIVE.value,
        ]
        peer_filter: str = ''
        if contact_onion is not None:
            peer_filter = ' AND r.peer_onion = ?'
            filters.append(clean_onion(contact_onion))

        query = (
            'SELECT r.id, r.peer_onion, r.content_type, o.payload, r.msg_id, r.created_at '
            'FROM message_receipts AS r '
            'INNER JOIN outbox_spool AS o ON o.receipt_id = r.id '
            'WHERE r.direction = ? AND r.status = ? AND r.delivery = ?'
            f'{peer_filter} '
            'ORDER BY r.created_at ASC, r.id ASC'
        )
        rows = self._sql.fetchall(query, tuple(filters))
        return [
            PendingLiveRecord(
                receipt_id=int(str(row[0])),
                peer_onion=str(row[1]),
                content_type=str(row[2]),
                payload=str(row[3]),
                msg_id=str(row[4]),
                timestamp=str(row[5]),
            )
            for row in rows
        ]

    def get_pending_live_usage(self) -> Tuple[int, int]:
        """Returns profile-wide outbound pending LIVE count and payload bytes.

        Args:
            None

        Returns:
            Tuple[int, int]: Logical-message count and UTF-8 payload bytes.
        """
        rows = self._sql.fetchall(
            'SELECT COUNT(*), COALESCE(SUM(CASE WHEN r.content_type = ? THEN r.retained_bytes ELSE LENGTH(CAST(o.payload AS BLOB)) END), 0) '
            'FROM message_receipts AS r '
            'INNER JOIN outbox_spool AS o ON o.receipt_id = r.id '
            'WHERE r.direction = ? AND r.status = ? AND r.delivery = ?',
            (
                ContentType.VOICE.value,
                MessageDirection.OUT.value,
                MessageStatus.PENDING.value,
                Delivery.LIVE.value,
            ),
        )
        return int(str(rows[0][0])), int(str(rows[0][1]))

    def update_retained_bytes(
        self, contact_onion: str, msg_id: str, retained_bytes: int, payload: str
    ) -> bool:
        """Updates bounded external payload accounting and serialized metadata.

        Args:
            contact_onion (str): Peer onion identity.
            msg_id (str): Stable logical message identifier.
            retained_bytes (int): Current retained binary byte count.
            payload (str): Updated compact content metadata.

        Returns:
            bool: True when an outbound pending receipt matched.
        """
        if retained_bytes < 0:
            return False
        with self._sql.transaction() as cursor:
            receipt = self._get_receipt(
                clean_onion(contact_onion), MessageDirection.OUT, msg_id, cursor
            )
            if receipt is None or receipt.status is not MessageStatus.PENDING:
                return False
            cursor.execute(
                'UPDATE message_receipts SET retained_bytes = ?, updated_at = ? WHERE id = ?',
                (retained_bytes, self._now(), receipt.receipt_id),
            )
            cursor.execute(
                'UPDATE outbox_spool SET payload = ? WHERE receipt_id = ?',
                (payload, receipt.receipt_id),
            )
            if receipt.delivery is Delivery.DROP:
                if self._voice_payload_finalized(payload):
                    cursor.execute(
                        'INSERT OR REPLACE INTO message_archive (receipt_id, payload) VALUES (?, ?)',
                        (receipt.receipt_id, payload),
                    )
                    cursor.execute(
                        'UPDATE message_receipts SET visible_in_history = 1 WHERE id = ?',
                        (receipt.receipt_id,),
                    )
            return True

    def update_inbound_voice_metadata(
        self, contact_onion: str, msg_id: str, retained_bytes: int, payload: str
    ) -> bool:
        """Updates one inbound Voice receipt and its crash-safe spool metadata.

        Args:
            contact_onion (str): Peer onion identity.
            msg_id (str): Stable logical Voice identity.
            retained_bytes (int): Retained binary byte count.
            payload (str): Final Voice metadata.

        Returns:
            bool: True when an inbound receipt matched.
        """
        with self._sql.transaction() as cursor:
            receipt = self._get_receipt(
                clean_onion(contact_onion), MessageDirection.IN, msg_id, cursor
            )
            if receipt is None or receipt.content_type is not ContentType.VOICE:
                return False
            cursor.execute(
                'UPDATE message_receipts SET retained_bytes = ?, updated_at = ? WHERE id = ?',
                (retained_bytes, self._now(), receipt.receipt_id),
            )
            cursor.execute(
                'UPDATE inbound_spool SET payload = ? WHERE receipt_id = ?',
                (payload, receipt.receipt_id),
            )
            if receipt.delivery is Delivery.DROP:
                if self._voice_payload_finalized(payload):
                    cursor.execute(
                        'INSERT INTO message_archive (receipt_id, payload) VALUES (?, ?) '
                        'ON CONFLICT(receipt_id) DO UPDATE SET payload = excluded.payload',
                        (receipt.receipt_id, payload),
                    )
                    cursor.execute(
                        'UPDATE message_receipts SET visible_in_history = 1 WHERE id = ?',
                        (receipt.receipt_id,),
                    )
            return True

    def promote_pending_live_to_drop(
        self,
        contact_onion: str,
        msg_ids: Optional[List[str]] = None,
    ) -> Optional[List[PendingLiveRecord]]:
        """Atomically validates and promotes selected pending LIVE records.

        Args:
            contact_onion (str): Expected peer onion identity.
            msg_ids (Optional[List[str]]): Selected logical IDs, or all for the peer.

        Returns:
            Optional[List[PendingLiveRecord]]: Promoted records, or None when any
                selected identity is invalid, duplicated, or ineligible.
        """
        normalized_onion = clean_onion(contact_onion)
        if msg_ids is not None and (
            not msg_ids
            or len(set(msg_ids)) != len(msg_ids)
            or any(not is_valid_message_id(msg_id) for msg_id in msg_ids)
        ):
            return None
        with self._sql.transaction() as cursor:
            params: list[SqlParam] = [
                normalized_onion,
                MessageDirection.OUT.value,
                Delivery.LIVE.value,
                MessageStatus.PENDING.value,
            ]
            selection_sql = ''
            if msg_ids is not None:
                selection_sql = f' AND r.msg_id IN ({self._placeholders(len(msg_ids))})'
                params.extend(msg_ids)
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(
                    'SELECT r.id, r.peer_onion, r.content_type, o.payload, r.msg_id, r.created_at '
                    'FROM message_receipts AS r '
                    'INNER JOIN outbox_spool AS o ON o.receipt_id = r.id '
                    'WHERE r.peer_onion = ? AND r.direction = ? AND r.delivery = ? AND r.status = ?'
                    f'{selection_sql} ORDER BY r.created_at ASC, r.id ASC',
                    tuple(params),
                ).fetchall(),
            )
            records = [
                PendingLiveRecord(
                    receipt_id=int(str(row[0])),
                    peer_onion=str(row[1]),
                    content_type=str(row[2]),
                    payload=str(row[3]),
                    msg_id=str(row[4]),
                    timestamp=str(row[5]),
                )
                for row in rows
            ]
            if msg_ids is not None and {record.msg_id for record in records} != set(
                msg_ids
            ):
                return None
            eligible_records: list[PendingLiveRecord] = []
            for record in records:
                if record.content_type != ContentType.VOICE.value:
                    eligible_records.append(record)
                    continue
                try:
                    metadata = json.loads(record.payload)
                    is_finalized = (
                        isinstance(metadata, dict) and metadata.get('finalized') is True
                    )
                except (TypeError, ValueError):
                    is_finalized = False
                if is_finalized:
                    eligible_records.append(record)
                elif msg_ids is not None:
                    return None
            records = eligible_records
            if not records:
                return []
            receipt_ids = [record.receipt_id for record in records]
            block = self._placeholders(len(receipt_ids))
            cursor.execute(
                f'UPDATE message_receipts SET delivery = ?, visible_in_history = 1, updated_at = ? WHERE id IN ({block})',
                (Delivery.DROP.value, self._now(), *receipt_ids),
            )
            cursor.execute(
                f'INSERT OR REPLACE INTO message_archive (receipt_id, payload) '
                f'SELECT receipt_id, payload FROM outbox_spool WHERE receipt_id IN ({block})',
                tuple(receipt_ids),
            )
            return records

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

    def get_unread_inbox_summaries(self) -> List[UnreadInboxSummaryRecord]:
        """
        Returns unread inbound totals and transport breakdown grouped by peer onion.

        Args:
            None

        Returns:
            List[UnreadInboxSummaryRecord]: One unread-summary row per peer.
        """
        rows = self._sql.fetchall(
            'SELECT peer_onion, COUNT(*), '
            'COALESCE(SUM(CASE WHEN delivery = ? THEN 1 ELSE 0 END), 0), '
            'COALESCE(SUM(CASE WHEN delivery = ? THEN 1 ELSE 0 END), 0) '
            'FROM message_receipts '
            'WHERE direction = ? AND status = ? '
            'GROUP BY peer_onion '
            'ORDER BY peer_onion ASC',
            (
                Delivery.DROP.value,
                Delivery.LIVE.value,
                MessageDirection.IN.value,
                MessageStatus.UNREAD.value,
            ),
        )
        return [
            UnreadInboxSummaryRecord(
                contact_onion=str(row[0]),
                total_unread=int(str(row[1])),
                drop_unread=int(str(row[2])),
                live_unread=int(str(row[3])),
            )
            for row in rows
        ]

    def get_drop_conversation_summaries(self) -> List[Tuple[str, int]]:
        """Returns DROP conversation identities and unread counts without payloads.

        Args:
            None

        Returns:
            List[Tuple[str, int]]: Peer onion and unread DROP count rows.
        """
        rows = self._sql.fetchall(
            'SELECT r.peer_onion, COALESCE(SUM(CASE WHEN r.direction = ? AND r.status = ? THEN 1 ELSE 0 END), 0) '
            'FROM message_receipts AS r '
            'LEFT JOIN message_archive AS a ON a.receipt_id = r.id '
            'WHERE r.delivery = ? AND (a.receipt_id IS NOT NULL OR r.status = ?) '
            'GROUP BY r.peer_onion ORDER BY MAX(r.created_at) DESC',
            (
                MessageDirection.IN.value,
                MessageStatus.UNREAD.value,
                Delivery.DROP.value,
                MessageStatus.PENDING.value,
            ),
        )
        return [(str(row[0]), int(str(row[1]))) for row in rows]

    def get_and_read_inbox(
        self,
        contact_onion: str,
        ephemeral_messages: bool,
        delivery: Optional[Delivery] = None,
    ) -> List[Tuple[int, str, str, str, Optional[str], str]]:
        """
        Retrieves unread inbox rows and applies consume semantics atomically.

        Args:
            contact_onion (str): The peer onion identity.
            ephemeral_messages (bool): Whether consumed drop payloads should be shredded.
            delivery (Optional[Delivery]): Optional delivery semantics filter.

        Returns:
            List[Tuple[int, str, str, str, Optional[str], str]]: Unread rows with content type.
        """
        normalized_onion: str = clean_onion(contact_onion)
        delivery_filter = ''
        params: list[SqlParam] = [
            normalized_onion,
            MessageDirection.IN.value,
            MessageStatus.UNREAD.value,
        ]
        if delivery is not None:
            delivery_filter = ' AND r.delivery = ?'
            params.append(delivery.value)
        query = (
            'SELECT r.id, r.delivery, s.payload, r.created_at, r.msg_id, r.content_type '
            'FROM message_receipts AS r '
            'INNER JOIN inbound_spool AS s ON s.receipt_id = r.id '
            'WHERE r.peer_onion = ? AND r.direction = ? AND r.status = ?'
            f'{delivery_filter} '
            'ORDER BY r.created_at ASC, r.id ASC'
        )

        with self._sql.transaction() as cursor:
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(
                    query,
                    tuple(params),
                ).fetchall(),
            )

            messages: List[Tuple[int, str, str, str, Optional[str], str]] = [
                (
                    int(str(row[0])),
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    str(row[4]) if row[4] is not None else None,
                    str(row[5]),
                )
                for row in rows
            ]
            if not messages:
                return messages

            receipt_ids: List[int] = [message[0] for message in messages]
            live_ids: List[int] = [
                message[0] for message in messages if message[1] == Delivery.LIVE.value
            ]
            drop_visible_ids: List[int] = [
                message[0] for message in messages if message[1] == Delivery.DROP.value
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
        query = """
            SELECT r.direction, r.status, a.payload, r.created_at, r.msg_id, r.content_type
            FROM message_receipts AS r
            INNER JOIN message_archive AS a ON a.receipt_id = r.id
            WHERE r.peer_onion = ?
              AND a.payload != ''
              AND r.delivery = ?
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT ?
        """
        rows = self._sql.fetchall(
            query,
            (
                clean_onion(contact_onion),
                Delivery.DROP.value,
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
                msg_id=str(row[4]),
                content_type=str(row[5]),
            )
            for row in rows
        ]

    def get_drop_voice_payloads(
        self,
        onion: Optional[str] = None,
        non_contacts_only: bool = False,
        msg_id: Optional[str] = None,
    ) -> List[str]:
        """Returns Voice metadata whose persistent blobs may be explicitly cleared.

        Pending outbound DROP rows are deliberately excluded because their blobs
        remain delivery-critical even after the visible conversation is cleared.
        """
        filters = [
            'r.delivery = ?',
            'r.content_type = ?',
            'NOT (r.direction = ? AND r.status = ?)',
        ]
        params: list[SqlParam] = [
            Delivery.DROP.value,
            ContentType.VOICE.value,
            MessageDirection.OUT.value,
            MessageStatus.PENDING.value,
        ]
        if onion:
            filters.append('r.peer_onion = ?')
            params.append(clean_onion(onion))
        if non_contacts_only:
            filters.append(
                "r.peer_onion NOT IN (SELECT onion FROM peers WHERE alias_state = 'saved')"
            )
        if msg_id is not None:
            if not is_valid_message_id(msg_id):
                return []
            filters.append('r.msg_id = ?')
            params.append(msg_id)
        where = ' AND '.join(filters)
        rows = self._sql.fetchall(
            'SELECT COALESCE(i.payload, a.payload) '
            'FROM message_receipts AS r '
            'LEFT JOIN inbound_spool AS i ON i.receipt_id = r.id '
            'LEFT JOIN message_archive AS a ON a.receipt_id = r.id '
            f'WHERE {where} AND COALESCE(i.payload, a.payload) IS NOT NULL',
            tuple(params),
        )
        return [str(row[0]) for row in rows]

    def has_drop_payload(self, contact_onion: str, msg_id: str) -> bool:
        """Reports whether one DROP receipt still owns visible archive payload."""
        rows = self._sql.fetchall(
            'SELECT 1 FROM message_receipts AS r '
            'INNER JOIN message_archive AS a ON a.receipt_id = r.id '
            'WHERE r.peer_onion = ? AND r.msg_id = ? AND r.delivery = ? LIMIT 1',
            (clean_onion(contact_onion), msg_id, Delivery.DROP.value),
        )
        return bool(rows)

    def clear_messages(
        self,
        onion: Optional[str] = None,
        non_contacts_only: bool = False,
    ) -> None:
        """
        Clears only DROP payload/history state while retaining delivery receipts.

        Args:
            onion (Optional[str]): Optional peer onion filter.
            non_contacts_only (bool): Whether only discovered peers should be affected.

        Returns:
            None
        """
        filters = ['delivery = ?']
        params: list[SqlParam] = [Delivery.DROP.value]
        if onion:
            filters.append('peer_onion = ?')
            params.append(clean_onion(onion))
        if non_contacts_only:
            filters.append(
                "peer_onion NOT IN (SELECT onion FROM peers WHERE alias_state = 'saved')"
            )
        where = ' AND '.join(filters)
        with self._sql.transaction() as cursor:
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(
                    f'SELECT id, direction, status FROM message_receipts WHERE {where} '
                    'AND NOT (content_type = ? AND direction = ? '
                    'AND NOT EXISTS (SELECT 1 FROM message_archive WHERE receipt_id = message_receipts.id))',
                    (
                        *params,
                        ContentType.VOICE.value,
                        MessageDirection.IN.value,
                    ),
                ).fetchall(),
            )
            if not rows:
                return
            receipt_ids = [int(str(row[0])) for row in rows]
            block = self._placeholders(len(receipt_ids))
            cursor.execute(
                f'DELETE FROM message_archive WHERE receipt_id IN ({block})',
                tuple(receipt_ids),
            )
            inbound_ids = [
                int(str(row[0]))
                for row in rows
                if str(row[1]) == MessageDirection.IN.value
            ]
            if inbound_ids:
                inbound_block = self._placeholders(len(inbound_ids))
                cursor.execute(
                    f'DELETE FROM inbound_spool WHERE receipt_id IN ({inbound_block})',
                    tuple(inbound_ids),
                )
                cursor.execute(
                    f'UPDATE message_receipts SET status = ?, visible_in_history = 0, updated_at = ? '
                    f'WHERE id IN ({inbound_block})',
                    (MessageStatus.READ.value, self._now(), *inbound_ids),
                )
            cursor.execute(
                f'UPDATE message_receipts SET visible_in_history = 0, updated_at = ? '
                f'WHERE id IN ({block})',
                (self._now(), *receipt_ids),
            )

    def delete_drop_message(
        self, contact_onion: str, msg_id: str
    ) -> MessageDeleteOutcome:
        """Deletes one local DROP payload while preserving the logical receipt.

        Args:
            contact_onion (str): Expected peer onion identity.
            msg_id (str): Stable logical message identifier.

        Returns:
            MessageDeleteOutcome: Typed operation outcome.
        """
        normalized_onion = clean_onion(contact_onion)
        if not is_valid_message_id(msg_id):
            return MessageDeleteOutcome.NOT_FOUND
        with self._sql.transaction() as cursor:
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(
                    'SELECT r.id, r.delivery, r.direction, r.status, '
                    'EXISTS(SELECT 1 FROM message_archive AS a WHERE a.receipt_id = r.id) '
                    'FROM message_receipts AS r '
                    'WHERE peer_onion = ? AND msg_id = ?',
                    (normalized_onion, msg_id),
                ).fetchall(),
            )
            if not rows:
                return MessageDeleteOutcome.NOT_FOUND
            receipt_id = int(str(rows[0][0]))
            if str(rows[0][1]) != Delivery.DROP.value:
                return MessageDeleteOutcome.NOT_DROP
            if (
                str(rows[0][2]) == MessageDirection.OUT.value
                and str(rows[0][3]) == MessageStatus.PENDING.value
            ):
                return MessageDeleteOutcome.PENDING_DELIVERY
            if int(str(rows[0][4])) != 1:
                return MessageDeleteOutcome.NOT_FOUND
            cursor.execute(
                'DELETE FROM message_archive WHERE receipt_id = ?', (receipt_id,)
            )
            cursor.execute(
                'DELETE FROM inbound_spool WHERE receipt_id = ?', (receipt_id,)
            )
            cursor.execute(
                'UPDATE message_receipts SET visible_in_history = 0, status = CASE '
                'WHEN direction = ? THEN ? ELSE status END, updated_at = ? WHERE id = ?',
                (
                    MessageDirection.IN.value,
                    MessageStatus.READ.value,
                    self._now(),
                    receipt_id,
                ),
            )
            return MessageDeleteOutcome.DELETED

    def dismiss_inbound_live(self, contact_onion: str) -> int:
        """Destroys inbound LIVE spool payloads while retaining dedupe receipts.

        Args:
            contact_onion (str): Peer onion identity.

        Returns:
            int: Number of LIVE receipts dismissed.
        """
        normalized_onion = clean_onion(contact_onion)
        with self._sql.transaction() as cursor:
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(
                    'SELECT id FROM message_receipts WHERE peer_onion = ? AND direction = ? AND delivery = ?',
                    (
                        normalized_onion,
                        MessageDirection.IN.value,
                        Delivery.LIVE.value,
                    ),
                ).fetchall(),
            )
            receipt_ids = [int(str(row[0])) for row in rows]
            if not receipt_ids:
                return 0
            block = self._placeholders(len(receipt_ids))
            cursor.execute(
                f'DELETE FROM inbound_spool WHERE receipt_id IN ({block})',
                tuple(receipt_ids),
            )
            cursor.execute(
                f'DELETE FROM message_archive WHERE receipt_id IN ({block})',
                tuple(receipt_ids),
            )
            cursor.execute(
                f'UPDATE message_receipts SET status = ?, visible_in_history = 0, updated_at = ? '
                f'WHERE id IN ({block})',
                (MessageStatus.READ.value, self._now(), *receipt_ids),
            )
            return len(receipt_ids)
