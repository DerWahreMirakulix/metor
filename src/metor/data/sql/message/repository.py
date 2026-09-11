"""Centralized durable message spool, archive, and receipt helpers."""

import base64
import hashlib
import json
import secrets
from typing import TYPE_CHECKING, List, Optional, Tuple, cast

from metor.utils import Constants, clean_onion
from metor.core.api import ContentType, Delivery, is_valid_message_id
from metor.data.message.models import (
    MessageDirection,
    MessageStatus,
    QueuedMessageResult,
    RetainedMessagePage,
    RetainedMessageRecord,
)

# Local Package Imports
from metor.data.sql.backends import SqlCipherCursor, SqlParam
from .receipts import MessageReceiptRow
from .history import MessageHistoryMixin
from .inbound import MessageInboundMixin
from .outbox import MessageOutboxMixin

if TYPE_CHECKING:
    from metor.data.sql.manager import SqlManager


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
    def _retained_filter(
        contact_onion: Optional[str],
        delivery: Optional[Delivery],
        direction: Optional[MessageDirection],
    ) -> tuple[str, list[SqlParam], str]:
        """Builds the bounded inventory predicate and stable filter identity."""
        clauses = [
            "((r.direction = 'out' AND r.status IN ('pending', 'draft')) "
            "OR (r.direction = 'in' AND r.content_type = 'voice' "
            "AND r.status = 'unread'))",
            '(i.receipt_id IS NOT NULL OR o.receipt_id IS NOT NULL '
            'OR a.receipt_id IS NOT NULL)',
        ]
        params: list[SqlParam] = []
        normalized_onion = clean_onion(contact_onion) if contact_onion else None
        if normalized_onion is not None:
            clauses.append('r.peer_onion = ?')
            params.append(normalized_onion)
        if delivery is not None:
            clauses.append('r.delivery = ?')
            params.append(delivery.value)
        if direction is not None:
            clauses.append('r.direction = ?')
            params.append(direction.value)
        identity = json.dumps(
            {
                'target': normalized_onion,
                'delivery': delivery.value if delivery is not None else None,
                'direction': direction.value if direction is not None else None,
            },
            sort_keys=True,
            separators=(',', ':'),
        )
        fingerprint = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]
        return ' AND '.join(clauses), params, fingerprint

    @staticmethod
    def _decode_retained_cursor(cursor: str) -> dict[str, object]:
        """Decodes one opaque bounded inventory cursor."""
        if not cursor or len(cursor) > 1024:
            raise ValueError('Invalid retained-message cursor.')
        try:
            padding = '=' * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode((cursor + padding).encode('ascii'))
            if len(raw) > 768:
                raise ValueError
            value = json.loads(raw.decode('utf-8'))
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError('Invalid retained-message cursor.') from exc
        if not isinstance(value, dict):
            raise ValueError('Invalid retained-message cursor.')
        return value

    @staticmethod
    def _encode_retained_cursor(
        last_id: int, ceiling_id: int, version: str, fingerprint: str
    ) -> str:
        """Encodes one content-free inventory continuation token."""
        raw = json.dumps(
            {
                'v': 1,
                'after': last_id,
                'ceiling': ceiling_id,
                'revision': version,
                'filter': fingerprint,
            },
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
        return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

    @staticmethod
    def _retained_record(row: Tuple[SqlParam, ...]) -> RetainedMessageRecord:
        """Converts a retained receipt row without returning serialized content."""
        content_type = ContentType(str(row[4]))
        retained_bytes = int(str(row[7]))
        finalized = content_type is ContentType.TEXT
        codec: Optional[str] = None
        duration_ms: Optional[int] = None
        if content_type is ContentType.VOICE:
            payload = str(row[8])
            try:
                metadata = json.loads(payload)
            except (TypeError, ValueError):
                metadata = None
            if isinstance(metadata, dict):
                finalized = metadata.get('finalized') is True
                raw_codec = metadata.get('codec')
                if isinstance(raw_codec, str) and 0 < len(raw_codec) <= 64:
                    codec = raw_codec
                raw_duration = metadata.get('duration_ms')
                if type(raw_duration) is int and raw_duration >= 0:
                    duration_ms = raw_duration
        return RetainedMessageRecord(
            peer_onion=str(row[1]),
            direction=MessageDirection(str(row[2])),
            delivery=str(row[3]),
            content_type=content_type.value,
            msg_id=str(row[5]),
            status=str(row[6]),
            finalized=finalized,
            retained_bytes=retained_bytes,
            codec=codec,
            duration_ms=duration_ms,
        )

    def list_retained_messages(
        self,
        contact_onion: Optional[str] = None,
        delivery: Optional[Delivery] = None,
        direction: Optional[MessageDirection] = None,
        cursor: Optional[str] = None,
        limit: int = Constants.DEFAULT_RETAINED_PAGE_SIZE,
    ) -> RetainedMessagePage:
        """Returns a non-consuming, stable page of retained logical identities.

        Continuations are rejected if any matching receipt changed between pages,
        forcing clients to restart instead of merging a torn inventory.
        """
        if type(limit) is not int or not 1 <= limit <= Constants.MAX_RETAINED_PAGE_SIZE:
            raise ValueError('Invalid retained-message page size.')
        predicate, params, fingerprint = self._retained_filter(
            contact_onion, delivery, direction
        )
        joins = (
            ' FROM message_receipts AS r '
            'LEFT JOIN inbound_spool AS i ON i.receipt_id = r.id '
            'LEFT JOIN outbox_spool AS o ON o.receipt_id = r.id '
            'LEFT JOIN message_archive AS a ON a.receipt_id = r.id '
        )
        with self._sql.transaction() as sql_cursor:
            aggregate = cast(
                Optional[Tuple[SqlParam, ...]],
                sql_cursor.execute(
                    'SELECT COUNT(*), COALESCE(MAX(r.id), 0), '
                    "COALESCE(MAX(r.updated_at), ''), COALESCE(SUM(r.id), 0)"
                    + joins
                    + 'WHERE '
                    + predicate,
                    tuple(params),
                ).fetchone(),
            )
            if aggregate is None:
                raise ValueError('Retained-message inventory is unavailable.')
            count = int(str(aggregate[0]))
            current_ceiling = int(str(aggregate[1]))
            version = hashlib.sha256(
                ':'.join(
                    (
                        str(count),
                        str(current_ceiling),
                        str(aggregate[2]),
                        str(aggregate[3]),
                    )
                ).encode('utf-8')
            ).hexdigest()[:24]
            after_id = 0
            ceiling_id = current_ceiling
            if cursor is not None:
                decoded = self._decode_retained_cursor(cursor)
                if (
                    decoded.get('v') != 1
                    or decoded.get('filter') != fingerprint
                    or decoded.get('revision') != version
                    or type(decoded.get('after')) is not int
                    or type(decoded.get('ceiling')) is not int
                ):
                    raise ValueError('Retained-message inventory changed; retry.')
                after_id = cast(int, decoded['after'])
                ceiling_id = cast(int, decoded['ceiling'])
                if not 0 <= after_id <= ceiling_id or ceiling_id != current_ceiling:
                    raise ValueError('Invalid retained-message cursor.')

            page_params = [*params, after_id, ceiling_id, limit + 1]
            rows = cast(
                List[Tuple[SqlParam, ...]],
                sql_cursor.execute(
                    'SELECT r.id, r.peer_onion, r.direction, r.delivery, '
                    'r.content_type, r.msg_id, r.status, r.retained_bytes, '
                    'COALESCE(i.payload, o.payload, a.payload)'
                    + joins
                    + 'WHERE '
                    + predicate
                    + ' AND r.id > ? AND r.id <= ? ORDER BY r.id ASC LIMIT ?',
                    tuple(page_params),
                ).fetchall(),
            )
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        next_cursor = None
        if has_more:
            next_cursor = self._encode_retained_cursor(
                int(str(visible_rows[-1][0])), ceiling_id, version, fingerprint
            )
        return RetainedMessagePage(
            messages=[self._retained_record(row) for row in visible_rows],
            next_cursor=next_cursor,
            inventory_version=version,
        )

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
