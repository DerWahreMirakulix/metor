"""Canonical typed SQL receipt collaborators shared by message operations."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import TYPE_CHECKING, List, Optional, Tuple, cast
from metor.core.api import ContentType, Delivery
from metor.data.message.models import MessageDirection, MessageStatus
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


class MessageReceiptStore:
    """Owns exact receipt lookup and common transaction primitives."""

    _sql: SqlManager

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
