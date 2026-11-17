"""Atomic local history deletion and exact queued-delivery cancellation.

Pending receipts survive without content after cancellation, recording an unknown
remote outcome without granting further emission authority.
"""

from typing import List, Optional, Tuple, cast

from metor.core.api import ContentType, Delivery, is_valid_message_id
from metor.data.message.models import (
    MessageDeleteOutcome,
    MessageDirection,
    MessageStatus,
    PendingLiveRecord,
)
from metor.data.sql.backends import SqlParam
from metor.shared import clean_onion

from .receipts import MessageReceiptStore


class MessageMutationMixin(MessageReceiptStore):
    """Owns explicitly requested local deletion in one durable transaction."""

    def discard_pending_live(
        self, contact_onion: str, msg_ids: list[str]
    ) -> list[PendingLiveRecord] | None:
        """Stops an exact queued LIVE selection and returns prior payload ownership.

        The caller must hold Core's shared operation lock and invalidate runtime
        emission generations before releasing it. Every identity must still be
        an own pending LIVE spool for this peer; stale selection changes nothing.
        Receipts retain unknown remote outcomes without content or retry authority.
        """
        if not msg_ids:
            return []
        if len(set(msg_ids)) != len(msg_ids) or any(
            not is_valid_message_id(msg_id) for msg_id in msg_ids
        ):
            return None
        normalized = clean_onion(contact_onion)
        block = self._placeholders(len(msg_ids))
        with self._sql.transaction() as cursor:
            rows = cursor.execute(
                'SELECT r.id, r.peer_onion, r.content_type, o.payload, r.msg_id, r.created_at '
                'FROM message_receipts AS r '
                'INNER JOIN outbox_spool AS o ON o.receipt_id = r.id '
                f'WHERE r.peer_onion = ? AND r.msg_id IN ({block}) '
                'AND r.direction = ? AND r.delivery = ? AND r.status = ?',
                (
                    normalized,
                    *msg_ids,
                    MessageDirection.OUT.value,
                    Delivery.LIVE.value,
                    MessageStatus.PENDING.value,
                ),
            ).fetchall()
            if len(rows) != len(msg_ids):
                return None
            records = [
                PendingLiveRecord(
                    int(str(row[0])),
                    str(row[1]),
                    str(row[2]),
                    str(row[3]),
                    str(row[4]),
                    str(row[5]),
                )
                for row in rows
            ]
            receipt_ids = [record.receipt_id for record in records]
            receipt_block = self._placeholders(len(receipt_ids))
            cursor.execute(
                f'DELETE FROM outbox_spool WHERE receipt_id IN ({receipt_block})',
                tuple(receipt_ids),
            )
            cursor.execute(
                f'DELETE FROM message_archive WHERE receipt_id IN ({receipt_block})',
                tuple(receipt_ids),
            )
            cursor.execute(
                'UPDATE message_receipts SET visible_in_history = 0, updated_at = ? '
                f'WHERE id IN ({receipt_block})',
                (self._now(), *receipt_ids),
            )
            return records

    def clear_messages(
        self,
        onion: Optional[str] = None,
        non_contacts_only: bool = False,
        cancel_pending: bool = False,
    ) -> tuple[tuple[str, str], ...]:
        """
        Clears only DROP payload/history state while retaining delivery receipts.

        Args:
            onion (Optional[str]): Optional peer onion filter.
            non_contacts_only (bool): Whether only discovered peers should be affected.
            cancel_pending: Stops queued DROP retries while retaining unknown receipts.

        Returns:
            tuple[tuple[str, str], ...]: Exact peer/message identities whose queue was stopped.
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
            pin_rows = cursor.execute(
                f'SELECT DISTINCT peer_onion FROM message_receipts WHERE {where}',
                tuple(params),
            ).fetchall()
            removed = {str(row[0]) for row in pin_rows}
            self._sql.metadata.prune_pins(cursor, removed)
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(
                    f'SELECT id, direction, status, peer_onion, msg_id FROM message_receipts WHERE {where} '
                    'AND status <> ? '
                    'AND NOT (content_type = ? AND direction = ? '
                    'AND NOT EXISTS (SELECT 1 FROM message_archive WHERE receipt_id = message_receipts.id))',
                    (
                        *params,
                        MessageStatus.DRAFT.value,
                        ContentType.VOICE.value,
                        MessageDirection.IN.value,
                    ),
                ).fetchall(),
            )
            if not rows:
                return ()
            receipt_ids = [int(str(row[0])) for row in rows]
            block = self._placeholders(len(receipt_ids))
            cursor.execute(
                f'DELETE FROM message_archive WHERE receipt_id IN ({block})',
                tuple(receipt_ids),
            )
            if cancel_pending:
                cursor.execute(
                    f'DELETE FROM outbox_spool WHERE receipt_id IN ({block}) '
                    'AND receipt_id IN (SELECT id FROM message_receipts '
                    'WHERE direction = ? AND status = ?)',
                    (
                        *receipt_ids,
                        MessageDirection.OUT.value,
                        MessageStatus.PENDING.value,
                    ),
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
            return tuple(
                (str(row[3]), str(row[4]))
                for row in rows
                if cancel_pending
                and str(row[1]) == MessageDirection.OUT.value
                and str(row[2]) == MessageStatus.PENDING.value
            )

    def delete_drop_message(
        self,
        contact_onion: str,
        msg_id: str,
        direction: Optional[MessageDirection] = None,
        cancel_pending: bool = False,
    ) -> MessageDeleteOutcome:
        """Deletes one local DROP payload while preserving the logical receipt.

        Args:
            contact_onion (str): Expected peer onion identity.
            msg_id (str): Stable logical message identifier.
            direction (Optional[MessageDirection]): Exact local row direction.
            cancel_pending: Stops an own queued DROP without recalling transmitted data.

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
                    'EXISTS(SELECT 1 FROM message_archive AS a WHERE a.receipt_id = r.id), '
                    'EXISTS(SELECT 1 FROM outbox_spool AS o WHERE o.receipt_id = r.id) '
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
            pending = (
                str(rows[0][2]) == MessageDirection.OUT.value
                and str(rows[0][3]) == MessageStatus.PENDING.value
            )
            if pending and not cancel_pending:
                return MessageDeleteOutcome.PENDING_DELIVERY
            if int(str(rows[0][4])) != 1 and not (
                pending and cancel_pending and int(str(rows[0][5])) == 1
            ):
                return MessageDeleteOutcome.NOT_FOUND
            if pending and cancel_pending:
                cursor.execute(
                    'DELETE FROM outbox_spool WHERE receipt_id = ?', (receipt_id,)
                )
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
