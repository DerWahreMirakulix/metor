import os
import json

from metor.profile import ProfileManager
from metor.settings import Settings
from metor.utils import clean_onion, ensure_onion_format

class ContactManager:
    """Manages the mapping between user-friendly aliases and .onion addresses."""
    
    def __init__(self, pm: ProfileManager):
        self.pm = pm
        
        self._file_path = os.path.join(self.pm.get_config_dir(), "contacts.json")
        self._contacts = self._load()
        self._session_aliases = {}

    def _load(self):
        if not os.path.exists(self._file_path):
            return {}
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
        
    def _refresh(self):
        self._contacts = self._load()

    def _save(self):
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(self._contacts, f, indent=4)

    def is_session_alias(self, alias):
        return alias.strip().lower() in self._session_aliases

    def add_contact(self, alias, onion):
        """Adds a completely new contact to the disk."""
        self._refresh()
        alias = alias.strip().lower()
        onion = clean_onion(onion)
        
        existing_aliases = [k for k, v in self._contacts.items() if v == onion]
        for old_alias in existing_aliases:
            if old_alias != alias:
                del self._contacts[old_alias]
                
        if alias in self._session_aliases:
            del self._session_aliases[alias]
                
        self._contacts[alias] = onion
        self._save()
        return True, f"Contact '{alias}' added successfully to profile '{self.pm.profile_name}'."

    def promote_session_alias(self, alias):
        """Promotes a volatile RAM alias to a permanent disk contact with the exact same name."""
        self._refresh()
        alias = alias.strip().lower()

        if alias not in self._session_aliases:
            return False, f"{Settings.RED}Error:{Settings.RESET} RAM alias '{alias}' not found."

        if alias in self._contacts:
             return False, f"{Settings.RED}Error:{Settings.RESET} Alias '{alias}' is already saved."

        onion = self._session_aliases.pop(alias)
        self._contacts[alias] = onion
        self._save()
        return True, f"RAM alias '{alias}' saved permanently to address book."

    def rename_contact(self, old_alias, new_alias):
        """Renames a contact dynamically (RAM stays RAM, Disk stays Disk)."""
        self._refresh()
        old_alias = old_alias.strip().lower()
        new_alias = new_alias.strip().lower()

        if old_alias == new_alias:
            return False, f"{Settings.RED}Error:{Settings.RESET} The new alias must be different from the old one."
            
        if new_alias in self._contacts or new_alias in self._session_aliases:
            if new_alias != old_alias:
                return False, f"{Settings.RED}Error:{Settings.RESET} Alias '{new_alias}' is already in use."
            
        if old_alias in self._contacts:
            onion = self._contacts.pop(old_alias)
            self._contacts[new_alias] = onion
            self._save() 
            return True, f"Contact renamed from '{old_alias}' to '{new_alias}'."
        elif old_alias in self._session_aliases:
            onion = self._session_aliases.pop(old_alias)
            self._session_aliases[new_alias] = onion
            return True, f"RAM alias renamed from '{old_alias}' to '{new_alias}'."
        else:
            return False, f"{Settings.RED}Error:{Settings.RESET} Contact '{old_alias}' not found."

    def remove_contact(self, alias):       
        """Removes a saved contact. Refuses to delete pure RAM aliases."""
        self._refresh()
        alias = alias.strip().lower()
        
        if alias in self._session_aliases and alias not in self._contacts:
            return False, f"{Settings.RED}Error:{Settings.RESET} RAM aliases cannot be deleted. They expire automatically."
            
        if alias in self._contacts:
            del self._contacts[alias]
            self._save()
            return True, f"Contact '{alias}' removed from profile '{self.pm.profile_name}'."
            
        return False, f"{Settings.RED}Error:{Settings.RESET} Contact '{alias}' not found."
    
    def resolve_target(self, target: str | None, default_value: str | None = None):
        onion = self.get_onion_by_alias(target)
        if not onion: onion = ensure_onion_format(target)
        alias = self.get_alias_by_onion(onion)
        return (alias or default_value, onion or default_value)

    def get_onion_by_alias(self, alias: str | None) -> str | None:    
        self._refresh()
        if not alias: return None
        alias = alias.strip().lower()
        
        onion = self._contacts.get(alias)
        if not onion:
            onion = self._session_aliases.get(alias)
            
        return onion + ".onion" if onion else None

    def get_alias_by_onion(self, onion: str | None) -> str | None:
        """Returns the alias for an onion, or auto-generates a RAM alias if completely unknown."""
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
            base_alias = onion[:6]
            alias = base_alias
            counter = 1
            
            while alias in self._contacts or alias in self._session_aliases:
                counter += 1
                alias = f"{base_alias}{counter}"
                
            self._session_aliases[alias] = onion
            return alias
            
        return None

    def show(self, chat_mode=False):
        self._refresh()
        profile_suffix = "" if chat_mode else f" for profile '{self.pm.profile_name}'"
        
        lines = []
        if self._contacts:
            lines.append(f"Available contacts{profile_suffix}:")
            for alias, onion in self._contacts.items():
                lines.append(f"   {Settings.CYAN}{alias}{Settings.RESET} -> {onion}")
        else:
            lines.append(f"No contacts in address book{profile_suffix}.")

        if self._session_aliases:
            lines.append(f"\nActive session aliases (RAM only):")
            for alias, onion in self._session_aliases.items():
                lines.append(f"   {Settings.PURPLE}{alias}{Settings.RESET} -> {onion}")

        return "\n".join(lines)
