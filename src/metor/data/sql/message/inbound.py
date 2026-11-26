"""Inbound text and Voice receipt persistence."""

from __future__ import annotations

from typing import List, Optional

from metor.core.api import ContentType, Delivery
from metor.data.message.models import (
    InboundDropOutcome,
    InboundVoiceRecord,
    MessageDirection,
    MessageStatus,
    VoicePayloadRecord,
)
from metor.shared import clean_onion


from .receipts import MessageReceiptStore


class MessageInboundMixin(MessageReceiptStore):
    """Owns inbound receipt, payload, unread, and LIVE-to-DROP transitions."""

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

    def matches_inbound_text(
        self, contact_onion: str, msg_id: str, payload: str
    ) -> bool:
        """Recognize an exact text retry after the inbound spool was consumed."""
        peer = clean_onion(contact_onion)
        with self._sql.transaction() as cursor:
            tag = self._inbound_text_tag(cursor, peer, msg_id, payload)
            return bool(
                cursor.execute(
                    'SELECT 1 FROM message_receipts WHERE peer_onion = ? AND direction = ? '
                    'AND msg_id = ? AND content_type = ? AND content_tag = ?',
                    (
                        peer,
                        MessageDirection.IN.value,
                        msg_id,
                        ContentType.TEXT.value,
                        tag,
                    ),
                ).fetchone()
            )

    def store_inbound_drop_text(
        self,
        contact_onion: str,
        msg_id: str,
        payload: str,
        timestamp: Optional[str],
        max_unread: int,
    ) -> InboundDropOutcome:
        """Creates or strengthens one inbound text identity to DROP semantics.

        Args:
            contact_onion (str): Authenticated peer identity.
            msg_id (str): Stable logical message identity.
            payload (str): Received text content.
            timestamp (Optional[str]): Authored timestamp.
            max_unread (int): Configured inbound DROP backlog ceiling.

        Returns:
            InboundDropOutcome: Created, duplicate, promoted, or conflict.
        """
        normalized_onion = clean_onion(contact_onion)
        created_at = timestamp or self._now()
        with self._sql.transaction() as cursor:
            receipt = self._get_receipt(
                normalized_onion, MessageDirection.IN, msg_id, cursor
            )
            tag = self._inbound_text_tag(cursor, normalized_onion, msg_id, payload)
            if receipt is not None:
                if (
                    receipt.content_type is not ContentType.TEXT
                    or not cursor.execute(
                        'SELECT 1 FROM message_receipts WHERE id = ? AND content_tag = ?',
                        (receipt.receipt_id, tag),
                    ).fetchone()
                ):
                    return InboundDropOutcome.CONFLICT
                if receipt.delivery is Delivery.DROP:
                    return InboundDropOutcome.DUPLICATE
            if max_unread >= 0:
                raw_count = cursor.execute(
                    'SELECT COUNT(*) FROM message_receipts WHERE peer_onion = ? AND direction = ? '
                    'AND delivery = ? AND status = ?',
                    (
                        normalized_onion,
                        MessageDirection.IN.value,
                        Delivery.DROP.value,
                        MessageStatus.UNREAD.value,
                    ),
                ).fetchall()[0][0]
                if int(str(raw_count)) >= max_unread:
                    return InboundDropOutcome.LIMIT
            if receipt is None:
                cursor.execute(
                    'INSERT INTO message_receipts '
                    '(msg_id, peer_onion, direction, delivery, content_type, retained_bytes, status, visible_in_history, created_at, updated_at, content_tag) '
                    'VALUES (?, ?, ?, ?, ?, 0, ?, 1, ?, ?, ?)',
                    (
                        msg_id,
                        normalized_onion,
                        MessageDirection.IN.value,
                        Delivery.DROP.value,
                        ContentType.TEXT.value,
                        MessageStatus.UNREAD.value,
                        created_at,
                        created_at,
                        tag,
                    ),
                )
                receipt_id = int(
                    str(cursor.execute('SELECT last_insert_rowid()').fetchall()[0][0])
                )
                cursor.execute(
                    'INSERT INTO inbound_spool (receipt_id, payload) VALUES (?, ?)',
                    (receipt_id, payload),
                )
                cursor.execute(
                    'INSERT INTO message_archive (receipt_id, payload) VALUES (?, ?)',
                    (receipt_id, payload),
                )
                return InboundDropOutcome.CREATED
            cursor.execute(
                'INSERT INTO inbound_spool (receipt_id, payload) VALUES (?, ?) '
                'ON CONFLICT(receipt_id) DO UPDATE SET payload = excluded.payload',
                (receipt.receipt_id, payload),
            )
            cursor.execute(
                'INSERT INTO message_archive (receipt_id, payload) VALUES (?, ?) '
                'ON CONFLICT(receipt_id) DO UPDATE SET payload = excluded.payload',
                (receipt.receipt_id, payload),
            )
            cursor.execute(
                'UPDATE message_receipts SET delivery = ?, status = ?, '
                'visible_in_history = 1, updated_at = ? WHERE id = ?',
                (
                    Delivery.DROP.value,
                    MessageStatus.UNREAD.value,
                    self._now(),
                    receipt.receipt_id,
                ),
            )
            return InboundDropOutcome.PROMOTED

    def get_inbound_voice(
        self, contact_onion: str, msg_id: str
    ) -> Optional[InboundVoiceRecord]:
        """Loads one inbound Voice receipt and its resumable spool metadata.

        Args:
            contact_onion (str): The contact onion input.
            msg_id (str): The msg id input.

        Returns:
            Optional[InboundVoiceRecord]: The resulting value.
        """
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

    def has_inbound_voice_receipt(self, contact_onion: str, msg_id: str) -> bool:
        """Reports whether a dedupe receipt belongs to inbound Voice content.

        Args:
            contact_onion (str): The contact onion input.
            msg_id (str): The msg id input.

        Returns:
            bool: Whether the documented condition holds.
        """
        receipt = self._get_receipt(
            clean_onion(contact_onion), MessageDirection.IN, msg_id
        )
        return receipt is not None and receipt.content_type is ContentType.VOICE

    def get_voice_payload(
        self,
        contact_onion: str,
        msg_id: str,
        direction: MessageDirection,
    ) -> Optional[VoicePayloadRecord]:
        """Loads one exact-direction Voice payload without exposing storage paths.

        Args:
            contact_onion (str): Peer onion identity.
            msg_id (str): Stable logical identity.
            direction (MessageDirection): Exact local direction.

        Returns:
            Optional[VoicePayloadRecord]: Owned Voice metadata when retained.
        """
        rows = self._sql.fetchall(
            'SELECT r.peer_onion, r.direction, r.delivery, '
            'COALESCE(i.payload, o.payload, a.payload), r.msg_id, r.status '
            'FROM message_receipts AS r '
            'LEFT JOIN inbound_spool AS i ON i.receipt_id = r.id '
            'LEFT JOIN outbox_spool AS o ON o.receipt_id = r.id '
            'LEFT JOIN message_archive AS a ON a.receipt_id = r.id '
            'WHERE r.peer_onion = ? AND r.msg_id = ? AND r.direction = ? '
            'AND r.content_type = ? AND COALESCE(i.payload, o.payload, a.payload) '
            'IS NOT NULL LIMIT 1',
            (
                clean_onion(contact_onion),
                msg_id,
                direction.value,
                ContentType.VOICE.value,
            ),
        )
        if not rows:
            return None
        row = rows[0]
        return VoicePayloadRecord(
            peer_onion=str(row[0]),
            direction=MessageDirection(str(row[1])),
            delivery=str(row[2]),
            payload=str(row[3]),
            msg_id=str(row[4]),
            status=str(row[5]),
        )

    def release_inbound_voice(
        self,
        contact_onion: str,
        msg_id: str,
        ephemeral_messages: bool,
    ) -> Optional[tuple[str, Delivery]]:
        """Consumes one finalized inbound Voice item after explicit handoff.

        Args:
            contact_onion (str): Peer onion identity.
            msg_id (str): Stable logical identity.
            ephemeral_messages (bool): Whether DROP archive content is removed.

        Returns:
            Optional[tuple[str, Delivery]]: Metadata and lifecycle on success.
        """
        with self._sql.transaction() as cursor:
            receipt = self._get_receipt(
                clean_onion(contact_onion), MessageDirection.IN, msg_id, cursor
            )
            if receipt is None or receipt.content_type is not ContentType.VOICE:
                return None
            rows = cursor.execute(
                'SELECT COALESCE(i.payload, a.payload) FROM message_receipts AS r '
                'LEFT JOIN inbound_spool AS i ON i.receipt_id = r.id '
                'LEFT JOIN message_archive AS a ON a.receipt_id = r.id '
                'WHERE r.id = ? AND COALESCE(i.payload, a.payload) IS NOT NULL',
                (receipt.receipt_id,),
            ).fetchall()
            if not rows:
                return None
            payload = str(rows[0][0])
            if not self._voice_payload_finalized(payload):
                return None
            cursor.execute(
                'UPDATE message_receipts SET status = ?, updated_at = ? WHERE id = ?',
                (MessageStatus.READ.value, self._now(), receipt.receipt_id),
            )
            cursor.execute(
                'DELETE FROM inbound_spool WHERE receipt_id = ?',
                (receipt.receipt_id,),
            )
            if receipt.delivery is Delivery.LIVE or ephemeral_messages:
                cursor.execute(
                    'DELETE FROM message_archive WHERE receipt_id = ?',
                    (receipt.receipt_id,),
                )
            return payload, receipt.delivery

    def get_unread_inbound_live_voices(self) -> List[InboundVoiceRecord]:
        """Loads crash-safe inbound LIVE Voice items still awaiting consume.

        Args:
            None

        Returns:
            List[InboundVoiceRecord]: The resulting value.
        """
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

    def get_unread_inbound_voices(self) -> List[InboundVoiceRecord]:
        """Loads every unread inbound Voice spool for recovery/reconciliation.

        Args:
            None

        Returns:
            List[InboundVoiceRecord]: Ordered LIVE and DROP Voice records.
        """
        rows = self._sql.fetchall(
            'SELECT r.id, r.peer_onion, r.delivery, i.payload, r.msg_id, '
            'r.created_at, r.retained_bytes, r.status FROM message_receipts AS r '
            'INNER JOIN inbound_spool AS i ON i.receipt_id = r.id '
            'WHERE r.direction = ? AND r.content_type = ? AND r.status = ? '
            'ORDER BY r.id ASC',
            (
                MessageDirection.IN.value,
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
