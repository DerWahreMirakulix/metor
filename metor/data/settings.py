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
    """Available global configuration keys strictly isolated by domain (DDD)."""

    # 1. User Interface & Limits
    DEFAULT_PROFILE = 'ui.default_profile'
    PROMPT_SIGN = 'ui.prompt_sign'
    CHAT_LIMIT = 'ui.chat_limit'
    HISTORY_LIMIT = 'ui.history_limit'
    MESSAGES_LIMIT = 'ui.messages_limit'

    # 2. Core Daemon & Network
    MAX_TOR_RETRIES = 'daemon.max_tor_retries'
    TOR_TIMEOUT = 'daemon.tor_timeout'
    ENABLE_TOR_LOGGING = 'daemon.enable_tor_logging'
    AUTO_ACCEPT_CONTACTS = 'daemon.auto_accept_contacts'

    # 3. Data Persistence
    RECORD_EVENTS = 'data.record_events'
    ALLOW_ASYNC = 'data.allow_async'

    # 4. Security & OPSEC
    REQUIRE_LOCAL_AUTH = 'security.require_local_auth'
    BURN_AFTER_READ = 'security.burn_after_read'


class Settings:
    """Dynamic application settings manager reading from and writing to a nested global JSON file."""

    _DEFAULTS: Dict[str, Any] = {
        SettingKey.DEFAULT_PROFILE.value: 'default',
        SettingKey.PROMPT_SIGN.value: '$',
        SettingKey.CHAT_LIMIT.value: 50,
        SettingKey.HISTORY_LIMIT.value: 50,
        SettingKey.MESSAGES_LIMIT.value: 50,
        SettingKey.MAX_TOR_RETRIES.value: 3,
        SettingKey.TOR_TIMEOUT.value: 10.0,
        SettingKey.ENABLE_TOR_LOGGING.value: False,
        SettingKey.AUTO_ACCEPT_CONTACTS.value: True,
        SettingKey.RECORD_EVENTS.value: True,
        SettingKey.ALLOW_ASYNC.value: True,
        SettingKey.REQUIRE_LOCAL_AUTH.value: False,
        SettingKey.BURN_AFTER_READ.value: False,
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

                    for domain in ('ui', 'daemon', 'data', 'security'):
                        if domain not in data:
                            data[domain] = {}

                    return data
            except (json.JSONDecodeError, IOError):
                pass
        return {'ui': {}, 'daemon': {}, 'data': {}, 'security': {}}

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
        category: str
        sub_key: str
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
            category: str
            sub_key: str
            category, sub_key = key.value.split('.', 1)

            data[category][sub_key] = value

            with path.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
