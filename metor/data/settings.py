"""
Module for handling global application settings securely.
Utilizes a centralized cross-platform file locking mechanism to prevent race conditions.
Enforces strict typing using Enums for configuration keys.
"""

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict

from metor.utils.constants import Constants
from metor.utils.lock import FileLock


class SettingKey(str, Enum):
    """Available global configuration keys split into logical domains."""

    DEFAULT_PROFILE = 'chat.default_profile'
    PROMPT_SIGN = 'chat.prompt_sign'
    MAX_TOR_RETRIES = 'daemon.max_tor_retries'
    ENABLE_TOR_LOGGING = 'daemon.enable_tor_logging'
    AUTO_ACCEPT_CONTACTS = 'daemon.auto_accept_contacts'


class Settings:
    """Dynamic application settings manager reading from and writing to a nested global JSON file."""

    _DEFAULTS: Dict[str, Any] = {
        SettingKey.DEFAULT_PROFILE.value: 'default',
        SettingKey.PROMPT_SIGN.value: '$',
        SettingKey.MAX_TOR_RETRIES.value: 3,
        SettingKey.ENABLE_TOR_LOGGING.value: False,
        SettingKey.AUTO_ACCEPT_CONTACTS.value: True,
    }

    @staticmethod
    def get_global_settings_path() -> Path:
        """
        Retrieves the path to the global settings JSON file.

        Args:
            None

        Returns:
            Path: Absolute path object to settings.json.
        """
        data_dir: Path = Constants.DATA
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / Constants.SETTINGS_FILE

    @classmethod
    def _load_settings(cls) -> Dict[str, Dict[str, Any]]:
        """
        Loads the settings from the JSON file into a nested structure.

        Args:
            None

        Returns:
            Dict[str, Dict[str, Any]]: The loaded settings dictionary partitioned by domain.
        """
        path: Path = cls.get_global_settings_path()
        if path.exists():
            try:
                with path.open('r', encoding='utf-8') as f:
                    data: Dict[str, Dict[str, Any]] = json.load(f)
                    if 'chat' not in data or 'daemon' not in data:
                        return {
                            'daemon': data.get('daemon', {}),
                            'chat': data.get('chat', {}),
                        }
                    return data
            except (json.JSONDecodeError, IOError):
                pass
        return {'daemon': {}, 'chat': {}}

    @classmethod
    def get(cls, key: SettingKey) -> Any:
        """
        Retrieves a setting value by its strongly-typed key. Uses default if not found.

        Args:
            key (SettingKey): The setting key enum to retrieve.

        Returns:
            Any: The value of the setting.
        """
        data: Dict[str, Dict[str, Any]] = cls._load_settings()
        category, sub_key = key.value.split('.', 1)

        if category in data and sub_key in data[category]:
            return data[category][sub_key]

        return cls._DEFAULTS.get(key.value)

    @classmethod
    def set(cls, key: SettingKey, value: Any) -> None:
        """
        Updates a setting value and saves it safely to the nested JSON file using a lock.

        Args:
            key (SettingKey): The setting key enum to update.
            value (Any): The new value for the setting.

        Returns:
            None
        """
        path: Path = cls.get_global_settings_path()

        with FileLock(path):
            data: Dict[str, Dict[str, Any]] = cls._load_settings()
            category, sub_key = key.value.split('.', 1)

            if category not in data:
                data[category] = {}

            data[category][sub_key] = value

            with path.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
