"""
Module for managing chat and connection history logs via SQLite.
"""

import os
from typing import List, Tuple, Optional

from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.utils.constants import Constants


class HistoryManager:
    """Manages chat and connection history logging using an SQLite database."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the HistoryManager and its underlying SqlManager.

        Args:
            pm (ProfileManager): The profile manager instance for context.
        """
        self._pm: ProfileManager = pm
        self._db_path: str = os.path.join(self._pm.get_config_dir(), Constants.DB_FILE)
        self._sql: SqlManager = SqlManager(self._db_path)

    def log_event(
        self, status: str, alias: Optional[str], onion: Optional[str], reason: str = ''
    ) -> None:
        """
        Logs a connection or chat event into the database.

        Args:
            status (str): The status or type of event.
            alias (Optional[str]): The associated remote alias.
            onion (Optional[str]): The associated remote onion identity.
            reason (str): Optional context or reason for the event.
        """
        query: str = (
            'INSERT INTO history (status, alias, onion, reason) VALUES (?, ?, ?, ?)'
        )
        self._sql.execute(query, (status, alias, onion, reason))

    def read_history(self) -> List[str]:
        """
        Reads all history events from the database and formats them for display.

        Returns:
            List[str]: A list of formatted history string lines ordered by newest first.
        """
        # We order by timestamp DESC to get the newest entries first, matching the old logic.
        query: str = 'SELECT timestamp, status, alias, onion, reason FROM history ORDER BY timestamp DESC'
        rows: List[Tuple] = self._sql.fetchall(query)

        lines: List[str] = []
        for row in rows:
            timestamp, status, alias, onion, reason = row
            line: str = f'[{timestamp}] {status} | remote alias: {alias} | remote identity: {onion}'
            if reason:
                line += f' | reason: {reason}'
            lines.append(line)
        return lines

    def clear_history(self) -> Tuple[bool, str]:
        """
        Wipes all event logs from the history table.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        try:
            query: str = 'DELETE FROM history'
            self._sql.execute(query)
            return True, f"History from profile '{self._pm.profile_name}' cleared."
        except Exception as e:
            return (
                False,
                f"Failed to clear history for profile '{self._pm.profile_name}': {str(e)}",
            )

    def update_alias(self, old_alias: str, new_alias: str) -> bool:
        """
        Updates the alias name for past records in the history logs.

        Args:
            old_alias (str): The current alias to search for.
            new_alias (str): The new alias to replace the old one.

        Returns:
            bool: True if the update query executed successfully, False otherwise.
        """
        try:
            query: str = 'UPDATE history SET alias = ? WHERE alias = ?'
            self._sql.execute(query, (new_alias, old_alias))
            return True
        except Exception:
            return False

    def show(self) -> str:
        """
        Fetches and constructs the complete history view as a single string.

        Returns:
            str: The multi-line formatted history output.
        """
        history_lines: List[str] = self.read_history()
        if not history_lines:
            return f"No history available for profile '{self._pm.profile_name}'."

        lines: List[str] = [f"History for profile '{self._pm.profile_name}':\n"]
        for line in history_lines:
            lines.append(line)

        return '\n'.join(lines)
