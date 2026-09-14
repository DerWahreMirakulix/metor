"""Non-consuming DROP archive projections and bounded identity-based paging."""

import json
from typing import List, Optional, Tuple, cast

from metor.core.api import Delivery
from metor.data.message.models import MessageDirection, StoredMessageRecord
from metor.data.sql.backends import SqlParam
from metor.utils import clean_onion

# Local Package Imports
from .receipts import MessageReceiptStore


class MessageArchiveMixin(MessageReceiptStore):
    """Owns archive reads independently of destructive consumption and deletion."""

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

    def get_chat_page(
        self,
        contact_onion: str,
        limit: int,
        max_payload_bytes: int,
        before_msg_id: Optional[str] = None,
        before_direction: Optional[MessageDirection] = None,
    ) -> tuple[List[StoredMessageRecord], bool, bool]:
        """Reads an older bounded page within one receipt-qualified transaction.

        Args:
            contact_onion: Exact resolved peer identity.
            limit: Validated page row ceiling.
            max_payload_bytes: Validated serialized row ceiling.
            before_msg_id: Optional exclusive message boundary.
            before_direction: Exact direction of the boundary receipt.
        Returns:
            tuple[List[StoredMessageRecord], bool, bool]: Chronological rows, older
                availability and whether the requested page can be represented.
        """
        onion = clean_onion(contact_onion)
        predicate = 'r.peer_onion = ? AND r.delivery = ? AND a.payload != ?'
        params: list[SqlParam] = [onion, Delivery.DROP.value, '']
        with self._sql.transaction() as cursor:
            if before_msg_id is not None and before_direction is not None:
                anchor = cast(
                    Optional[Tuple[SqlParam, ...]],
                    cursor.execute(
                        'SELECT created_at, id FROM message_receipts '
                        'WHERE peer_onion = ? AND direction = ? AND msg_id = ? '
                        'AND delivery = ?',
                        (
                            onion,
                            before_direction.value,
                            before_msg_id,
                            Delivery.DROP.value,
                        ),
                    ).fetchone(),
                )
                if anchor is None:
                    return [], False, False
                predicate += (
                    ' AND (r.created_at < ? OR (r.created_at = ? AND r.id < ?))'
                )
                params.extend([str(anchor[0]), str(anchor[0]), int(str(anchor[1]))])
            cursor.execute(
                'SELECT r.direction, r.status, a.payload, r.created_at, r.msg_id, r.content_type '
                'FROM message_receipts AS r '
                'INNER JOIN message_archive AS a ON a.receipt_id = r.id '
                'WHERE ' + predicate + ' ORDER BY r.created_at DESC, r.id DESC LIMIT ?',
                tuple(params + [limit + 1]),
            )
            records: List[StoredMessageRecord] = []
            used = 0
            more = False
            while raw := cursor.fetchone():
                row = cast(Tuple[SqlParam, ...], raw)
                size = len(json.dumps([str(value) for value in row]).encode('utf-8'))
                if len(records) == limit or used + size > max_payload_bytes:
                    more = True
                    break
                records.append(
                    StoredMessageRecord(
                        direction=str(row[0]),
                        status=str(row[1]),
                        payload=str(row[2]),
                        timestamp=str(row[3]),
                        msg_id=str(row[4]),
                        content_type=str(row[5]),
                    )
                )
                used += size
            records.reverse()
            return records, more, bool(records) or not more
