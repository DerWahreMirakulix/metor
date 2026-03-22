"""
Module for handling global application settings securely.
Utilizes a centralized cross-platform file locking mechanism to prevent race conditions.
Enforces strict typing using Enums for configuration keys.
"""

import os
import json
from enum import Enum
from typing import Any, Dict

from metor.utils.constants import Constants
from metor.utils.lock import FileLock


class SettingKey(str, Enum):
    """Available global configuration keys."""

    DEFAULT_PROFILE = 'default_profile'
    PROMPT_SIGN = 'prompt_sign'
    MAX_TOR_RETRIES = 'max_tor_retries'
    ENABLE_TOR_LOGGING = 'enable_tor_logging'
    AUTO_ACCEPT_CONTACTS = 'auto_accept_contacts'


class Settings:
    """Dynamic application settings manager reading from and writing to a global JSON file."""

    # Default values fallback mapping Enum values (strings) to their defaults
    _DEFAULTS: Dict[str, Any] = {
        SettingKey.DEFAULT_PROFILE.value: 'default',
        SettingKey.PROMPT_SIGN.value: '$',
        SettingKey.MAX_TOR_RETRIES.value: 3,
        SettingKey.ENABLE_TOR_LOGGING.value: False,
        SettingKey.AUTO_ACCEPT_CONTACTS.value: True,
    }

    @staticmethod
    def get_global_settings_path() -> str:
        """
        Retrieves the path to the global settings JSON file.

        Returns:
            str: Absolute path to settings.json.
        """
        data_dir: str = Constants.DATA
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        return os.path.join(data_dir, Constants.SETTINGS_FILE)

    @classmethod
    def _load_settings(cls) -> Dict[str, Any]:
        """
        Loads the settings from the JSON file without locking (safe for pure reads).

        Returns:
            Dict[str, Any]: The loaded settings dictionary.
        """
        path: str = cls.get_global_settings_path()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    @classmethod
    def get(cls, key: SettingKey) -> Any:
        """
        Retrieves a setting value by its strongly-typed key. Uses default if not found.

        Args:
            key (SettingKey): The setting key enum to retrieve.

        Returns:
            Any: The value of the setting.
        """
        data: Dict[str, Any] = cls._load_settings()
        return data.get(key.value, cls._DEFAULTS.get(key.value))

    @classmethod
    def set(cls, key: SettingKey, value: Any) -> None:
        """
        Updates a setting value and saves it safely to the JSON file using a lock.

        Args:
            key (SettingKey): The setting key enum to update.
            value (Any): The new value for the setting.

        Returns:
            None
        """
        path: str = cls.get_global_settings_path()

        # Centralized locking logic applied via Context Manager
        with FileLock(path):
            data: Dict[str, Any] = cls._load_settings()
            data[key.value] = value
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
