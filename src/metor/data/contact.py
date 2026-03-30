"""
Module for managing mappings between user-friendly aliases and .onion addresses.
Maintains data integrity without applying UI presentation formatting.
"""

from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any

from metor.core.api import TransCode
from metor.utils import Constants, clean_onion

# Local Package Imports
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager


class ContactManager:
    """Manages the database mapping between aliases and .onion addresses."""

    def __init__(self, pm: ProfileManager, password: Optional[str] = None) -> None:
        """
        Initializes the ContactManager connected to the SQLite database.

        Args:
            pm (ProfileManager): The profile manager instance.
            password (Optional[str]): The master password for SQLCipher encryption.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._db_path: Path = Path(self._pm.get_config_dir()) / Constants.DB_FILE
        self._sql: SqlManager = SqlManager(self._db_path, password)

    def get_all_contacts(self) -> List[str]:
        """
        Retrieves a list of all permanently saved contact aliases.

        Args:
            None

        Returns:
            List[str]: A list of saved alias names.
        """
        query: str = 'SELECT alias FROM contacts WHERE is_saved = 1'
        rows: List[Tuple[Any, ...]] = self._sql.fetchall(query)
        return [str(row[0]) for row in rows]

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
        res: List[Tuple[Any, ...]] = self._sql.fetchall(query, (alias,))
        if res and res[0][0] == 0:
            return True
        return False

    def add_contact(
        self, alias: str, onion: str
    ) -> Tuple[bool, TransCode, Dict[str, Any]]:
        """
        Adds a new contact to the address book.

        Args:
            alias (str): The chosen name for the contact.
            onion (str): The remote onion identity.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any]]: A success flag, domain state code, and parameters.
        """
        alias = alias.strip().lower()
        onion = clean_onion(onion)

        if self._sql.fetchall('SELECT onion FROM contacts WHERE alias = ?', (alias,)):
            return False, TransCode.ALIAS_IN_USE, {'alias': alias}

        res: List[Tuple[Any, ...]] = self._sql.fetchall(
            'SELECT alias FROM contacts WHERE onion = ? AND is_saved = 1', (onion,)
        )
        if res:
            return (
                False,
                TransCode.ONION_IN_USE,
                {'alias': str(res[0][0])},
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

        # We intentionally don't resolve the alias since it is dynamically inserted in the UI
        return (
            True,
            TransCode.CONTACT_ADDED,
            {'alias': alias, 'profile': self._pm.profile_name},
        )

    def promote_discovered_peer(
        self, alias: str
    ) -> Tuple[bool, TransCode, Dict[str, Any]]:
        """
        Promotes a discovered peer to a permanent address book contact.

        Args:
            alias (str): The discovered alias to promote.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any]]: A success flag, domain state code, and parameters.
        """
        alias = alias.strip().lower()
        res: List[Tuple[Any, ...]] = self._sql.fetchall(
            'SELECT is_saved FROM contacts WHERE alias = ?', (alias,)
        )

        if not res:
            return False, TransCode.PEER_NOT_FOUND, {'target': alias}
        if res[0][0] == 1:
            return False, TransCode.CONTACT_ALREADY_SAVED, {'alias': alias}

        self._sql.execute('UPDATE contacts SET is_saved = 1 WHERE alias = ?', (alias,))

        # We intentionally don't resolve the alias since it is dynamically inserted in the UI
        return True, TransCode.PEER_PROMOTED, {'alias': alias}

    def rename_contact(
        self, old_alias: str, new_alias: str
    ) -> Tuple[bool, TransCode, Dict[str, Any]]:
        """
        Renames a contact or discovered peer dynamically.

        Args:
            old_alias (str): The current alias.
            new_alias (str): The desired new alias.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any]]: A success flag, domain state code, and parameters.
        """
        old_alias = old_alias.strip().lower()
        new_alias = new_alias.strip().lower()

        if old_alias == new_alias:
            return False, TransCode.ALIAS_SAME, {}

        if self._sql.fetchall(
            'SELECT onion FROM contacts WHERE alias = ?', (new_alias,)
        ):
            return False, TransCode.ALIAS_IN_USE, {'alias': new_alias}

        if not self._sql.fetchall(
            'SELECT onion FROM contacts WHERE alias = ?', (old_alias,)
        ):
            return False, TransCode.ALIAS_NOT_FOUND, {'alias': old_alias}

        self._sql.execute(
            'UPDATE contacts SET alias = ? WHERE alias = ?', (new_alias, old_alias)
        )
        return (
            True,
            TransCode.ALIAS_RENAMED,
            {'old_alias': old_alias, 'new_alias': new_alias},
        )

    def remove_contact(
        self, alias: str, active_onions: Optional[List[str]] = None
    ) -> Tuple[bool, TransCode, Dict[str, Any], List[Tuple[str, str, bool]], List[str]]:
        """
        Removes a saved contact or anonymizes a renamed discovered peer.
        Refuses to physically delete peers tied to active states, demotes instead.

        Args:
            alias (str): The contact to remove.
            active_onions (Optional[List[str]]): Currently connected onions functioning as a shield.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any], List[Tuple[str, str, bool]], List[str]]: A success flag, state code, params, UI renames, and UI deletions.
        """
        active_onions = active_onions or []
        alias = alias.strip().lower()
        res: List[Tuple[Any, ...]] = self._sql.fetchall(
            'SELECT is_saved, onion FROM contacts WHERE alias = ?', (alias,)
        )

        if not res:
            return False, TransCode.PEER_NOT_FOUND, {'target': alias}, [], []

        is_saved, onion = res[0]
        was_saved: bool = is_saved == 1

        has_hist = self._sql.fetchall(
            'SELECT 1 FROM history WHERE onion = ? LIMIT 1', (onion,)
        )
        has_msgs = self._sql.fetchall(
            'SELECT 1 FROM messages WHERE contact_onion = ? LIMIT 1', (onion,)
        )

        if onion in active_onions or has_hist or has_msgs:
            new_alias: str = self._generate_ram_alias(str(onion))

            # If the current alias already matches the generated hash alias, it's fully anonymized.
            if new_alias == alias:
                if was_saved:
                    self._sql.execute(
                        'UPDATE contacts SET is_saved = 0 WHERE alias = ?', (alias,)
                    )
                    return True, TransCode.CONTACT_DOWNGRADED, {'alias': alias}, [], []
                else:
                    return (
                        False,
                        TransCode.PEER_CANT_DELETE_ACTIVE,
                        {'alias': alias},
                        [],
                        [],
                    )

            self._sql.execute(
                'UPDATE contacts SET is_saved = 0, alias = ? WHERE alias = ?',
                (new_alias, alias),
            )

            if was_saved:
                return (
                    True,
                    TransCode.CONTACT_REMOVED_DOWNGRADED,
                    {'alias': alias, 'new_alias': new_alias},
                    [(alias, new_alias, was_saved)],
                    [],
                )
            else:
                return (
                    True,
                    TransCode.PEER_ANONYMIZED,
                    {'alias': alias, 'new_alias': new_alias},
                    [(alias, new_alias, was_saved)],
                    [],
                )
        else:
            self._sql.execute('DELETE FROM contacts WHERE alias = ?', (alias,))

            if was_saved:
                return (
                    True,
                    TransCode.CONTACT_REMOVED,
                    {'alias': alias, 'profile': self._pm.profile_name},
                    [],
                    [alias],
                )
            else:
                return True, TransCode.PEER_REMOVED, {'alias': alias}, [], [alias]

    def clear_contacts(
        self, active_onions: Optional[List[str]] = None
    ) -> Tuple[bool, TransCode, Dict[str, Any], List[Tuple[str, str, bool]], List[str]]:
        """
        Wipes the address book, demoting saved contacts to discovered peers if they
        are still tied to history, messages, or active network connections.

        Args:
            active_onions (Optional[List[str]]): Currently connected onions functioning as a shield.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any], List[Tuple[str, str, bool]], List[str]]: A success flag, state code, params, UI renames, and UI deletions.
        """
        active_onions = active_onions or []
        try:
            saved: List[Tuple[Any, ...]] = self._sql.fetchall(
                'SELECT alias, onion FROM contacts WHERE is_saved = 1'
            )
            renames: List[Tuple[str, str, bool]] = []
            removed: List[str] = []

            for raw_alias, raw_onion in saved:
                alias = str(raw_alias)
                onion = str(raw_onion)

                has_hist = self._sql.fetchall(
                    'SELECT 1 FROM history WHERE onion = ? LIMIT 1', (onion,)
                )
                has_msgs = self._sql.fetchall(
                    'SELECT 1 FROM messages WHERE contact_onion = ? LIMIT 1', (onion,)
                )

                if onion in active_onions or has_hist or has_msgs:
                    new_alias: str = self._generate_ram_alias(onion)
                    self._sql.execute(
                        'UPDATE contacts SET is_saved = 0, alias = ? WHERE onion = ?',
                        (new_alias, onion),
                    )
                    # All elements fetched here are was_saved=True
                    renames.append((alias, new_alias, True))
                else:
                    self._sql.execute('DELETE FROM contacts WHERE onion = ?', (onion,))
                    removed.append(alias)

            return (
                True,
                TransCode.CONTACTS_CLEARED,
                {'profile': self._pm.profile_name},
                renames,
                removed,
            )
        except Exception:
            return False, TransCode.CONTACTS_CLEAR_FAILED, {}, [], []

    def cleanup_orphans(self, active_onions: Optional[List[str]] = None) -> List[str]:
        """
        Executes a zero-trace wipe of all temporary peers that no longer have a
        live connection, chat history, or pending messages. Returns deleted aliases.

        Args:
            active_onions (Optional[List[str]]): Active Tor connection onions to preserve.

        Returns:
            List[str]: List of cleanly removed aliases for UI sync.
        """
        active_onions = active_onions or []
        placeholders: str = ', '.join(['?'] * len(active_onions))
        condition = f'AND onion NOT IN ({placeholders})' if active_onions else ''
        params = tuple(active_onions) if active_onions else ()

        query_select: str = f"""
            SELECT alias FROM contacts 
            WHERE is_saved = 0 
            AND onion NOT IN (SELECT onion FROM history WHERE onion IS NOT NULL)
            AND onion NOT IN (SELECT contact_onion FROM messages)
            {condition}
        """
        rows: List[Tuple[Any, ...]] = self._sql.fetchall(query_select, params)
        deleted_aliases: List[str] = [str(r[0]) for r in rows]

        if deleted_aliases:
            query_delete: str = f"""
                DELETE FROM contacts 
                WHERE is_saved = 0 
                AND onion NOT IN (SELECT onion FROM history WHERE onion IS NOT NULL)
                AND onion NOT IN (SELECT contact_onion FROM messages)
                {condition}
            """
            self._sql.execute(query_delete, params)

        return deleted_aliases

    def resolve_target(
        self,
        target: Optional[str],
        default_value: Optional[str] = None,
        auto_create: bool = False,
    ) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Resolves a generic target string into an (alias, onion) tuple.

        Args:
            target (Optional[str]): The target to resolve (alias or onion).
            default_value (Optional[str]): The fallback value if resolution fails.
            auto_create (bool): If True, automatically creates a discovered peer RAM alias if
                                the target is a valid, unknown onion address.

        Returns:
            Tuple[Optional[str], Optional[str], bool]: A tuple containing the resolved alias,
            clean onion, and existence flag. If exists is True, both alias and onion are
            guaranteed to be non-None valid strings.
        """
        onion: Optional[str] = self.get_onion_by_alias(target)
        # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
        if not onion and target:
            onion = clean_onion(target)
        alias: Optional[str] = self.get_alias_by_onion(onion, auto_create=auto_create)
        return (
            (alias, onion, True)
            if alias and onion
            else (default_value, default_value, False)
        )

    def get_onion_by_alias(self, alias: Optional[str]) -> Optional[str]:
        """
        Returns the raw, clean onion address associated with an alias.

        Args:
            alias (Optional[str]): The alias to resolve.

        Returns:
            Optional[str]: The mapped 56-character string.
        """
        if not alias:
            return None
        alias = alias.strip().lower()

        res: List[Tuple[Any, ...]] = self._sql.fetchall(
            'SELECT onion FROM contacts WHERE alias = ?', (alias,)
        )
        if res:
            return str(res[0][0])
        return None

    def _generate_ram_alias(self, onion: str) -> str:
        """
        Generates a unique default alias from an onion string preventing collisions.

        Args:
            onion (str): The onion address.

        Returns:
            str: The auto-generated alias.
        """
        base_alias: str = clean_onion(onion)[:6]
        alias: str = base_alias
        counter: int = 1
        while self._sql.fetchall(
            'SELECT onion FROM contacts WHERE alias = ? AND onion != ?', (alias, onion)
        ):
            counter += 1
            alias = f'{base_alias}{counter}'
        return alias

    def get_alias_by_onion(
        self, onion: Optional[str], auto_create: bool = True
    ) -> Optional[str]:
        """
        Returns the alias for an onion, or auto-generates a discovered peer if unknown.

        Args:
            onion (Optional[str]): The onion address.
            auto_create (bool): Whether to generate a temporary alias if it doesn't exist.

        Returns:
            Optional[str]: The mapped or generated alias.
        """
        if not onion:
            return None
        onion = clean_onion(onion)

        res: List[Tuple[Any, ...]] = self._sql.fetchall(
            'SELECT alias FROM contacts WHERE onion = ?', (onion,)
        )
        if res:
            return str(res[0][0])

        if len(onion) == 56 and auto_create:
            alias: str = self._generate_ram_alias(onion)
            self._sql.execute(
                'INSERT INTO contacts (onion, alias, is_saved) VALUES (?, ?, 0)',
                (onion, alias),
            )
            return alias

        return None

    def get_contacts_data(self) -> Dict[str, Any]:
        """
        Retrieves raw contacts data for UI presentation.

        Args:
            None

        Returns:
            Dict[str, Any]: Dictionary containing 'saved', 'discovered', and 'profile' data.
        """
        saved: List[Tuple[Any, ...]] = self._sql.fetchall(
            'SELECT alias, onion FROM contacts WHERE is_saved = 1 ORDER BY alias ASC'
        )
        discovered: List[Tuple[Any, ...]] = self._sql.fetchall(
            'SELECT alias, onion FROM contacts WHERE is_saved = 0 ORDER BY alias ASC'
        )
        return {
            'saved': [(str(row[0]), str(row[1])) for row in saved],
            'discovered': [(str(row[0]), str(row[1])) for row in discovered],
            'profile': self._pm.profile_name,
        }
