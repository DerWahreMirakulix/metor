"""
Module for managing mappings between user-friendly aliases and .onion addresses.
"""

import os
from typing import Tuple, Optional, List

from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.utils.helper import clean_onion, ensure_onion_format


class ContactManager:
    """Manages the database mapping between aliases and .onion addresses."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the ContactManager connected to the SQLite database.

        Args:
            pm (ProfileManager): The profile manager instance.
        """
        self._pm: ProfileManager = pm
        self._db_path: str = os.path.join(self._pm.get_config_dir(), Constants.DB_FILE)
        self._sql: SqlManager = SqlManager(self._db_path)

    def get_all_contacts(self) -> List[str]:
        """
        Retrieves a list of all permanently saved contact aliases.

        Returns:
            List[str]: A list of saved alias names.
        """
        query: str = 'SELECT alias FROM contacts WHERE is_saved = 1'
        rows: List[Tuple] = self._sql.fetchall(query)
        return [row[0] for row in rows]

    def is_session_alias(self, alias: str) -> bool:
        """
        Checks if an alias belongs to an auto-generated discovered peer.

        Args:
            alias (str): The alias to check.

        Returns:
            bool: True if it is an unsaved discovered peer.
        """
        alias = alias.strip().lower()
        query: str = 'SELECT is_saved FROM contacts WHERE alias = ?'
        res: List[Tuple] = self._sql.fetchall(query, (alias,))
        if res and res[0][0] == 0:
            return True
        return False

    def add_contact(self, alias: str, onion: str) -> Tuple[bool, str]:
        """
        Adds a new contact to the address book.

        Args:
            alias (str): The chosen name for the contact.
            onion (str): The remote onion identity.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        alias = alias.strip().lower()
        onion = clean_onion(onion)

        if self._sql.fetchall('SELECT onion FROM contacts WHERE alias = ?', (alias,)):
            return False, f"Alias '{alias}' is already in use."

        res: List[Tuple] = self._sql.fetchall(
            'SELECT alias FROM contacts WHERE onion = ? AND is_saved = 1', (onion,)
        )
        if res:
            return (
                False,
                f"The onion is already associated with saved contact '{res[0][0]}'.",
            )

        if self._sql.fetchall('SELECT alias FROM contacts WHERE onion = ?', (onion,)):
            self._sql.execute(
                'UPDATE contacts SET alias = ?, is_saved = 1 WHERE onion = ?',
                (alias, onion),
            )
        else:
            self._sql.execute(
                'INSERT INTO contacts (onion, alias, is_saved) VALUES (?, ?, 1)',
                (onion, alias),
            )

        return (
            True,
            f"Contact '{alias}' added successfully to profile '{self._pm.profile_name}'.",
        )

    def promote_discovered_peer(self, alias: str) -> Tuple[bool, str]:
        """
        Promotes a discovered peer to a permanent address book contact.

        Args:
            alias (str): The discovered alias to promote.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        alias = alias.strip().lower()
        res: List[Tuple] = self._sql.fetchall(
            'SELECT is_saved FROM contacts WHERE alias = ?', (alias,)
        )

        if not res:
            return False, f"Peer alias '{alias}' not found."
        if res[0][0] == 1:
            return False, f"Alias '{alias}' is already saved."

        self._sql.execute('UPDATE contacts SET is_saved = 1 WHERE alias = ?', (alias,))
        return True, f"Discovered peer '{alias}' saved permanently to address book."

    def rename_contact(self, old_alias: str, new_alias: str) -> Tuple[bool, str]:
        """
        Renames a contact or discovered peer dynamically.

        Args:
            old_alias (str): The current alias.
            new_alias (str): The desired new alias.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        old_alias = old_alias.strip().lower()
        new_alias = new_alias.strip().lower()

        if old_alias == new_alias:
            return False, 'The new alias must be different from the old one.'

        if self._sql.fetchall(
            'SELECT onion FROM contacts WHERE alias = ?', (new_alias,)
        ):
            return False, f"Alias '{new_alias}' is already in use."

        if not self._sql.fetchall(
            'SELECT onion FROM contacts WHERE alias = ?', (old_alias,)
        ):
            return False, f"Alias '{old_alias}' not found."

        self._sql.execute(
            'UPDATE contacts SET alias = ? WHERE alias = ?', (new_alias, old_alias)
        )
        return True, f"Alias renamed from '{old_alias}' to '{new_alias}'."

    def remove_contact(self, alias: str) -> Tuple[bool, str]:
        """
        Removes a saved contact. Refuses to delete discovered peers.

        Args:
            alias (str): The contact to remove.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        alias = alias.strip().lower()
        res: List[Tuple] = self._sql.fetchall(
            'SELECT is_saved FROM contacts WHERE alias = ?', (alias,)
        )

        if not res:
            return False, f"Contact '{alias}' not found."

        if res[0][0] == 0:
            return (
                False,
                'Discovered peers cannot be deleted manually as they are tied to message history.',
            )

        self._sql.execute(
            'DELETE FROM contacts WHERE alias = ? AND is_saved = 1', (alias,)
        )
        return (
            True,
            f"Contact '{alias}' removed from profile '{self._pm.profile_name}'.",
        )

    def clear_contacts(self) -> Tuple[bool, str]:
        """
        Wipes the address book, resets saved contacts to discovered peers,
        and anonymizes aliases for active onions in history/messages.

        Args:
            None

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        try:
            query: str = """
                SELECT DISTINCT onion FROM (
                    SELECT onion FROM history WHERE onion IS NOT NULL
                    UNION
                    SELECT contact_onion AS onion FROM messages
                )
            """
            rows: List[Tuple] = self._sql.fetchall(query)
            active_onions: List[str] = [r[0] for r in rows]

            self._sql.execute('DELETE FROM contacts')

            for onion in active_onions:
                self.get_alias_by_onion(onion)

            return (
                True,
                f"All contacts cleared and active peers anonymized for profile '{self._pm.profile_name}'.",
            )
        except Exception as e:
            return False, f'Failed to clear contacts: {e}'

    def resolve_target(
        self, target: Optional[str], default_value: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolves a generic target string into an (alias, onion) tuple.

        Args:
            target (Optional[str]): The target to resolve.
            default_value (Optional[str]): The fallback value if resolution fails.

        Returns:
            Tuple[Optional[str], Optional[str]]: A tuple containing the resolved alias and onion.
        """
        onion: Optional[str] = self.get_onion_by_alias(target)
        if not onion and target:
            onion = ensure_onion_format(target)
        alias: Optional[str] = self.get_alias_by_onion(onion)
        return (alias or default_value, onion or default_value)

    def get_onion_by_alias(self, alias: Optional[str]) -> Optional[str]:
        """Returns the onion address associated with an alias."""
        if not alias:
            return None
        alias = alias.strip().lower()

        res: List[Tuple] = self._sql.fetchall(
            'SELECT onion FROM contacts WHERE alias = ?', (alias,)
        )
        if res:
            return f'{res[0][0]}.onion'
        return None

    def get_alias_by_onion(self, onion: Optional[str]) -> Optional[str]:
        """
        Returns the alias for an onion, or auto-generates a discovered peer if unknown.

        Args:
            onion (Optional[str]): The onion address.

        Returns:
            Optional[str]: The mapped or generated alias.
        """
        if not onion:
            return None
        onion = clean_onion(onion)

        res: List[Tuple] = self._sql.fetchall(
            'SELECT alias FROM contacts WHERE onion = ?', (onion,)
        )
        if res:
            return res[0][0]

        if len(onion) == 56:
            base_alias: str = onion[:6]
            alias: str = base_alias
            counter: int = 1

            while self._sql.fetchall(
                'SELECT onion FROM contacts WHERE alias = ?', (alias,)
            ):
                counter += 1
                alias = f'{base_alias}{counter}'

            self._sql.execute(
                'INSERT INTO contacts (onion, alias, is_saved) VALUES (?, ?, 0)',
                (onion, alias),
            )
            return alias

        return None

    def show(self, chat_mode: bool = False) -> str:
        """
        Returns a formatted string of all address book contacts and discovered peers.

        Args:
            chat_mode (bool): Whether to format strictly for the chat UI.

        Returns:
            str: The formatted contacts list.
        """
        profile_suffix: str = (
            '' if chat_mode else f" for profile '{self._pm.profile_name}'"
        )
        lines: List[str] = []

        saved: List[Tuple] = self._sql.fetchall(
            'SELECT alias, onion FROM contacts WHERE is_saved = 1 ORDER BY alias ASC'
        )
        if saved:
            lines.append(f'Available contacts{profile_suffix}:')
            for row in saved:
                lines.append(f'   {Theme.GREEN}{row[0]}{Theme.RESET} -> {row[1]}')
        else:
            lines.append(f'No contacts in address book{profile_suffix}.')

        discovered: List[Tuple] = self._sql.fetchall(
            'SELECT alias, onion FROM contacts WHERE is_saved = 0 ORDER BY alias ASC'
        )
        if discovered:
            lines.append('\nDiscovered peers:')
            for row in discovered:
                lines.append(f'   {Theme.DARK_GREY}{row[0]}{Theme.RESET} -> {row[1]}')

        return '\n'.join(lines)
