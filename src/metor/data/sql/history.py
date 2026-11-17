"""Centralized raw transport history ledger helpers."""

from typing import TYPE_CHECKING, List, Optional, Tuple, cast

from metor.shared import clean_onion
from metor.utils import Constants

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
        transport: Optional[str] = None,
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
            transport (Optional[str]): Optional transport channel label.

        Returns:
            None
        """
        self._sql.execute(
            'INSERT INTO history_ledger '
            '(timestamp, family, event_code, peer_onion, actor, trigger, detail_code, detail_text, flow_id, transport) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
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
                transport,
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
            transport=str(row[9]) if row[9] is not None else None,
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
            'detail_code, detail_text, flow_id, transport FROM history_ledger'
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

    def get_page(
        self, filter_onion: Optional[str], page_size: int, before_id: Optional[int]
    ) -> tuple[list[HistoryLedgerEntry], Optional[int], bool, bool]:
        """Reads one bounded metadata page with an atomically validated anchor.

        Args:
            filter_onion: Optional canonical peer filter.
            page_size: Maximum raw rows inspected, validated by the public DTO.
            before_id: Exclusive ledger identity, or the newest page.
        Returns:
            tuple: Rows, next anchor, older-row flag and anchor availability.
        """
        if not 1 <= page_size <= Constants.HISTORY_PAGE_MAX_ITEMS:
            raise ValueError('Invalid history page size')
        conditions: list[str] = []
        params: tuple[SqlParam, ...] = ()
        if filter_onion is not None:
            conditions.append('peer_onion = ?')
            params += (clean_onion(filter_onion),)
        with self._sql.transaction() as cursor:
            if before_id is not None:
                cursor.execute(
                    'SELECT timestamp, peer_onion FROM history_ledger WHERE id = ?',
                    (before_id,),
                )
                anchor = cast(Optional[tuple[SqlParam, ...]], cursor.fetchone())
                if anchor is None or (
                    filter_onion is not None and anchor[1] != clean_onion(filter_onion)
                ):
                    return [], None, False, False
                conditions.append('(timestamp < ? OR (timestamp = ? AND id < ?))')
                params += (anchor[0], anchor[0], before_id)
            # Paged metadata excludes free-form diagnostic text at the SQL boundary.
            # Bounded scalar columns prevent legacy diagnostic data expanding a page.
            columns = (
                'timestamp',
                'family',
                'event_code',
                'peer_onion',
                'actor',
                'trigger',
                'detail_code',
                'flow_id',
                'transport',
            )
            selected = ', '.join('substr(' + name + ', 1, ?)' for name in columns)
            query = 'SELECT id, ' + selected + ' FROM history_ledger'
            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
            query += ' ORDER BY timestamp DESC, id DESC LIMIT ?'
            cursor.execute(
                query,
                (Constants.HISTORY_METADATA_MAX_CHARS,) * len(columns)
                + params
                + (page_size + 1,),
            )
            rows = cast(list[tuple[SqlParam, ...]], cursor.fetchall())
        selected_rows = rows[:page_size]
        entries = [
            self._entry_from_row(tuple(row[1:8]) + ('',) + tuple(row[8:]))
            for row in selected_rows
        ]
        has_older = len(rows) > page_size
        next_id = (
            int(str(selected_rows[-1][0])) if has_older and selected_rows else None
        )
        return entries, next_id, has_older, True

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
