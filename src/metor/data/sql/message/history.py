"""Message history projection and consumption."""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple, cast

from metor.core.api import ContentType, Delivery, is_valid_message_id
from metor.data.message.models import (
    MessageDirection,
    MessageStatus,
    UnreadInboxSummaryRecord,
)
from metor.data.sql.backends import SqlParam
from metor.shared import clean_onion


from .receipts import MessageReceiptStore


class MessageHistoryMixin(MessageReceiptStore):
    """Owns visible history reads and consume state."""

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

    def get_drop_conversation_summaries(self) -> List[Tuple[str, int, int]]:
        """Returns DROP conversation identities and unread counts without payloads.

        Args:
            None

        Returns:
            List[Tuple[str, int, int]]: Peer, unread and pending DROP counts in canonical activity order.
        """
        rows = self._sql.fetchall(
            'SELECT r.peer_onion, COALESCE(SUM(CASE WHEN r.direction = ? AND r.status = ? THEN 1 ELSE 0 END), 0), '
            'COALESCE(SUM(CASE WHEN r.direction = ? AND r.status = ? '
            'AND EXISTS(SELECT 1 FROM outbox_spool AS o WHERE o.receipt_id = r.id) '
            'THEN 1 ELSE 0 END), 0) '
            'FROM message_receipts AS r '
            'LEFT JOIN message_archive AS a ON a.receipt_id = r.id '
            'WHERE r.delivery = ? AND (a.receipt_id IS NOT NULL OR (r.status = ? '
            'AND EXISTS(SELECT 1 FROM outbox_spool AS o WHERE o.receipt_id = r.id))) '
            'GROUP BY r.peer_onion ORDER BY MAX(r.created_at) DESC, r.peer_onion ASC',
            (
                MessageDirection.IN.value,
                MessageStatus.UNREAD.value,
                MessageDirection.OUT.value,
                MessageStatus.PENDING.value,
                Delivery.DROP.value,
                MessageStatus.PENDING.value,
            ),
        )
        return [(str(row[0]), int(str(row[1])), int(str(row[2]))) for row in rows]

    def get_live_activity(self) -> Dict[str, str]:
        """Reads canonical retained LIVE receipt recency without selecting message payloads.

        Args:
            None
        Returns:
            Dict[str, str]: Peer-to-receipt update timestamp for unresolved LIVE work.
        """
        rows = self._sql.fetchall(
            'SELECT peer_onion, MAX(updated_at) FROM message_receipts '
            'WHERE delivery = ? AND ((direction = ? AND status = ?) '
            'OR (direction = ? AND status = ?)) GROUP BY peer_onion',
            (
                Delivery.LIVE.value,
                MessageDirection.IN.value,
                MessageStatus.UNREAD.value,
                MessageDirection.OUT.value,
                MessageStatus.PENDING.value,
            ),
        )
        return {str(row[0]): str(row[1]) for row in rows}

    def get_and_read_inbox(
        self,
        contact_onion: str,
        ephemeral_messages: bool,
        delivery: Optional[Delivery] = None,
        max_messages: Optional[int] = None,
        max_payload_bytes: Optional[int] = None,
    ) -> List[Tuple[int, str, str, str, Optional[str], str]]:
        """
        Retrieves unread inbox rows and applies consume semantics atomically.

        Args:
            contact_onion (str): The peer onion identity.
            ephemeral_messages (bool): Whether consumed drop payloads should be shredded.
            delivery (Optional[Delivery]): Optional delivery semantics filter.
            max_messages: Optional foreground handoff row ceiling.
            max_payload_bytes: Optional serialized row-content budget.

        Returns:
            List[Tuple[int, str, str, str, Optional[str], str]]: Unread rows with content type.
        """
        normalized_onion: str = clean_onion(contact_onion)
        delivery_filter = ''
        params: list[SqlParam] = [
            normalized_onion,
            MessageDirection.IN.value,
            MessageStatus.UNREAD.value,
            ContentType.TEXT.value,
        ]
        if delivery is not None:
            delivery_filter = ' AND r.delivery = ?'
            params.append(delivery.value)
        query = (
            'SELECT r.id, r.delivery, s.payload, r.created_at, r.msg_id, r.content_type '
            'FROM message_receipts AS r '
            'INNER JOIN inbound_spool AS s ON s.receipt_id = r.id '
            'WHERE r.peer_onion = ? AND r.direction = ? AND r.status = ? '
            'AND r.content_type = ?'
            f'{delivery_filter} '
            'ORDER BY r.created_at ASC, r.id ASC'
        )
        if max_messages is not None:
            query += ' LIMIT ?'
            params.append(max_messages)

        with self._sql.transaction() as cursor:
            cursor.execute(query, tuple(params))
            rows: List[Tuple[SqlParam, ...]] = []
            encoded_bytes = 0
            while raw := cursor.fetchone():
                row = cast(Tuple[SqlParam, ...], raw)
                size = len(json.dumps([str(value) for value in row]).encode('utf-8'))
                if (
                    max_payload_bytes is not None
                    and encoded_bytes + size > max_payload_bytes
                ):
                    break
                rows.append(row)
                encoded_bytes += size

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

    def get_drop_voice_payloads(
        self,
        onion: Optional[str] = None,
        non_contacts_only: bool = False,
        msg_id: Optional[str] = None,
        direction: Optional[MessageDirection] = None,
        include_pending: bool = False,
    ) -> List[str]:
        """Returns Voice metadata whose persistent blobs may be explicitly cleared.

        Pending outbound DROP rows are excluded unless cancellation is explicit.
        Their blobs remain delivery-critical when only visible history is cleared.

        Args:
            onion (Optional[str]): The onion input.
            non_contacts_only (bool): The non contacts only input.
            msg_id (Optional[str]): The msg id input.
            direction (Optional[MessageDirection]): The direction input.
            include_pending: Includes delivery-owned blobs during explicit cancellation.

        Returns:
            List[str]: The resulting value.
        """
        filters = [
            'r.delivery = ?',
            'r.content_type = ?',
        ]
        params: list[SqlParam] = [
            Delivery.DROP.value,
            ContentType.VOICE.value,
        ]
        if not include_pending:
            filters.append('NOT (r.direction = ? AND r.status = ?)')
            params.extend((MessageDirection.OUT.value, MessageStatus.PENDING.value))
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
        if direction is not None:
            filters.append('r.direction = ?')
            params.append(direction.value)
        where = ' AND '.join(filters)
        rows = self._sql.fetchall(
            'SELECT COALESCE(i.payload, a.payload, o.payload) '
            'FROM message_receipts AS r '
            'LEFT JOIN inbound_spool AS i ON i.receipt_id = r.id '
            'LEFT JOIN message_archive AS a ON a.receipt_id = r.id '
            'LEFT JOIN outbox_spool AS o ON o.receipt_id = r.id '
            f'WHERE {where} AND COALESCE(i.payload, a.payload, o.payload) IS NOT NULL '
            'AND r.status <> ? AND (r.direction <> ? OR a.receipt_id IS NOT NULL)',
            (*params, MessageStatus.DRAFT.value, MessageDirection.IN.value),
        )
        return [str(row[0]) for row in rows]

    def has_drop_payload(self, contact_onion: str, msg_id: str) -> bool:
        """Reports whether one DROP receipt still owns visible archive payload.

        Args:
            contact_onion (str): The contact onion input.
            msg_id (str): The msg id input.

        Returns:
            bool: Whether the documented condition holds.
        """
        rows = self._sql.fetchall(
            'SELECT 1 FROM message_receipts AS r '
            'INNER JOIN message_archive AS a ON a.receipt_id = r.id '
            'WHERE r.peer_onion = ? AND r.msg_id = ? AND r.delivery = ? LIMIT 1',
            (clean_onion(contact_onion), msg_id, Delivery.DROP.value),
        )
        return bool(rows)

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
