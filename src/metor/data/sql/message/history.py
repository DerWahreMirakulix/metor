"""Message history projection, consumption, and deletion."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, cast

from metor.core.api import ContentType, Delivery, is_valid_message_id
from metor.data.message.models import (
    MessageDeleteOutcome,
    MessageDirection,
    MessageStatus,
    StoredMessageRecord,
    UnreadInboxSummaryRecord,
)
from metor.data.sql.backends import SqlParam
from metor.utils import clean_onion


class MessageHistoryMixin:
    """Owns visible history reads, read state, and scoped deletion."""

    def __getattr__(self, name: str) -> Any:
        """Defers typed collaborator attributes to the composed repository."""
        raise AttributeError(name)

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
        direction: Optional[MessageDirection] = None,
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
        if direction is not None:
            filters.append('r.direction = ?')
            params.append(direction.value)
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
        self,
        contact_onion: str,
        msg_id: str,
        direction: Optional[MessageDirection] = None,
    ) -> MessageDeleteOutcome:
        """Deletes one local DROP payload while preserving the logical receipt.

        Args:
            contact_onion (str): Expected peer onion identity.
            msg_id (str): Stable logical message identifier.
            direction (Optional[MessageDirection]): Exact local row direction.

        Returns:
            MessageDeleteOutcome: Typed operation outcome.
        """
        normalized_onion = clean_onion(contact_onion)
        if not is_valid_message_id(msg_id):
            return MessageDeleteOutcome.NOT_FOUND
        with self._sql.transaction() as cursor:
            direction_filter = ''
            params: list[SqlParam] = [normalized_onion, msg_id]
            if direction is not None:
                direction_filter = ' AND r.direction = ?'
                params.append(direction.value)
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(
                    'SELECT r.id, r.delivery, r.direction, r.status, '
                    'EXISTS(SELECT 1 FROM message_archive AS a WHERE a.receipt_id = r.id) '
                    'FROM message_receipts AS r '
                    f'WHERE peer_onion = ? AND msg_id = ?{direction_filter}',
                    tuple(params),
                ).fetchall(),
            )
            if not rows:
                return MessageDeleteOutcome.NOT_FOUND
            if len(rows) > 1:
                return MessageDeleteOutcome.AMBIGUOUS_IDENTITY
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
