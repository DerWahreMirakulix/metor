"""
Module for managing mappings between user-friendly aliases and .onion addresses.
"""

import os
import json
from typing import Dict, Tuple, Optional, List

from metor.data.profile import ProfileManager
from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.utils.helper import clean_onion, ensure_onion_format
from metor.utils.lock import FileLock


class ContactManager:
    """Manages the mapping between user-friendly aliases and .onion addresses."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the ContactManager for a specific profile.

        Args:
            pm (ProfileManager): The profile manager instance.
        """
        self._pm: ProfileManager = pm
        self._file_path: str = os.path.join(
            self._pm.get_config_dir(), Constants.CONTACTS_FILE
        )
        self._contacts: Dict[str, str] = self._load()
        self._session_aliases: Dict[str, str] = {}

    def _load(self) -> Dict[str, str]:
        """
        Loads contacts from the JSON file on disk.

        Returns:
            Dict[str, str]: A dictionary of saved contacts.
        """
        if not os.path.exists(self._file_path):
            return {}
        try:
            with open(self._file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _refresh(self) -> None:
        """Reloads the contacts dictionary from disk."""
        self._contacts = self._load()

    def _save(self) -> None:
        """Saves the current contacts dictionary to disk using an exclusive file lock."""
        with FileLock(self._file_path):
            with open(self._file_path, 'w', encoding='utf-8') as f:
                json.dump(self._contacts, f, indent=4)

    def get_all_contacts(self) -> List[str]:
        """
        Retrieves a list of all permanently saved contact aliases.

        Returns:
            List[str]: A list of saved alias names.
        """
        self._refresh()
        return list(self._contacts.keys())

    def is_session_alias(self, alias: str) -> bool:
        """Checks if an alias is only temporarily stored in RAM."""
        return alias.strip().lower() in self._session_aliases

    def add_contact(self, alias: str, onion: str) -> Tuple[bool, str]:
        """
        Adds a completely new contact to the disk.

        Args:
            alias (str): The chosen name for the contact.
            onion (str): The remote onion identity.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        self._refresh()
        alias = alias.strip().lower()

        if self._contacts.get(alias):
            return False, f"Alias '{alias}' is already in use."

        onion = clean_onion(onion)

        existing_aliases: List[str] = [
            k for k, v in self._contacts.items() if v == onion
        ]
        if existing_aliases:
            return (
                False,
                f"The onion is already associated with an alias '{existing_aliases[0]}'.",
            )

        if alias in self._session_aliases:
            del self._session_aliases[alias]

        self._contacts[alias] = onion
        self._save()

        return (
            True,
            f"Contact '{alias}' added successfully to profile '{self._pm.profile_name}'.",
        )

    def promote_session_alias(self, alias: str) -> Tuple[bool, str]:
        """
        Promotes a volatile RAM alias to a permanent disk contact with the exact same name.

        Args:
            alias (str): The RAM alias to promote.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        self._refresh()
        alias = alias.strip().lower()

        if alias not in self._session_aliases:
            return False, f"RAM alias '{alias}' not found."

        if alias in self._contacts:
            return False, f"Alias '{alias}' is already saved."

        onion: str = self._session_aliases.pop(alias)
        self._contacts[alias] = onion
        self._save()
        return True, f"RAM alias '{alias}' saved permanently to address book."

    def rename_contact(self, old_alias: str, new_alias: str) -> Tuple[bool, str]:
        """
        Renames a contact dynamically (RAM stays RAM, Disk stays Disk).

        Args:
            old_alias (str): The current alias.
            new_alias (str): The desired new alias.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        self._refresh()
        old_alias = old_alias.strip().lower()
        new_alias = new_alias.strip().lower()

        if old_alias == new_alias:
            return False, 'The new alias must be different from the old one.'

        if new_alias in self._contacts or new_alias in self._session_aliases:
            if new_alias != old_alias:
                return False, f"Alias '{new_alias}' is already in use."

        if old_alias in self._contacts:
            onion: str = self._contacts.pop(old_alias)
            self._contacts[new_alias] = onion
            self._save()
            return True, f"Contact renamed from '{old_alias}' to '{new_alias}'."
        elif old_alias in self._session_aliases:
            onion = self._session_aliases.pop(old_alias)
            self._session_aliases[new_alias] = onion
            return True, f"RAM alias renamed from '{old_alias}' to '{new_alias}'."
        else:
            return False, f"Contact '{old_alias}' not found."

    def remove_contact(self, alias: str) -> Tuple[bool, str]:
        """
        Removes a saved contact. Refuses to delete pure RAM aliases.

        Args:
            alias (str): The contact to remove.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        self._refresh()
        alias = alias.strip().lower()

        if alias in self._session_aliases and alias not in self._contacts:
            return False, 'RAM aliases cannot be deleted. They expire automatically.'

        if alias in self._contacts:
            del self._contacts[alias]
            self._save()
            return (
                True,
                f"Contact '{alias}' removed from profile '{self._pm.profile_name}'.",
            )

        return False, f"Contact '{alias}' not found."

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
        self._refresh()
        if not alias:
            return None
        alias = alias.strip().lower()

        onion: Optional[str] = self._contacts.get(alias)
        if not onion:
            onion = self._session_aliases.get(alias)

        return f'{onion}.onion' if onion else None

    def get_alias_by_onion(self, onion: Optional[str]) -> Optional[str]:
        """
        Returns the alias for an onion, or auto-generates a RAM alias if completely unknown.

        Args:
            onion (Optional[str]): The onion address.

        Returns:
            Optional[str]: The mapped or generated alias.
        """
        self._refresh()
        if not onion:
            return None

        onion = clean_onion(onion)

        for alias, saved_onion in self._contacts.items():
            if saved_onion == onion:
                return alias

        for alias, saved_onion in self._session_aliases.items():
            if saved_onion == onion:
                return alias

        if len(onion) == 56:
            base_alias: str = onion[:6]
            alias = base_alias
            counter: int = 1

            while alias in self._contacts or alias in self._session_aliases:
                counter += 1
                alias = f'{base_alias}{counter}'

            self._session_aliases[alias] = onion
            return alias

        return None

    def show(self, chat_mode: bool = False) -> str:
        """
        Returns a formatted string of all disk contacts and RAM aliases.

        Args:
            chat_mode (bool): Whether to format strictly for the chat UI.

        Returns:
            str: The formatted contacts list.
        """
        self._refresh()
        profile_suffix: str = (
            '' if chat_mode else f" for profile '{self._pm.profile_name}'"
        )

        lines: List[str] = []
        if self._contacts:
            lines.append(f'Available contacts{profile_suffix}:')
            for alias, onion in self._contacts.items():
                lines.append(f'   {Theme.GREEN}{alias}{Theme.RESET} -> {onion}')
        else:
            lines.append(f'No contacts in address book{profile_suffix}.')

        if self._session_aliases:
            lines.append('\nActive session aliases (RAM only):')
            for alias, onion in self._session_aliases.items():
                lines.append(f'   {Theme.DARK_GREY}{alias}{Theme.RESET} -> {onion}')

        return '\n'.join(lines)
