"""Centralized peer alias persistence helpers."""

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterator, List, Optional, Tuple, cast

from metor.shared import clean_onion

from metor.data.sql.backends import SqlCipherCursor, SqlParam

if TYPE_CHECKING:
    from metor.data.sql.manager import SqlManager


def compare_aliases(left: str, right: str) -> int:
    """Compares Unicode display labels without changing their persisted spelling.

    Args:
        left: First persisted or requested display alias.
        right: Second persisted or requested display alias.
    Returns:
        int: Case-insensitive SQL comparison result.
    """
    first, second = left.casefold(), right.casefold()
    return (first > second) - (first < second)


@dataclass(frozen=True)
class PeerRow:
    """Represents one persisted peer alias row."""

    onion: str
    alias: str
    is_saved: bool


class PeerRepository:
    """Centralized peer-alias persistence helpers."""

    def __init__(
        self, sql: 'SqlManager', *, cursor: Optional[SqlCipherCursor] = None
    ) -> None:
        """
        Initializes the peer repository.

        Args:
            sql (SqlManager): The owning SQL manager.
            cursor: Existing transaction cursor for an atomic alias operation.

        Returns:
            None
        """
        self._sql: SqlManager = sql
        self._cursor = cursor

    @contextmanager
    def alias_mutation(self) -> Iterator['PeerRepository']:
        """Keeps alias identity checks and writes in one existing SQL transaction.

        Args:
            None
        Yields:
            PeerRepository: Cursor-bound helpers under the shared persistence lock.
        """
        with self._transaction() as cursor:
            yield PeerRepository(self._sql, cursor=cursor)

    @contextmanager
    def _transaction(self) -> Iterator[SqlCipherCursor]:
        """Reuses a bound transaction without nesting connection commits or locks.

        Args:
            None
        Yields:
            SqlCipherCursor: Existing or newly opened atomic SQL cursor.
        """
        if self._cursor is not None:
            yield self._cursor
        else:
            with self._sql.transaction() as cursor:
                yield cursor

    def _fetchall(
        self, query: str, params: Tuple[SqlParam, ...] = ()
    ) -> List[Tuple[SqlParam, ...]]:
        """Reads through the bound cursor while preserving the ordinary repository API.

        Args:
            query: Parameterized peer query.
            params: Bound SQL values.
        Returns:
            List[Tuple[SqlParam, ...]]: Matching typed rows.
        """
        if self._cursor is None:
            return self._sql.fetchall(query, params)
        return cast(
            List[Tuple[SqlParam, ...]], self._cursor.execute(query, params).fetchall()
        )

    def _execute(self, query: str, params: Tuple[SqlParam, ...] = ()) -> None:
        """Writes without committing a cursor-bound alias operation prematurely.

        Args:
            query: Parameterized peer mutation.
            params: Bound SQL values.
        Returns:
            None
        """
        if self._cursor is None:
            self._sql.execute(query, params)
        else:
            self._cursor.execute(query, params)

    @staticmethod
    def _to_row(row: Tuple[SqlParam, ...]) -> PeerRow:
        """
        Casts one SQL row into one typed peer row.

        Args:
            row (Tuple[SqlParam, ...]): The raw SQL row.

        Returns:
            PeerRow: The typed peer row.
        """
        return PeerRow(
            onion=str(row[0]),
            alias=str(row[1]),
            is_saved=str(row[2]) == 'saved',
        )

    def get_by_alias(self, alias: str) -> Optional[PeerRow]:
        """
        Retrieves one peer row by alias.

        Args:
            alias (str): The display alias, compared case-insensitively.

        Returns:
            Optional[PeerRow]: The matching row, if present.
        """
        rows = self._fetchall(
            'SELECT onion, alias, alias_state FROM peers WHERE alias = ? COLLATE METOR_ALIAS',
            (alias,),
        )
        if len(rows) == 1:
            return self._to_row(rows[0])
        # Older profiles can contain distinct labels that Unicode casefold now
        # considers equal. Preserve exact resolution; never choose a random peer.
        return next((self._to_row(row) for row in rows if row[1] == alias), None)

    def alias_is_taken(self, alias: str, except_onion: str = '') -> bool:
        """Checks all equivalent labels while permitting a peer's own case-only rename.

        Args:
            alias: Requested display label.
            except_onion: Exact identity allowed to retain its equivalent label.
        Returns:
            bool: Whether another persisted peer occupies the requested label.
        """
        return bool(
            self._fetchall(
                'SELECT 1 FROM peers WHERE alias = ? COLLATE METOR_ALIAS AND onion <> ? LIMIT 1',
                (alias, except_onion),
            )
        )

    def get_by_onion(self, onion: str) -> Optional[PeerRow]:
        """
        Retrieves one peer row by onion identity.

        Args:
            onion (str): The normalized onion identity.

        Returns:
            Optional[PeerRow]: The matching row, if present.
        """
        rows = self._fetchall(
            'SELECT onion, alias, alias_state FROM peers WHERE onion = ?',
            (onion,),
        )
        if not rows:
            return None
        return self._to_row(rows[0])

    def list_saved_aliases(self) -> List[str]:
        """
        Returns all saved aliases ordered for UI presentation.

        Args:
            None

        Returns:
            List[str]: All saved aliases.
        """
        rows = self._fetchall(
            "SELECT alias FROM peers WHERE alias_state = 'saved' ORDER BY alias COLLATE METOR_ALIAS ASC"
        )
        return [str(row[0]) for row in rows]

    def list_saved(self) -> List[PeerRow]:
        """
        Returns all saved peers.

        Args:
            None

        Returns:
            List[PeerRow]: Saved peer rows ordered by alias.
        """
        rows = self._fetchall(
            "SELECT onion, alias, alias_state FROM peers WHERE alias_state = 'saved' ORDER BY alias COLLATE METOR_ALIAS ASC"
        )
        return [self._to_row(row) for row in rows]

    def list_discovered(self) -> List[PeerRow]:
        """
        Returns all discovered peers.

        Args:
            None

        Returns:
            List[PeerRow]: Discovered peer rows ordered by alias.
        """
        rows = self._fetchall(
            "SELECT onion, alias, alias_state FROM peers WHERE alias_state = 'discovered' ORDER BY alias COLLATE METOR_ALIAS ASC"
        )
        return [self._to_row(row) for row in rows]

    def insert(self, onion: str, alias: str, is_saved: bool) -> None:
        """
        Inserts one new peer row.

        Args:
            onion (str): The peer onion identity.
            alias (str): The peer alias.
            is_saved (bool): Whether the peer is saved or discovered.

        Returns:
            None
        """
        timestamp: str = datetime.now(timezone.utc).isoformat()
        self._execute(
            'INSERT INTO peers (onion, alias, alias_state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
            (
                onion,
                alias,
                'saved' if is_saved else 'discovered',
                timestamp,
                timestamp,
            ),
        )

    def update_alias(self, onion: str, alias: str) -> None:
        """
        Updates one peer alias while preserving saved/discovered state.

        Args:
            onion (str): The peer onion identity.
            alias (str): The new alias.

        Returns:
            None
        """
        self._execute(
            'UPDATE peers SET alias = ?, updated_at = ? WHERE onion = ?',
            (alias, datetime.now(timezone.utc).isoformat(), onion),
        )

    def update_saved(self, onion: str, is_saved: bool) -> None:
        """
        Updates one peer state without renaming it.

        Args:
            onion (str): The peer onion identity.
            is_saved (bool): The desired saved flag.

        Returns:
            None
        """
        self._execute(
            'UPDATE peers SET alias_state = ?, updated_at = ? WHERE onion = ?',
            (
                'saved' if is_saved else 'discovered',
                datetime.now(timezone.utc).isoformat(),
                onion,
            ),
        )

    def update_alias_and_saved(self, onion: str, alias: str, is_saved: bool) -> None:
        """
        Updates both alias and saved/discovered state for one peer.

        Args:
            onion (str): The peer onion identity.
            alias (str): The new alias.
            is_saved (bool): The desired saved flag.

        Returns:
            None
        """
        self._execute(
            'UPDATE peers SET alias = ?, alias_state = ?, updated_at = ? WHERE onion = ?',
            (
                alias,
                'saved' if is_saved else 'discovered',
                datetime.now(timezone.utc).isoformat(),
                onion,
            ),
        )

    def delete_by_alias(self, alias: str) -> None:
        """
        Deletes one peer row by alias.

        Args:
            alias (str): The normalized alias.

        Returns:
            None
        """
        with self._transaction() as cursor:
            cursor.execute('SELECT onion FROM peers WHERE alias = ?', (alias,))
            row = cursor.fetchone()
            if isinstance(row, tuple) and isinstance(row[0], str):
                self._sql.metadata.prune_pins(cursor, {row[0]})
            cursor.execute('DELETE FROM peers WHERE alias = ?', (alias,))

    def delete_by_onion(self, onion: str) -> None:
        """
        Deletes one peer row by onion identity.

        Args:
            onion (str): The normalized onion identity.

        Returns:
            None
        """
        with self._transaction() as cursor:
            self._sql.metadata.prune_pins(cursor, {onion})
            cursor.execute('DELETE FROM peers WHERE onion = ?', (onion,))

    def has_references(self, onion: str) -> bool:
        """
        Checks whether one peer still has durable history or message references.

        Args:
            onion (str): The normalized onion identity.

        Returns:
            bool: True when the peer still has stored references.
        """
        history_rows = self._fetchall(
            'SELECT 1 FROM history_ledger WHERE peer_onion = ? LIMIT 1',
            (onion,),
        )
        if history_rows:
            return True

        message_rows = self._fetchall(
            'SELECT 1 FROM message_receipts WHERE peer_onion = ? LIMIT 1',
            (onion,),
        )
        return bool(message_rows)

    def cleanup_orphans(
        self,
        active_onions: Optional[List[str]] = None,
    ) -> List[Tuple[str, str]]:
        """
        Deletes discovered peers without durable references or active connections.

        Args:
            active_onions (Optional[List[str]]): Currently active onions to preserve.

        Returns:
            List[Tuple[str, str]]: Removed alias/onion pairs.
        """
        active_onions = [clean_onion(onion) for onion in (active_onions or [])]
        condition: str = ''
        params: Tuple[SqlParam, ...] = ()
        if active_onions:
            placeholders = ', '.join('?' for _ in active_onions)
            condition = f'AND onion NOT IN ({placeholders})'
            params = tuple(active_onions)

        select_query = f"""
            SELECT alias, onion FROM peers
            WHERE alias_state = 'discovered'
              AND onion NOT IN (
                  SELECT peer_onion FROM history_ledger WHERE peer_onion IS NOT NULL
              )
              AND onion NOT IN (
                  SELECT peer_onion FROM message_receipts
              )
              {condition}
            ORDER BY alias ASC
        """
        delete_query = f"""
            DELETE FROM peers
            WHERE alias_state = 'discovered'
              AND onion NOT IN (
                  SELECT peer_onion FROM history_ledger WHERE peer_onion IS NOT NULL
              )
              AND onion NOT IN (
                  SELECT peer_onion FROM message_receipts
              )
              {condition}
        """

        with self._transaction() as cursor:
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(select_query, params).fetchall(),
            )
            deleted_peers: List[Tuple[str, str]] = [
                (str(row[0]), str(row[1])) for row in rows
            ]
            if deleted_peers:
                self._sql.metadata.prune_pins(
                    cursor, {onion for _alias, onion in deleted_peers}
                )
                cursor.execute(delete_query, params)

        return deleted_peers
