import os
import json

from metor.profile import ProfileManager
from metor.settings import Settings
from metor.utils import clean_onion

class ContactManager:
    """Manages the mapping between user-friendly aliases and .onion addresses."""
    
    def __init__(self, pm: ProfileManager):
        self.pm = pm
        
        self._file_path = os.path.join(self.pm.get_config_dir(), "contacts.json")
        self._contacts = self._load()

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

    def add_contact(self, alias, onion):
        self._refresh()
        alias = alias.strip().lower()
        onion = clean_onion(onion)
        
        existing_aliases = [k for k, v in self._contacts.items() if v == onion]
        for old_alias in existing_aliases:
            if old_alias != alias:
                del self._contacts[old_alias]
                
        self._contacts[alias] = onion
        self._save()
        return True, f"Contact '{alias}' added successfully to profile '{self.pm.profile_name}'."

    def rename_contact(self, old_alias, new_alias):
        self._refresh()
        old_alias = old_alias.strip().lower()
        new_alias = new_alias.strip().lower()
        
        if old_alias not in self._contacts:
            return False, f"{Settings.RED}Error:{Settings.RESET} Contact '{old_alias}' not found in profile '{self.pm.profile_name}'."
            
        if new_alias in self._contacts and new_alias != old_alias:
            return False, f"{Settings.RED}Error:{Settings.RESET} Alias '{new_alias}' is already in use."
            
        onion = self._contacts.pop(old_alias)
        self._contacts[new_alias] = onion
        self._save()
        return True, f"Contact renamed from '{old_alias}' to '{new_alias}' in profile '{self.pm.profile_name}'."

    def remove_contact(self, alias):       
        self._refresh()
        alias = alias.strip().lower()
        if alias in self._contacts:
            del self._contacts[alias]
            self._save()
            return True, f"Contact '{alias}' removed from profile '{self.pm.profile_name}'."
        return False, f"{Settings.RED}Error:{Settings.RESET} Contact '{alias}' not found in profile '{self.pm.profile_name}'."

    def get_onion_by_alias(self, alias: str | None) -> str | None:    
        self._refresh()
        onion = self._contacts.get(alias.strip().lower()) if alias else None
        return onion + ".onion" if onion else None

    def get_alias_by_onion(self, onion: str | None) -> str | None:
        self._refresh()
        if not onion:
            return None

        onion = clean_onion(onion)
        for alias, saved_onion in self._contacts.items():
            if saved_onion == onion:
                return alias
                
        base_alias = onion[:6]
        alias = base_alias
        counter = 1
        
        while alias in self._contacts and self._contacts[alias] != onion:
            counter += 1
            alias = f"{base_alias}{counter}"
            
        self.add_contact(alias, onion)
        return alias

    def show(self, chat_mode=False):
        self._refresh()
        profile_suffix = "" if chat_mode else f" for profile '{self.pm.profile_name}'"
        if not self._contacts:
            return f"No contacts in address book{profile_suffix}."
        
        lines = [f"Available contacts{profile_suffix}:"]
        for alias, onion in self._contacts.items():
            lines.append(f"   {Settings.CYAN}{alias}{Settings.RESET} -> {onion}")

        return "\n".join(lines)
