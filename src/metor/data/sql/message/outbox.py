"""Outbound spool admission, Voice metadata, and fallback promotion."""

from __future__ import annotations

import json
from typing import Any, List, Optional, Tuple, cast

from metor.core.api import ContentType, Delivery, is_valid_message_id
from metor.data.message.models import (
    MessageDirection,
    MessageStatus,
    PendingLiveAdmission,
    PendingLiveRecord,
)
from metor.data.sql.backends import SqlParam
from metor.utils import clean_onion


class MessageOutboxMixin:
    """Owns pending outbox state and atomic shared quota admission."""

    def __getattr__(self, name: str) -> Any:
        """Defers typed collaborator attributes to the composed repository."""
        raise AttributeError(name)

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

    def get_voice_draft_payloads(self) -> List[str]:
        """Returns outbound DROP Voice metadata awaiting commit or cancellation.

        Args:
            None

        Returns:
            List[str]: Ordered draft metadata documents.
        """
        rows = self._sql.fetchall(
            'SELECT o.payload FROM message_receipts AS r '
            'INNER JOIN outbox_spool AS o ON o.receipt_id = r.id '
            'WHERE r.direction = ? AND r.delivery = ? '
            'AND r.content_type = ? AND r.status = ? ORDER BY r.id ASC',
            (
                MessageDirection.OUT.value,
                Delivery.DROP.value,
                ContentType.VOICE.value,
                MessageStatus.DRAFT.value,
            ),
        )
        return [str(row[0]) for row in rows]

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

    def queue_pending_live_if_capacity(
        self,
        contact_onion: str,
        content_type: ContentType,
        payload: str,
        msg_id: str,
        timestamp: str,
        retained_bytes: int,
        count_limit: int,
        byte_limit: int,
    ) -> PendingLiveAdmission:
        """Atomically reserves profile-wide LIVE count/byte capacity and queues.

        Args:
            contact_onion (str): Peer onion identity.
            content_type (ContentType): Typed content discriminator.
            payload (str): Durable spool payload or Voice metadata.
            msg_id (str): Stable logical identity.
            timestamp (str): Authored timestamp.
            retained_bytes (int): Binary bytes retained outside SQL.
            count_limit (int): Maximum pending LIVE item count.
            byte_limit (int): Maximum pending LIVE content bytes.

        Returns:
            PendingLiveAdmission: Atomic admission result.
        """
        normalized_onion = clean_onion(contact_onion)
        if not is_valid_message_id(msg_id) or retained_bytes < 0:
            return PendingLiveAdmission.DUPLICATE
        item_bytes = (
            retained_bytes
            if content_type is ContentType.VOICE
            else len(payload.encode('utf-8'))
        )
        with self._sql.transaction() as cursor:
            existing = self._get_receipt(
                normalized_onion, MessageDirection.OUT, msg_id, cursor
            )
            if existing is not None:
                return PendingLiveAdmission.DUPLICATE
            usage = cursor.execute(
                'SELECT COUNT(*), COALESCE(SUM(CASE WHEN r.content_type = ? '
                'THEN r.retained_bytes ELSE LENGTH(CAST(o.payload AS BLOB)) END), 0) '
                'FROM message_receipts AS r INNER JOIN outbox_spool AS o '
                'ON o.receipt_id = r.id WHERE r.direction = ? AND r.status = ? '
                'AND r.delivery = ?',
                (
                    ContentType.VOICE.value,
                    MessageDirection.OUT.value,
                    MessageStatus.PENDING.value,
                    Delivery.LIVE.value,
                ),
            ).fetchall()[0]
            pending_count = int(str(usage[0]))
            pending_bytes = int(str(usage[1]))
            if count_limit >= 0 and pending_count >= count_limit:
                return PendingLiveAdmission.COUNT_LIMIT
            if byte_limit >= 0 and pending_bytes + item_bytes > byte_limit:
                return PendingLiveAdmission.BYTE_LIMIT
            cursor.execute(
                'INSERT INTO message_receipts '
                '(msg_id, peer_onion, direction, delivery, content_type, retained_bytes, status, visible_in_history, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)',
                (
                    msg_id,
                    normalized_onion,
                    MessageDirection.OUT.value,
                    Delivery.LIVE.value,
                    content_type.value,
                    retained_bytes,
                    MessageStatus.PENDING.value,
                    timestamp,
                    timestamp,
                ),
            )
            receipt_id = int(
                str(cursor.execute('SELECT last_insert_rowid()').fetchall()[0][0])
            )
            cursor.execute(
                'INSERT INTO outbox_spool (receipt_id, payload) VALUES (?, ?)',
                (receipt_id, payload),
            )
            return PendingLiveAdmission.ACCEPTED

    def grow_pending_live_voice_if_capacity(
        self,
        contact_onion: str,
        msg_id: str,
        expected_bytes: int,
        retained_bytes: int,
        payload: str,
        byte_limit: int,
    ) -> PendingLiveAdmission:
        """Atomically grows one Voice reservation against the shared byte limit.

        Args:
            contact_onion (str): Peer onion identity.
            msg_id (str): Stable logical identity.
            expected_bytes (int): Current size required for exact update.
            retained_bytes (int): Requested new retained size.
            payload (str): Updated Voice metadata.
            byte_limit (int): Maximum profile-wide pending LIVE bytes.

        Returns:
            PendingLiveAdmission: Accepted or a typed refusal.
        """
        if retained_bytes <= expected_bytes:
            return PendingLiveAdmission.DUPLICATE
        with self._sql.transaction() as cursor:
            receipt = self._get_receipt(
                clean_onion(contact_onion), MessageDirection.OUT, msg_id, cursor
            )
            if (
                receipt is None
                or receipt.delivery is not Delivery.LIVE
                or receipt.content_type is not ContentType.VOICE
                or receipt.status is not MessageStatus.PENDING
                or receipt.retained_bytes != expected_bytes
            ):
                return PendingLiveAdmission.DUPLICATE
            usage = cursor.execute(
                'SELECT COALESCE(SUM(CASE WHEN r.content_type = ? THEN '
                'r.retained_bytes ELSE LENGTH(CAST(o.payload AS BLOB)) END), 0) '
                'FROM message_receipts AS r INNER JOIN outbox_spool AS o '
                'ON o.receipt_id = r.id WHERE r.direction = ? AND r.status = ? '
                'AND r.delivery = ?',
                (
                    ContentType.VOICE.value,
                    MessageDirection.OUT.value,
                    MessageStatus.PENDING.value,
                    Delivery.LIVE.value,
                ),
            ).fetchall()[0][0]
            pending_bytes = int(str(usage))
            if (
                byte_limit >= 0
                and pending_bytes + retained_bytes - expected_bytes > byte_limit
            ):
                return PendingLiveAdmission.BYTE_LIMIT
            cursor.execute(
                'UPDATE message_receipts SET retained_bytes = ?, updated_at = ? '
                'WHERE id = ?',
                (retained_bytes, self._now(), receipt.receipt_id),
            )
            cursor.execute(
                'UPDATE outbox_spool SET payload = ? WHERE receipt_id = ?',
                (payload, receipt.receipt_id),
            )
            return PendingLiveAdmission.ACCEPTED

    def commit_voice_draft(self, contact_onion: str, msg_id: str) -> bool:
        """Publishes one finalized outbound DROP Voice draft to the outbox.

        Args:
            contact_onion (str): Peer onion identity.
            msg_id (str): Stable draft identity.

        Returns:
            bool: True when the draft became pending delivery.
        """
        with self._sql.transaction() as cursor:
            receipt = self._get_receipt(
                clean_onion(contact_onion), MessageDirection.OUT, msg_id, cursor
            )
            if (
                receipt is None
                or receipt.delivery is not Delivery.DROP
                or receipt.content_type is not ContentType.VOICE
                or receipt.status is not MessageStatus.DRAFT
            ):
                return False
            rows = cursor.execute(
                'SELECT payload FROM outbox_spool WHERE receipt_id = ?',
                (receipt.receipt_id,),
            ).fetchall()
            if not rows or not self._voice_payload_finalized(str(rows[0][0])):
                return False
            payload = str(rows[0][0])
            cursor.execute(
                'UPDATE message_receipts SET status = ?, visible_in_history = 1, '
                'updated_at = ? WHERE id = ?',
                (MessageStatus.PENDING.value, self._now(), receipt.receipt_id),
            )
            cursor.execute(
                'INSERT INTO message_archive (receipt_id, payload) VALUES (?, ?) '
                'ON CONFLICT(receipt_id) DO UPDATE SET payload = excluded.payload',
                (receipt.receipt_id, payload),
            )
            return True

    def cancel_voice_draft(self, contact_onion: str, msg_id: str) -> Optional[str]:
        """Deletes one unsent DROP Voice draft and returns owned metadata.

        Args:
            contact_onion (str): Peer onion identity.
            msg_id (str): Stable draft identity.

        Returns:
            Optional[str]: Metadata to release when an eligible draft existed.
        """
        with self._sql.transaction() as cursor:
            receipt = self._get_receipt(
                clean_onion(contact_onion), MessageDirection.OUT, msg_id, cursor
            )
            if (
                receipt is None
                or receipt.delivery is not Delivery.DROP
                or receipt.content_type is not ContentType.VOICE
                or receipt.status is not MessageStatus.DRAFT
            ):
                return None
            rows = cursor.execute(
                'SELECT payload FROM outbox_spool WHERE receipt_id = ?',
                (receipt.receipt_id,),
            ).fetchall()
            if not rows:
                return None
            payload = str(rows[0][0])
            cursor.execute(
                'DELETE FROM message_receipts WHERE id = ?', (receipt.receipt_id,)
            )
            return payload

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
            if receipt is None or receipt.status not in {
                MessageStatus.PENDING,
                MessageStatus.DRAFT,
            }:
                return False
            cursor.execute(
                'UPDATE message_receipts SET retained_bytes = ?, updated_at = ? WHERE id = ?',
                (retained_bytes, self._now(), receipt.receipt_id),
            )
            cursor.execute(
                'UPDATE outbox_spool SET payload = ? WHERE receipt_id = ?',
                (payload, receipt.receipt_id),
            )
            if (
                receipt.delivery is Delivery.DROP
                and receipt.status is MessageStatus.PENDING
            ):
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

    def promote_inbound_voice_to_drop(
        self,
        contact_onion: str,
        msg_id: str,
        payload: str,
        retained_bytes: int,
    ) -> bool:
        """Strengthens one inbound Voice identity to DROP without duplication.

        Args:
            contact_onion (str): Authenticated peer identity.
            msg_id (str): Stable logical identity.
            payload (str): Current canonical Voice metadata.
            retained_bytes (int): Current retained byte count.

        Returns:
            bool: True when the identity was Voice and is now DROP-owned.
        """
        with self._sql.transaction() as cursor:
            receipt = self._get_receipt(
                clean_onion(contact_onion), MessageDirection.IN, msg_id, cursor
            )
            if receipt is None or receipt.content_type is not ContentType.VOICE:
                return False
            finalized = self._voice_payload_finalized(payload)
            cursor.execute(
                'INSERT INTO inbound_spool (receipt_id, payload) VALUES (?, ?) '
                'ON CONFLICT(receipt_id) DO UPDATE SET payload = excluded.payload',
                (receipt.receipt_id, payload),
            )
            cursor.execute(
                'UPDATE message_receipts SET delivery = ?, retained_bytes = ?, '
                'status = ?, visible_in_history = ?, updated_at = ? WHERE id = ?',
                (
                    Delivery.DROP.value,
                    retained_bytes,
                    MessageStatus.UNREAD.value,
                    int(finalized),
                    self._now(),
                    receipt.receipt_id,
                ),
            )
            if finalized:
                cursor.execute(
                    'INSERT INTO message_archive (receipt_id, payload) VALUES (?, ?) '
                    'ON CONFLICT(receipt_id) DO UPDATE SET payload = excluded.payload',
                    (receipt.receipt_id, payload),
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
