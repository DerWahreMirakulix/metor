"""Centralized raw transport history ledger helpers."""

from typing import TYPE_CHECKING, List, Optional, Tuple

from metor.utils import clean_onion

from metor.data.history.codes import (
    HistoryActor,
    HistoryEvent,
    HistoryFamily,
    HistoryReasonCode,
    HistoryTrigger,
)
from metor.data.history.models import HistoryLedgerEntry
from metor.data.sql.backends import SqlParam

if TYPE_CHECKING:
    from metor.data.sql.manager import SqlManager


class HistoryRepository:
    """Centralized raw transport history ledger helpers."""

    def __init__(self, sql: 'SqlManager') -> None:
        """
        Initializes the history repository.

        Args:
            sql (SqlManager): The owning SQL manager.

        Returns:
            None
        """
        self._sql: SqlManager = sql

    def log_entry(
        self,
        *,
        timestamp: str,
        family: HistoryFamily,
        event_code: HistoryEvent,
        peer_onion: Optional[str],
        actor: HistoryActor,
        trigger: Optional[str],
        detail_code: Optional[HistoryReasonCode],
        detail_text: str,
        flow_id: str,
    ) -> None:
        """
        Persists one raw transport history ledger row.

        Args:
            timestamp (str): The authored timestamp.
            family (HistoryFamily): The transport family.
            event_code (HistoryEvent): The raw event code.
            peer_onion (Optional[str]): The related peer onion identity.
            actor (HistoryActor): The actor causing the event.
            trigger (Optional[str]): Optional machine-readable trigger.
            detail_code (Optional[HistoryReasonCode]): Optional machine-readable detail code.
            detail_text (str): Optional diagnostic detail text.
            flow_id (str): The durable flow identifier.

        Returns:
            None
        """
        self._sql.execute(
            'INSERT INTO history_ledger '
            '(timestamp, family, event_code, peer_onion, actor, trigger, detail_code, detail_text, flow_id) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                timestamp,
                family.value,
                event_code.value,
                peer_onion,
                actor.value,
                trigger,
                detail_code.value if detail_code is not None else None,
                detail_text,
                flow_id,
            ),
        )

    @staticmethod
    def _entry_from_row(row: Tuple[SqlParam, ...]) -> HistoryLedgerEntry:
        """
        Casts one SQL row into one typed raw history entry.

        Args:
            row (Tuple[SqlParam, ...]): The raw SQL row.

        Returns:
            HistoryLedgerEntry: The typed history entry.
        """
        return HistoryLedgerEntry(
            timestamp=str(row[0]),
            family=HistoryFamily(str(row[1])),
            event_code=HistoryEvent(str(row[2])),
            peer_onion=str(row[3]) if row[3] is not None else None,
            actor=HistoryActor(str(row[4])),
            trigger=HistoryTrigger(str(row[5])) if row[5] is not None else None,
            detail_code=(
                HistoryReasonCode(str(row[6])) if row[6] is not None else None
            ),
            detail_text=str(row[7] or ''),
            flow_id=str(row[8]),
        )

    def get_entries(
        self,
        filter_onion: Optional[str],
        limit: Optional[int],
    ) -> List[HistoryLedgerEntry]:
        """
        Retrieves raw history entries ordered newest-first.

        Args:
            filter_onion (Optional[str]): Optional peer onion filter.
            limit (Optional[int]): Optional result limit.

        Returns:
            List[HistoryLedgerEntry]: Raw ledger entries.
        """
        params: Tuple[SqlParam, ...] = ()
        query = (
            'SELECT timestamp, family, event_code, peer_onion, actor, trigger, '
            'detail_code, detail_text, flow_id FROM history_ledger'
        )
        if filter_onion is not None:
            query += ' WHERE peer_onion = ?'
            params = (clean_onion(filter_onion),)

        query += ' ORDER BY timestamp DESC, id DESC'
        if limit is not None:
            query += ' LIMIT ?'
            params = params + (limit,)

        rows = self._sql.fetchall(query, params)
        return [self._entry_from_row(row) for row in rows]

    def clear(self, filter_onion: Optional[str] = None) -> None:
        """
        Clears history rows globally or for one peer.

        Args:
            filter_onion (Optional[str]): Optional peer onion filter.

        Returns:
            None
        """
        if filter_onion is not None:
            self._sql.execute(
                'DELETE FROM history_ledger WHERE peer_onion = ?',
                (clean_onion(filter_onion),),
            )
            return

        self._sql.execute('DELETE FROM history_ledger')
