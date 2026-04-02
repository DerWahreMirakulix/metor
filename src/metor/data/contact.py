"""
Module for managing mappings between user-friendly aliases and .onion addresses.
Maintains data integrity without applying UI presentation formatting.
"""

from pathlib import Path
from typing import Tuple, Optional, List, Dict, Union

from metor.core.api import EventType
from metor.utils import clean_onion

# Local Package Imports
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager, SqlParam


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
        self._db_path: Path = self._pm.paths.get_db_file()
        self._sql: SqlManager = SqlManager(self._db_path, self._pm.config, password)

    def get_all_contacts(self) -> List[str]:
        """
        Retrieves a list of all permanently saved contact aliases.

        Args:
            None

        Returns:
            List[str]: A list of saved alias names.
        """
        query: str = 'SELECT alias FROM contacts WHERE is_saved = 1'
        rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(query)
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
        res: List[Tuple[SqlParam, ...]] = self._sql.fetchall(query, (alias,))
        if res and res[0][0] == 0:
            return True
        return False

    def add_contact(
        self, alias: str, onion: str
    ) -> Tuple[bool, EventType, Dict[str, str]]:
        """
        Adds a new contact to the address book.

        Args:
            alias (str): The chosen name for the contact.
            onion (str): The remote onion identity.

        Returns:
            Tuple[bool, EventType, Dict[str, str]]: A success flag, strict event type, and payload.
        """
        alias = alias.strip().lower()
        onion = clean_onion(onion)

        if self._sql.fetchall('SELECT onion FROM contacts WHERE alias = ?', (alias,)):
            return False, EventType.ALIAS_IN_USE, {'alias': alias, 'onion': onion}

        res: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            'SELECT alias FROM contacts WHERE onion = ? AND is_saved = 1', (onion,)
        )
        if res:
            return (
                False,
                EventType.ONION_IN_USE,
                {'alias': str(res[0][0]), 'onion': onion},
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
            EventType.CONTACT_ADDED,
            {'alias': alias, 'onion': onion, 'profile': self._pm.profile_name},
        )

    def promote_discovered_peer(
        self, alias: str
    ) -> Tuple[bool, EventType, Dict[str, str]]:
        """
        Promotes a discovered peer to a permanent address book contact.

        Args:
            alias (str): The discovered alias to promote.

        Returns:
            Tuple[bool, EventType, Dict[str, str]]: A success flag, strict event type, and payload.
        """
        alias = alias.strip().lower()
        res: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            'SELECT is_saved FROM contacts WHERE alias = ?', (alias,)
        )

        if not res:
            return False, EventType.PEER_NOT_FOUND, {'target': alias}

        onion: Optional[str] = self.get_onion_by_alias(alias)
        if res[0][0] == 1:
            params: Dict[str, str] = {'alias': alias}
            if onion:
                params['onion'] = onion
            return False, EventType.CONTACT_ALREADY_SAVED, params

        self._sql.execute('UPDATE contacts SET is_saved = 1 WHERE alias = ?', (alias,))

        # We intentionally don't resolve the alias since it is dynamically inserted in the UI
        params = {'alias': alias}
        if onion:
            params['onion'] = onion
        return True, EventType.PEER_PROMOTED, params

    def rename_contact(
        self, old_alias: str, new_alias: str
    ) -> Tuple[bool, EventType, Dict[str, str]]:
        """
        Renames a contact or discovered peer dynamically.

        Args:
            old_alias (str): The current alias.
            new_alias (str): The desired new alias.

        Returns:
            Tuple[bool, EventType, Dict[str, str]]: A success flag, strict event type, and payload.
        """
        old_alias = old_alias.strip().lower()
        new_alias = new_alias.strip().lower()

        if old_alias == new_alias:
            return False, EventType.ALIAS_SAME, {}

        onion: Optional[str] = self.get_onion_by_alias(old_alias)

        if self._sql.fetchall(
            'SELECT onion FROM contacts WHERE alias = ?', (new_alias,)
        ):
            params: Dict[str, str] = {'alias': new_alias}
            if onion:
                params['onion'] = onion
            return False, EventType.ALIAS_IN_USE, params

        if not self._sql.fetchall(
            'SELECT onion FROM contacts WHERE alias = ?', (old_alias,)
        ):
            return False, EventType.ALIAS_NOT_FOUND, {'alias': old_alias}

        self._sql.execute(
            'UPDATE contacts SET alias = ? WHERE alias = ?', (new_alias, old_alias)
        )
        result_params: Dict[str, str] = {
            'old_alias': old_alias,
            'new_alias': new_alias,
        }
        if onion:
            result_params['onion'] = onion
        return (
            True,
            EventType.ALIAS_RENAMED,
            result_params,
        )

    def remove_contact(
        self, alias: str, active_onions: Optional[List[str]] = None
    ) -> Tuple[
        bool,
        EventType,
        Dict[str, str],
        List[Tuple[str, str, str, bool]],
        List[Tuple[str, str]],
    ]:
        """
        Removes a saved contact or anonymizes a renamed discovered peer.
        Refuses to physically delete peers tied to active states, demotes instead.

        Args:
            alias (str): The contact to remove.
            active_onions (Optional[List[str]]): Currently connected onions functioning as a shield.

        Returns:
            Tuple[bool, EventType, Dict[str, str], List[Tuple[str, str, str, bool]], List[Tuple[str, str]]]: A success flag, strict event type, payload, UI renames, and UI deletions.
        """
        active_onions = active_onions or []
        alias = alias.strip().lower()
        res: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            'SELECT is_saved, onion FROM contacts WHERE alias = ?', (alias,)
        )

        if not res:
            return False, EventType.PEER_NOT_FOUND, {'target': alias}, [], []

        is_saved, raw_onion = res[0]
        onion = str(raw_onion)
        was_saved: bool = is_saved == 1

        has_hist = self._sql.fetchall(
            'SELECT 1 FROM history WHERE onion = ? LIMIT 1', (onion,)
        )
        has_msgs = self._sql.fetchall(
            'SELECT 1 FROM messages WHERE contact_onion = ? LIMIT 1', (onion,)
        )

        if onion in active_onions or has_hist or has_msgs:
            new_alias: str = self._generate_ram_alias(onion)

            # If the current alias already matches the generated hash alias, it's fully anonymized.
            if new_alias == alias:
                if was_saved:
                    self._sql.execute(
                        'UPDATE contacts SET is_saved = 0 WHERE alias = ?', (alias,)
                    )
                    return (
                        True,
                        EventType.CONTACT_DOWNGRADED,
                        {'alias': alias, 'onion': onion},
                        [],
                        [],
                    )
                else:
                    return (
                        False,
                        EventType.PEER_CANT_DELETE_ACTIVE,
                        {'alias': alias, 'onion': onion},
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
                    EventType.CONTACT_REMOVED_DOWNGRADED,
                    {'alias': alias, 'new_alias': new_alias, 'onion': onion},
                    [(alias, new_alias, onion, was_saved)],
                    [],
                )
            else:
                return (
                    True,
                    EventType.PEER_ANONYMIZED,
                    {'alias': alias, 'new_alias': new_alias, 'onion': onion},
                    [(alias, new_alias, onion, was_saved)],
                    [],
                )
        else:
            self._sql.execute('DELETE FROM contacts WHERE alias = ?', (alias,))

            if was_saved:
                return (
                    True,
                    EventType.CONTACT_REMOVED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'profile': self._pm.profile_name,
                    },
                    [],
                    [(alias, onion)],
                )
            else:
                return (
                    True,
                    EventType.PEER_REMOVED,
                    {'alias': alias, 'onion': onion},
                    [],
                    [(alias, onion)],
                )

    def clear_contacts(
        self, active_onions: Optional[List[str]] = None
    ) -> Tuple[
        bool,
        EventType,
        Dict[str, str],
        List[Tuple[str, str, str, bool]],
        List[Tuple[str, str]],
    ]:
        """
        Wipes the address book, demoting saved contacts to discovered peers if they
        are still tied to history, messages, or active network connections.

        Args:
            active_onions (Optional[List[str]]): Currently connected onions functioning as a shield.

        Returns:
            Tuple[bool, EventType, Dict[str, str], List[Tuple[str, str, str, bool]], List[Tuple[str, str]]]: A success flag, strict event type, payload, UI renames, and UI deletions.
        """
        active_onions = active_onions or []
        try:
            saved: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
                'SELECT alias, onion FROM contacts WHERE is_saved = 1'
            )
            renames: List[Tuple[str, str, str, bool]] = []
            removed: List[Tuple[str, str]] = []

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
                    renames.append((alias, new_alias, onion, True))
                else:
                    self._sql.execute('DELETE FROM contacts WHERE onion = ?', (onion,))
                    removed.append((alias, onion))

            return (
                True,
                EventType.CONTACTS_CLEARED,
                {'profile': self._pm.profile_name},
                renames,
                removed,
            )
        except Exception:
            return False, EventType.CONTACTS_CLEAR_FAILED, {}, [], []

    def cleanup_orphans(
        self, active_onions: Optional[List[str]] = None
    ) -> List[Tuple[str, str]]:
        """
        Executes a zero-trace wipe of all temporary peers that no longer have a
        live connection, chat history, or pending messages. Returns deleted peers.

        Args:
            active_onions (Optional[List[str]]): Active Tor connection onions to preserve.

        Returns:
            List[Tuple[str, str]]: List of removed alias/onion pairs for UI sync.
        """
        active_onions = active_onions or []

        # AUDIT EXCEPTION: SQLite IN-clauses with dynamic list sizes do not support static parameterization.
        # F-Strings are used exclusively to inject the correct amount of '?' placeholders.
        # Actual values are passed safely via the 'params' tuple to prevent SQL injection.
        placeholders: str = ', '.join(['?'] * len(active_onions))
        condition = f'AND onion NOT IN ({placeholders})' if active_onions else ''
        params = tuple(active_onions) if active_onions else ()

        query_select: str = f"""
            SELECT alias, onion FROM contacts 
            WHERE is_saved = 0 
            AND onion NOT IN (SELECT onion FROM history WHERE onion IS NOT NULL)
            AND onion NOT IN (SELECT contact_onion FROM messages)
            {condition}
        """
        rows: List[Tuple[SqlParam, ...]] = self._sql.fetchall(query_select, params)
        deleted_peers: List[Tuple[str, str]] = [
            (str(row[0]), str(row[1])) for row in rows
        ]

        if deleted_peers:
            query_delete: str = f"""
                DELETE FROM contacts 
                WHERE is_saved = 0 
                AND onion NOT IN (SELECT onion FROM history WHERE onion IS NOT NULL)
                AND onion NOT IN (SELECT contact_onion FROM messages)
                {condition}
            """
            self._sql.execute(query_delete, params)

        return deleted_peers

    def resolve_target(self, target: Optional[str]) -> Optional[Tuple[str, str]]:
        """
        Resolves a generic target string into a guaranteed (alias, onion) tuple.
        This variant is strictly read-only and never creates aliases.

        Args:
            target (Optional[str]): The target to resolve (alias or onion).

        Returns:
            Optional[Tuple[str, str]]: A tuple containing the resolved alias and
            clean onion. Returns None if the target cannot be resolved.
        """
        onion: Optional[str] = self.get_onion_by_alias(target)
        if not onion and target:
            onion = clean_onion(target)

        alias: Optional[str] = self.get_alias_by_onion(onion)

        if alias and onion:
            return alias, onion
        return None

    def resolve_target_for_interaction(
        self,
        target: Optional[str],
    ) -> Optional[Tuple[str, str]]:
        """
        Resolves a generic target string into a guaranteed (alias, onion) tuple.
        This variant may create a RAM alias for a previously unseen onion because
        it is intended for interactive peer actions such as connect, switch, or drops.

        Args:
            target (Optional[str]): The target to resolve (alias or onion).

        Returns:
            Optional[Tuple[str, str]]: A tuple containing the resolved alias and
            clean onion. Returns None if the target cannot be resolved.
        """
        onion: Optional[str] = self.get_onion_by_alias(target)
        if not onion and target:
            onion = clean_onion(target)

        alias: Optional[str] = self.ensure_alias_for_onion(onion)

        if alias and onion:
            return alias, onion
        return None

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

        res: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
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

    def get_alias_by_onion(self, onion: Optional[str]) -> Optional[str]:
        """
        Returns the alias for an onion without mutating storage.

        Args:
            onion (Optional[str]): The onion address.

        Returns:
            Optional[str]: The mapped alias.
        """
        if not onion:
            return None
        onion = clean_onion(onion)

        res: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            'SELECT alias FROM contacts WHERE onion = ?', (onion,)
        )
        if res:
            return str(res[0][0])

        return None

    def ensure_alias_for_onion(self, onion: Optional[str]) -> Optional[str]:
        """
        Returns the alias for an onion, creating a RAM alias if needed.

        Args:
            onion (Optional[str]): The onion address.

        Returns:
            Optional[str]: The mapped or newly created alias.
        """
        alias: Optional[str] = self.get_alias_by_onion(onion)
        if alias:
            return alias

        if not onion:
            return None

        onion = clean_onion(onion)

        if len(onion) == 56:
            alias = self._generate_ram_alias(onion)
            self._sql.execute(
                'INSERT INTO contacts (onion, alias, is_saved) VALUES (?, ?, 0)',
                (onion, alias),
            )
            return alias

        return None

    def require_alias_by_onion(self, onion: str) -> str:
        """
        Resolves an onion to an already existing alias.

        Args:
            onion (str): The onion address.

        Raises:
            ValueError: If no alias mapping exists.

        Returns:
            str: The resolved alias.
        """
        alias: Optional[str] = self.get_alias_by_onion(onion)
        if not alias:
            raise ValueError(f"Missing alias mapping for onion '{clean_onion(onion)}'.")
        return alias

    def get_contacts_data(self) -> Dict[str, Union[str, List[Tuple[str, str]]]]:
        """
        Retrieves raw contacts data for UI presentation.

        Args:
            None

        Returns:
            Dict[str, Union[str, List[Tuple[str, str]]]]: Dictionary containing 'saved', 'discovered', and 'profile' data.
        """
        saved: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            'SELECT alias, onion FROM contacts WHERE is_saved = 1 ORDER BY alias ASC'
        )
        discovered: List[Tuple[SqlParam, ...]] = self._sql.fetchall(
            'SELECT alias, onion FROM contacts WHERE is_saved = 0 ORDER BY alias ASC'
        )
        return {
            'saved': [(str(row[0]), str(row[1])) for row in saved],
            'discovered': [(str(row[0]), str(row[1])) for row in discovered],
            'profile': self._pm.profile_name,
        }
