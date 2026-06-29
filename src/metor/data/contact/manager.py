"""Contact persistence service backed by the centralized SQL peer store."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from metor.utils import clean_onion

from metor.data.contact.models import (
    ContactAliasChange,
    ContactOperationResult,
    ContactOperationType,
    ContactRecord,
    ContactRemoval,
    ContactsSnapshot,
)
from metor.data.profile import ProfileManager
from metor.data.sql import PeerRepository, SqlManager


class ContactManager:
    """Manages the database mapping between aliases and .onion addresses."""

    def __init__(self, pm: ProfileManager, password: Optional[str] = None) -> None:
        """
        Initializes the contact manager connected to the centralized peer store.

        Args:
            pm (ProfileManager): The profile manager instance.
            password (Optional[str]): The master password for SQLCipher encryption.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._db_path: Path = self._pm.paths.get_db_file()
        self._sql: SqlManager = SqlManager(self._db_path, self._pm.config, password)
        self._peers: PeerRepository = self._sql.peers

    def get_all_contacts(self) -> List[str]:
        """
        Retrieves a list of all permanently saved contact aliases.

        Args:
            None

        Returns:
            List[str]: A list of saved alias names.
        """
        return self._peers.list_saved_aliases()

    def is_session_alias(self, alias: str) -> bool:
        """
        Checks if an alias belongs to an auto-generated discovered peer.

        Args:
            alias (str): The alias to check.

        Returns:
            bool: True if it is an unsaved discovered peer.
        """
        peer = self._peers.get_by_alias(alias.strip().lower())
        return peer is not None and not peer.is_saved

    def add_contact(self, alias: str, onion: str) -> ContactOperationResult:
        """
        Adds a new contact to the address book.

        Args:
            alias (str): The chosen name for the contact.
            onion (str): The remote onion identity.

        Returns:
            ContactOperationResult: The typed address-book mutation result.
        """
        alias = alias.strip().lower()
        onion = clean_onion(onion)

        alias_row = self._peers.get_by_alias(alias)
        if alias_row is not None:
            return ContactOperationResult(
                False,
                ContactOperationType.ALIAS_IN_USE,
                {'alias': alias, 'onion': onion},
            )

        onion_row = self._peers.get_by_onion(onion)
        if onion_row is not None and onion_row.is_saved:
            return ContactOperationResult(
                False,
                ContactOperationType.ONION_IN_USE,
                {'alias': onion_row.alias, 'onion': onion},
            )

        if onion_row is not None:
            self._peers.update_alias_and_saved(onion, alias, True)
        else:
            self._peers.insert(onion, alias, True)

        return ContactOperationResult(
            True,
            ContactOperationType.CONTACT_ADDED,
            {'alias': alias, 'onion': onion, 'profile': self._pm.profile_name},
        )

    def promote_discovered_peer(self, alias: str) -> ContactOperationResult:
        """
        Promotes a discovered peer to a permanent address-book contact.

        Args:
            alias (str): The discovered alias to promote.

        Returns:
            ContactOperationResult: The typed address-book mutation result.
        """
        alias = alias.strip().lower()
        peer = self._peers.get_by_alias(alias)
        if peer is None:
            return ContactOperationResult(
                False,
                ContactOperationType.DISCOVERED_PEER_NOT_FOUND,
                {'target': alias},
            )

        if peer.is_saved:
            return ContactOperationResult(
                False,
                ContactOperationType.CONTACT_ALREADY_SAVED,
                {'alias': alias, 'onion': peer.onion},
            )

        self._peers.update_saved(peer.onion, True)
        return ContactOperationResult(
            True,
            ContactOperationType.PEER_PROMOTED,
            {'alias': alias, 'onion': peer.onion},
        )

    def rename_contact(
        self,
        old_alias: str,
        new_alias: str,
    ) -> ContactOperationResult:
        """
        Renames a contact or discovered peer dynamically.

        Args:
            old_alias (str): The current alias.
            new_alias (str): The desired new alias.

        Returns:
            ContactOperationResult: The typed address-book mutation result.
        """
        old_alias = old_alias.strip().lower()
        new_alias = new_alias.strip().lower()

        if old_alias == new_alias:
            return ContactOperationResult(False, ContactOperationType.ALIAS_SAME, {})

        onion = self.get_onion_by_alias(old_alias)
        if self._peers.get_by_alias(new_alias) is not None:
            params: Dict[str, str] = {'alias': new_alias}
            if onion is not None:
                params['onion'] = onion
            return ContactOperationResult(
                False,
                ContactOperationType.ALIAS_IN_USE,
                params,
            )

        peer = self._peers.get_by_alias(old_alias)
        if peer is None:
            return ContactOperationResult(
                False,
                ContactOperationType.ALIAS_NOT_FOUND,
                {'alias': old_alias},
            )

        self._peers.update_alias(peer.onion, new_alias)
        result_params: Dict[str, str] = {
            'old_alias': old_alias,
            'new_alias': new_alias,
        }
        if onion is not None:
            result_params['onion'] = onion
        return ContactOperationResult(
            True,
            ContactOperationType.ALIAS_RENAMED,
            result_params,
        )

    def remove_contact(
        self,
        alias: str,
        active_onions: Optional[List[str]] = None,
    ) -> ContactOperationResult:
        """
        Removes a saved contact or anonymizes a renamed discovered peer.

        Args:
            alias (str): The contact to remove.
            active_onions (Optional[List[str]]): Currently connected onions functioning as a shield.

        Returns:
            ContactOperationResult: The typed address-book mutation result.
        """
        active_onions = [clean_onion(onion) for onion in (active_onions or [])]
        alias = alias.strip().lower()
        peer = self._peers.get_by_alias(alias)
        if peer is None:
            return ContactOperationResult(
                False,
                ContactOperationType.PEER_NOT_FOUND,
                {'target': alias},
            )

        onion = peer.onion
        was_saved: bool = peer.is_saved
        has_refs: bool = onion in active_onions or self._peers.has_references(onion)

        if has_refs:
            new_alias = self._generate_ram_alias(onion)
            if new_alias == alias:
                if was_saved:
                    self._peers.update_saved(onion, False)
                    return ContactOperationResult(
                        True,
                        ContactOperationType.CONTACT_DOWNGRADED,
                        {'alias': alias, 'onion': onion},
                    )

                return ContactOperationResult(
                    False,
                    ContactOperationType.PEER_CANT_DELETE_ACTIVE,
                    {'alias': alias, 'onion': onion},
                )

            self._peers.update_alias_and_saved(onion, new_alias, False)
            if was_saved:
                return ContactOperationResult(
                    True,
                    ContactOperationType.CONTACT_REMOVED_DOWNGRADED,
                    {'alias': alias, 'new_alias': new_alias, 'onion': onion},
                    renames=(ContactAliasChange(alias, new_alias, onion, was_saved),),
                )

            return ContactOperationResult(
                True,
                ContactOperationType.PEER_ANONYMIZED,
                {'alias': alias, 'new_alias': new_alias, 'onion': onion},
                renames=(ContactAliasChange(alias, new_alias, onion, was_saved),),
            )

        self._peers.delete_by_alias(alias)
        if was_saved:
            return ContactOperationResult(
                True,
                ContactOperationType.CONTACT_REMOVED,
                {
                    'alias': alias,
                    'onion': onion,
                    'profile': self._pm.profile_name,
                },
                removals=(ContactRemoval(alias, onion),),
            )

        return ContactOperationResult(
            True,
            ContactOperationType.PEER_REMOVED,
            {'alias': alias, 'onion': onion},
            removals=(ContactRemoval(alias, onion),),
        )

    def clear_contacts(
        self,
        active_onions: Optional[List[str]] = None,
    ) -> ContactOperationResult:
        """
        Wipes the address book while preserving peers that still anchor durable references.

        Args:
            active_onions (Optional[List[str]]): Currently connected onions functioning as a shield.

        Returns:
            ContactOperationResult: The typed address-book mutation result.
        """
        active_onions = [clean_onion(onion) for onion in (active_onions or [])]
        try:
            renames: List[ContactAliasChange] = []
            removed: List[ContactRemoval] = []

            for peer in self._peers.list_saved():
                if peer.onion in active_onions or self._peers.has_references(
                    peer.onion
                ):
                    new_alias = self._generate_ram_alias(peer.onion)
                    self._peers.update_alias_and_saved(peer.onion, new_alias, False)
                    renames.append(
                        ContactAliasChange(peer.alias, new_alias, peer.onion, True)
                    )
                else:
                    self._peers.delete_by_onion(peer.onion)
                    removed.append(ContactRemoval(peer.alias, peer.onion))

            return ContactOperationResult(
                True,
                ContactOperationType.CONTACTS_CLEARED,
                {
                    'profile': self._pm.profile_name,
                    'preserved_peers': len(renames),
                },
                renames=tuple(renames),
                removals=tuple(removed),
            )
        except Exception:
            return ContactOperationResult(
                False,
                ContactOperationType.CONTACTS_CLEAR_FAILED,
                {},
            )

    def cleanup_orphans(
        self,
        active_onions: Optional[List[str]] = None,
    ) -> List[Tuple[str, str]]:
        """
        Executes a zero-trace wipe of all temporary peers that no longer have durable state.

        Args:
            active_onions (Optional[List[str]]): Active Tor connection onions to preserve.

        Returns:
            List[Tuple[str, str]]: List of removed alias/onion pairs for UI sync.
        """
        return self._peers.cleanup_orphans(active_onions)

    def resolve_target(self, target: Optional[str]) -> Optional[Tuple[str, str]]:
        """
        Resolves a generic target string into a guaranteed alias/onion tuple.

        Args:
            target (Optional[str]): The target to resolve (alias or onion).

        Returns:
            Optional[Tuple[str, str]]: A tuple containing the resolved alias and clean onion.
        """
        onion = self.get_onion_by_alias(target)
        if not onion and target:
            onion = clean_onion(target)

        alias = self.get_alias_by_onion(onion)
        if alias and onion:
            return alias, onion
        return None

    def resolve_target_for_interaction(
        self,
        target: Optional[str],
    ) -> Optional[Tuple[str, str]]:
        """
        Resolves a generic target string into a guaranteed alias/onion tuple.

        Args:
            target (Optional[str]): The target to resolve (alias or onion).

        Returns:
            Optional[Tuple[str, str]]: A tuple containing the resolved alias and clean onion.
        """
        onion = self.get_onion_by_alias(target)
        if not onion and target:
            onion = clean_onion(target)

        alias = self.ensure_alias_for_onion(onion)
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

        peer = self._peers.get_by_alias(alias.strip().lower())
        return peer.onion if peer is not None else None

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
        while True:
            peer = self._peers.get_by_alias(alias)
            if peer is None or peer.onion == onion:
                return alias
            counter += 1
            alias = f'{base_alias}{counter}'

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

        peer = self._peers.get_by_onion(clean_onion(onion))
        return peer.alias if peer is not None else None

    def ensure_alias_for_onion(self, onion: Optional[str]) -> Optional[str]:
        """
        Returns the alias for an onion, creating a discovered alias if needed.

        Args:
            onion (Optional[str]): The onion address.

        Returns:
            Optional[str]: The mapped or newly created alias.
        """
        alias = self.get_alias_by_onion(onion)
        if alias:
            return alias

        if not onion:
            return None

        onion = clean_onion(onion)
        if len(onion) != 56:
            return None

        alias = self._generate_ram_alias(onion)
        self._peers.insert(onion, alias, False)
        return alias

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
        alias = self.get_alias_by_onion(onion)
        if not alias:
            raise ValueError(f"Missing alias mapping for onion '{clean_onion(onion)}'.")
        return alias

    def get_contacts_data(self) -> ContactsSnapshot:
        """
        Retrieves typed contacts data for UI presentation.

        Args:
            None

        Returns:
            ContactsSnapshot: Typed saved/discovered contact sets.
        """
        return ContactsSnapshot(
            saved=tuple(
                ContactRecord(peer.alias, peer.onion)
                for peer in self._peers.list_saved()
            ),
            discovered=tuple(
                ContactRecord(peer.alias, peer.onion)
                for peer in self._peers.list_discovered()
            ),
            profile=self._pm.profile_name,
        )
