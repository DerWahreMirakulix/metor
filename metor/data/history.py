"""
Module for managing chat and connection history logs via SQLite.
"""

from enum import Enum
from pathlib import Path
from typing import List, Tuple, Optional

from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.utils.helper import get_divider_string, get_header_string

# Local Package Imports
from metor.data.profile import ProfileManager
from metor.data.contact import ContactManager
from metor.data.sql import SqlManager


class HistoryEvent(str, Enum):
    """Predefined event types for the history log."""

    ASYNC_QUEUED = 'async_queued'
    ASYNC_SENT = 'async_sent'
    ASYNC_RECEIVED = 'async_received'
    ASYNC_FAILED = 'async_failed'

    REQUESTED = 'requested'
    REQUESTED_BY_REMOTE = 'requested_by_remote'
    CONNECTED = 'connected'
    REJECTED = 'rejected'
    REJECTED_BY_REMOTE = 'rejected_by_remote'
    DISCONNECTED = 'disconnected'
    DISCONNECTED_BY_REMOTE = 'disconnected_by_remote'
    CONNECTION_LOST = 'connection_lost'


class HistoryManager:
    """Manages connection history logging using an SQLite database."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the HistoryManager and its underlying SqlManager.

        Args:
            pm (ProfileManager): The profile manager instance for context.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._db_path: Path = Path(self._pm.get_config_dir()) / Constants.DB_FILE
        self._sql: SqlManager = SqlManager(self._db_path)

    def log_event(
        self, status: HistoryEvent, onion: Optional[str], reason: str = ''
    ) -> None:
        """
        Logs a connection event into the database.

        Args:
            status (HistoryEvent): The event type to log.
            onion (Optional[str]): The associated remote onion identity.
            reason (str): Optional context for the event.

        Returns:
            None
        """
        query: str = 'INSERT INTO history (status, onion, reason) VALUES (?, ?, ?)'
        self._sql.execute(query, (status.value, onion, reason))

    def get_history(
        self, filter_onion: Optional[str] = None
    ) -> List[Tuple[str, str, Optional[str], str]]:
        """
        Retrieves raw history events from the database.

        Args:
            filter_onion (Optional[str]): The specific onion to filter by.

        Returns:
            List[Tuple[str, str, Optional[str], str]]: List of events (timestamp, status, onion, reason).
        """
        if filter_onion:
            query: str = 'SELECT timestamp, status, onion, reason FROM history WHERE onion = ? ORDER BY timestamp DESC'
            return self._sql.fetchall(query, (filter_onion,))
        else:
            query: str = 'SELECT timestamp, status, onion, reason FROM history ORDER BY timestamp DESC'
            return self._sql.fetchall(query)

    def clear_history(self, filter_onion: Optional[str] = None) -> Tuple[bool, str]:
        """
        Wipes event logs from the history table and removes orphaned discovered peers.

        Args:
            filter_onion (Optional[str]): The target onion identity. If None, deletes all.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        try:
            if filter_onion:
                self._sql.execute(
                    'DELETE FROM history WHERE onion = ?', (filter_onion,)
                )
                msg = f"History for '{filter_onion}' cleared."
            else:
                self._sql.execute('DELETE FROM history')
                msg = f"History for profile '{self._pm.profile_name}' cleared."

            cleanup_query: str = """
                DELETE FROM contacts 
                WHERE is_saved = 0 
                AND onion NOT IN (SELECT onion FROM history WHERE onion IS NOT NULL)
                AND onion NOT IN (SELECT contact_onion FROM messages)
            """
            self._sql.execute(cleanup_query)

            return True, msg
        except Exception:
            return False, 'Failed to clear history.'

    def show(self, cm: ContactManager, target: Optional[str] = None) -> str:
        """
        Fetches history and constructs a human-readable string for terminal display.

        Args:
            cm (ContactManager): The contact manager for resolving aliases.
            target (Optional[str]): The target CLI argument (alias or onion).

        Returns:
            str: The formatted event history output.
        """
        onion = None
        disp_name = f'profile {Theme.CYAN}{self._pm.profile_name}{Theme.RESET}'

        if target:
            alias, onion, exists = cm.resolve_target(target)
            if not exists:
                return f"Contact '{target}' not found."
            disp_name = f'contact {Theme.CYAN}{alias}{Theme.RESET}'

        rows: List[Tuple[str, str, Optional[str], str]] = self.get_history(onion)

        if not rows:
            return f'No event history available for {disp_name}.'

        out: str = f'{get_header_string(f"Event history for {disp_name}")}\n'

        for row in rows:
            timestamp, status, row_onion, reason = row
            display_alias: str = (
                cm.get_alias_by_onion(row_onion) if row_onion else 'Unknown'
            )

            line: str = f'[{timestamp}] {Theme.CYAN}{status}{Theme.RESET} | remote alias: {Theme.CYAN}{display_alias}{Theme.RESET} | remote identity: {Theme.YELLOW}{row_onion}{Theme.RESET}'
            if reason:
                line += f' | reason: {Theme.CYAN}{reason}{Theme.RESET}'

            out += f'{line}\n'

        out += get_divider_string()
        return out
