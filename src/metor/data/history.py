"""
Module for managing chat and connection history logs via SQLite.
Enforces Data-at-Rest policies and Zero-Trace architecture.
Yields raw domain models without applying CLI format dependencies.
"""

from enum import Enum
from pathlib import Path
from typing import List, Tuple, Optional, Dict

from metor.core.api import DomainCode, DbCode
from metor.utils import Constants, clean_onion

# Local Package Imports
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager, SqlParam
from metor.data.settings import SettingKey


class HistoryEvent(str, Enum):
    """Predefined event types for the history log."""

    # Async / Drops
    DROP_QUEUED = 'drop_queued'
    DROP_SENT = 'drop_sent'
    DROP_RECEIVED = 'drop_received'
    DROP_FAILED = 'drop_failed'

    # Drop Tunneling
    DROP_TUNNEL_CONNECTED = 'drop_tunnel_connected'
    DROP_TUNNEL_FAILED = 'drop_tunnel_failed'
    DROP_TUNNEL_CLOSED = 'drop_tunnel_closed'

    # Live Connections
    LIVE_REQUESTED = 'live_requested'
    LIVE_REQUESTED_BY_REMOTE = 'live_requested_by_remote'
    LIVE_CONNECTED = 'live_connected'
    LIVE_REJECTED = 'live_rejected'
    LIVE_REJECTED_BY_REMOTE = 'live_rejected_by_remote'
    LIVE_DISCONNECTED = 'live_disconnected'
    LIVE_DISCONNECTED_BY_REMOTE = 'live_disconnected_by_remote'
    LIVE_CONNECTION_LOST = 'live_connection_lost'
    TIEBREAKER_REJECTED = 'tiebreaker_rejected'

    # Network Resilience
    LIVE_CONNECTION_TIMEOUT = 'live_connection_timeout'
    LIVE_AUTO_RECONNECT_ATTEMPT = 'live_auto_reconnect_attempt'
    LIVE_AUTO_RECONNECT_FAILED = 'live_auto_reconnect_failed'
    LIVE_RETUNNEL_INITIATED = 'live_retunnel_initiated'
    LIVE_RETUNNEL_SUCCESS = 'live_retunnel_success'
    LIVE_REJECTED_MAX_CONNECTIONS = 'live_rejected_max_connections'
    LIVE_STREAM_CORRUPTED = 'live_stream_corrupted'

    @property
    def is_drop(self) -> bool:
        """
        Determines if the event is related to asynchronous messaging drops.

        Args:
            None

        Returns:
            bool: True if the event is a drop type, False otherwise.
        """
        return self.value.startswith('drop_')

    @property
    def is_live(self) -> bool:
        """
        Determines if the event is related to live connections.

        Args:
            None

        Returns:
            bool: True if the event is a live type, False otherwise.
        """
        return self.value.startswith('live_')


class HistoryManager:
    """Manages connection history logging using an SQLite database."""

    def __init__(self, pm: ProfileManager, password: Optional[str] = None) -> None:
        """
        Initializes the HistoryManager and its underlying SqlManager.

        Args:
            pm (ProfileManager): The profile manager instance for context.
            password (Optional[str]): The master password for SQLCipher encryption.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._db_path: Path = Path(self._pm.get_config_dir()) / Constants.DB_FILE
        self._sql: SqlManager = SqlManager(self._db_path, self._pm.config, password)

    def log_event(
        self, status: HistoryEvent, onion: Optional[str], reason: str = ''
    ) -> None:
        """
        Logs a connection event into the database. Bypasses logging entirely
        if the respective record_events policy is disabled, enforcing a Zero-Trace state.

        Args:
            status (HistoryEvent): The event type to log.
            onion (Optional[str]): The associated remote onion identity.
            reason (str): Optional context for the event.

        Returns:
            None
        """
        if status.is_drop:
            if not self._pm.config.get_bool(SettingKey.RECORD_DROP_EVENTS):
                return
        else:
            if not self._pm.config.get_bool(SettingKey.RECORD_LIVE_EVENTS):
                return

        onion = clean_onion(onion) if onion else None
        query: str = 'INSERT INTO history (status, onion, reason) VALUES (?, ?, ?)'
        self._sql.execute(query, (status.value, onion, reason))

    def get_history(
        self, filter_onion: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Tuple[str, str, Optional[str], str]]:
        """
        Retrieves raw history events from the database.

        Args:
            filter_onion (Optional[str]): The specific onion to filter by.
            limit (Optional[int]): The maximum number of events to retrieve.

        Returns:
            List[Tuple[str, str, Optional[str], str]]: List of events (timestamp, status, onion, reason).
        """
        actual_limit: int = (
            limit
            if limit is not None
            else self._pm.config.get_int(SettingKey.HISTORY_LIMIT)
        )
        if filter_onion:
            query: str = 'SELECT timestamp, status, onion, reason FROM history WHERE onion = ? ORDER BY timestamp DESC LIMIT ?'
            rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
                query, (filter_onion, actual_limit)
            )
        else:
            global_query: str = 'SELECT timestamp, status, onion, reason FROM history ORDER BY timestamp DESC LIMIT ?'
            rows = self._sql.fetchall(global_query, (actual_limit,))

        return [
            (
                str(r[0]),
                str(r[1]),
                str(r[2]) if r[2] is not None else None,
                str(r[3] or ''),
            )
            for r in rows
        ]

    def clear_history(
        self, filter_onion: Optional[str] = None
    ) -> Tuple[bool, DomainCode, Dict[str, str]]:
        """
        Wipes event logs from the history table strictly maintaining domain boundaries.

        Args:
            filter_onion (Optional[str]): The target onion identity. If None, deletes all.

        Returns:
            Tuple[bool, DomainCode, Dict[str, str]]: A success flag, domain state code, and parameters.
        """
        try:
            if filter_onion:
                self._sql.execute(
                    'DELETE FROM history WHERE onion = ?', (filter_onion,)
                )
                return True, DbCode.HISTORY_CLEARED, {'target': filter_onion}
            else:
                self._sql.execute('DELETE FROM history')
                return (
                    True,
                    DbCode.HISTORY_CLEARED_ALL,
                    {'profile': self._pm.profile_name},
                )

        except Exception:
            return False, DbCode.HISTORY_CLEAR_FAILED, {}

    def update_alias(self, old_alias: str, new_alias: str) -> None:
        """
        No-op method kept for API compatibility, since history is strictly indexed by onion.

        Args:
            old_alias (str): The old alias.
            new_alias (str): The new alias.

        Returns:
            None
        """
        pass
