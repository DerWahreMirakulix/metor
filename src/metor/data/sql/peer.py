"""Centralized peer alias persistence helpers."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional, Tuple, cast

from metor.utils import clean_onion

from metor.data.sql.backends import SqlParam

if TYPE_CHECKING:
    from metor.data.sql.manager import SqlManager


@dataclass(frozen=True)
class PeerRow:
    """Represents one persisted peer alias row."""

    onion: str
    alias: str
    is_saved: bool


class PeerRepository:
    """Centralized peer-alias persistence helpers."""

    def __init__(self, sql: 'SqlManager') -> None:
        """
        Initializes the peer repository.

        Args:
            sql (SqlManager): The owning SQL manager.

        Returns:
            None
        """
        self._sql: SqlManager = sql

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
            alias (str): The normalized alias.

        Returns:
            Optional[PeerRow]: The matching row, if present.
        """
        rows = self._sql.fetchall(
            'SELECT onion, alias, alias_state FROM peers WHERE alias = ?',
            (alias,),
        )
        if not rows:
            return None
        return self._to_row(rows[0])

    def get_by_onion(self, onion: str) -> Optional[PeerRow]:
        """
        Retrieves one peer row by onion identity.

        Args:
            onion (str): The normalized onion identity.

        Returns:
            Optional[PeerRow]: The matching row, if present.
        """
        rows = self._sql.fetchall(
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
        rows = self._sql.fetchall(
            "SELECT alias FROM peers WHERE alias_state = 'saved' ORDER BY alias ASC"
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
        rows = self._sql.fetchall(
            "SELECT onion, alias, alias_state FROM peers WHERE alias_state = 'saved' ORDER BY alias ASC"
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
        rows = self._sql.fetchall(
            "SELECT onion, alias, alias_state FROM peers WHERE alias_state = 'discovered' ORDER BY alias ASC"
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
        self._sql.execute(
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
        self._sql.execute(
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
        self._sql.execute(
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
        self._sql.execute(
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
        self._sql.execute('DELETE FROM peers WHERE alias = ?', (alias,))

    def delete_by_onion(self, onion: str) -> None:
        """
        Deletes one peer row by onion identity.

        Args:
            onion (str): The normalized onion identity.

        Returns:
            None
        """
        self._sql.execute('DELETE FROM peers WHERE onion = ?', (onion,))

    def has_references(self, onion: str) -> bool:
        """
        Checks whether one peer still has durable history or message references.

        Args:
            onion (str): The normalized onion identity.

        Returns:
            bool: True when the peer still has stored references.
        """
        history_rows = self._sql.fetchall(
            'SELECT 1 FROM history_ledger WHERE peer_onion = ? LIMIT 1',
            (onion,),
        )
        if history_rows:
            return True

        message_rows = self._sql.fetchall(
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

        with self._sql.transaction() as cursor:
            rows = cast(
                List[Tuple[SqlParam, ...]],
                cursor.execute(select_query, params).fetchall(),
            )
            deleted_peers: List[Tuple[str, str]] = [
                (str(row[0]), str(row[1])) for row in rows
            ]
            if deleted_peers:
                cursor.execute(delete_query, params)

        return deleted_peers
