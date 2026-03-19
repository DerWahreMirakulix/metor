import os
import json
from metor.config import get_config_dir

class AddressBook:
    """
    Manages the mapping between user-friendly aliases and Tor hidden service addresses (.onion).
    Data is persisted to a JSON file specific to the current active profile.
    """
    def __init__(self):
        self.file_path = os.path.join(get_config_dir(), "address_book.json")
        self.contacts = self._load()

    def _load(self):
        """
        Load contacts from the JSON file. If the file doesn't exist or is invalid, return an empty dictionary.
        """
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save(self):
        """
        Save the current contacts to the JSON file.
        """
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.contacts, f, indent=4)

    def _clean_onion(self, onion):
        """
        Ensure the onion address is lowercase and strip the .onion suffix."""
        onion = onion.strip().lower()
        if onion.endswith(".onion"):
            onion = onion[:-6]
        return onion

    def add_contact(self, alias, onion):
        """
        Add a new contact or update an existing one. 
        Ensures a strict 1-to-1 mapping by removing any old aliases for the same onion.
        """
        alias = alias.strip().lower()
        onion = self._clean_onion(onion)
        
        # Remove any existing alias that points to this exact onion
        existing_aliases = [k for k, v in self.contacts.items() if v == onion]
        for old_alias in existing_aliases:
            if old_alias != alias:
                del self.contacts[old_alias]
                
        self.contacts[alias] = onion
        self._save()
        return alias

    def rename_contact(self, old_alias, new_alias):
        """
        Rename an existing alias. 
        Returns True if successful, False if old_alias doesn't exist or new_alias is taken.
        """
        old_alias = old_alias.strip().lower()
        new_alias = new_alias.strip().lower()
        
        if old_alias not in self.contacts:
            return False
            
        # Prevent accidentally overwriting a different contact
        if new_alias in self.contacts and new_alias != old_alias:
            return False
            
        onion = self.contacts.pop(old_alias)
        self.contacts[new_alias] = onion
        self._save()
        return True

    def remove_contact(self, alias):
        """
        Remove a contact by alias.
        """
        alias = alias.strip().lower()
        if alias in self.contacts:
            del self.contacts[alias]
            self._save()
            return True
        return False

    def get_onion_by_alias(self, alias):
        """
        Return the onion address for a given alias.
        """
        return self.contacts.get(alias.strip().lower())

    def get_alias_by_onion(self, onion):
        """
        Return the alias for an onion address.
        If the onion is not in the address book, automatically generate and save 
        a short 6-character alias based on the onion string.
        """
        onion = self._clean_onion(onion)
        
        for alias, saved_onion in self.contacts.items():
            if saved_onion == onion:
                return alias
                
        # Generate a fallback alias using the first 6 characters
        base_alias = onion[:6]
        alias = base_alias
        counter = 1
        
        # Prevent collisions if two onions share the same first 6 characters
        while alias in self.contacts and self.contacts[alias] != onion:
            counter += 1
            alias = f"{base_alias}{counter}"
            
        self.add_contact(alias, onion)
        return alias

    def list_contacts(self):
        """
        Return a dictionary of all saved contacts.
        """
        return self.contacts