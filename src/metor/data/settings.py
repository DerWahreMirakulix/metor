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
    """Available global configuration keys strictly isolated by Client (ui) and Server (daemon) domains."""

    # 1. User Interface (Client)
    DEFAULT_PROFILE = 'ui.default_profile'
    PROMPT_SIGN = 'ui.prompt_sign'
    CHAT_LIMIT = 'ui.chat_limit'
    HISTORY_LIMIT = 'ui.history_limit'
    MESSAGES_LIMIT = 'ui.messages_limit'
    CHAT_BUFFER_PADDING = 'ui.chat_buffer_padding'

    # 2. Core Daemon (Server - Network, Persistence & Security)
    MAX_TOR_RETRIES = 'daemon.max_tor_retries'
    MAX_CONNECT_RETRIES = 'daemon.max_connect_retries'
    TOR_TIMEOUT = 'daemon.tor_timeout'
    ENABLE_TOR_LOGGING = 'daemon.enable_tor_logging'
    ENABLE_SQL_LOGGING = 'daemon.enable_sql_logging'
    AUTO_ACCEPT_CONTACTS = 'daemon.auto_accept_contacts'
    REQUIRE_LOCAL_AUTH = 'daemon.require_local_auth'
    ALLOW_DROPS = 'daemon.allow_drops'
    EPHEMERAL_MESSAGES = 'daemon.ephemeral_messages'
    RECORD_LIVE_EVENTS = 'daemon.record_live_events'
    RECORD_DROP_EVENTS = 'daemon.record_drop_events'
    FALLBACK_TO_DROP = 'daemon.fallback_to_drop'
    MAX_UNSEEN_LIVE_MSGS = 'daemon.max_unseen_live_msgs'


class Settings:
    """Dynamic application settings manager reading from and writing to a nested global JSON file."""

    _DEFAULTS: Dict[str, Any] = {
        SettingKey.DEFAULT_PROFILE.value: 'default',
        SettingKey.PROMPT_SIGN.value: '$',
        SettingKey.CHAT_LIMIT.value: 50,
        SettingKey.HISTORY_LIMIT.value: 50,
        SettingKey.MESSAGES_LIMIT.value: 50,
        SettingKey.CHAT_BUFFER_PADDING.value: 20,
        SettingKey.MAX_TOR_RETRIES.value: 3,
        SettingKey.MAX_CONNECT_RETRIES.value: 3,
        SettingKey.TOR_TIMEOUT.value: 10.0,
        SettingKey.ENABLE_TOR_LOGGING.value: False,
        SettingKey.ENABLE_SQL_LOGGING.value: False,
        SettingKey.AUTO_ACCEPT_CONTACTS.value: True,
        SettingKey.REQUIRE_LOCAL_AUTH.value: False,
        SettingKey.ALLOW_DROPS.value: True,
        SettingKey.EPHEMERAL_MESSAGES.value: False,
        SettingKey.RECORD_LIVE_EVENTS.value: True,
        SettingKey.RECORD_DROP_EVENTS.value: True,
        SettingKey.FALLBACK_TO_DROP.value: True,
        SettingKey.MAX_UNSEEN_LIVE_MSGS.value: 20,
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
        Creates the default structure and writes it to disk if the file is missing.

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

                    for domain in ('ui', 'daemon'):
                        if domain not in data:
                            data[domain] = {}

                    return data
            except (json.JSONDecodeError, IOError):
                pass

        data = {'ui': {}, 'daemon': {}}
        for key_enum, val in cls._DEFAULTS.items():
            category: str
            sub_key: str
            category, sub_key = key_enum.split('.', 1)
            data[category][sub_key] = val

        with FileLock(path):
            with path.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)

        return data

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
        Enforces strict type validation against the default configuration schema.

        Args:
            key (SettingKey): The setting key enum to update.
            value (Any): The new value for the setting.

        Raises:
            TypeError: If the provided value does not match the expected type schema.

        Returns:
            None
        """
        default_val: Any = cls._DEFAULTS.get(key.value)
        if default_val is not None:
            expected_type: type = type(default_val)
            if (
                expected_type is float
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                value = float(value)
            elif type(value) is not expected_type:
                raise TypeError(
                    f"Invalid type for '{key.value}'. Expected {expected_type.__name__}, got {type(value).__name__}."
                )

        path: Path = cls.get_global_settings_path()

        with FileLock(path):
            data: Dict[str, Dict[str, Any]] = cls._load_settings()
            category: str
            sub_key: str
            category, sub_key = key.value.split('.', 1)

            data[category][sub_key] = value

            with path.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
