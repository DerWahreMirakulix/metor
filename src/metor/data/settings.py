"""
Module for handling global application settings securely.
Utilizes a centralized cross-platform file locking mechanism to prevent race conditions.
Enforces strict typing using Enums for configuration keys and strongly-typed accessors.
"""

import json
from enum import Enum
from pathlib import Path
from typing import Dict, Union, Optional

from metor.utils import Constants, FileLock, TypeCaster


# Types
SettingValue = Union[str, int, float, bool]


class SettingKey(str, Enum):
    """Available global configuration keys strictly isolated by Client (ui) and Server (daemon) domains."""

    # 1. User Interface (Client)
    DEFAULT_PROFILE = 'ui.default_profile'
    PROMPT_SIGN = 'ui.prompt_sign'
    CHAT_LIMIT = 'ui.chat_limit'
    HISTORY_LIMIT = 'ui.history_limit'
    MESSAGES_LIMIT = 'ui.messages_limit'
    CHAT_BUFFER_PADDING = 'ui.chat_buffer_padding'
    IPC_TIMEOUT = 'ui.ipc_timeout'

    # 2. Core Daemon (Server - Network, Persistence & Security)
    MAX_TOR_RETRIES = 'daemon.max_tor_retries'
    MAX_CONNECT_RETRIES = 'daemon.max_connect_retries'
    TOR_TIMEOUT = 'daemon.tor_timeout'
    STREAM_IDLE_TIMEOUT = 'daemon.stream_idle_timeout'
    LATE_ACCEPTANCE_TIMEOUT = 'daemon.late_acceptance_timeout'
    DAEMON_IPC_TIMEOUT = 'daemon.ipc_timeout'
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

    # 3. Advanced Network Resilience & Constraints
    MAX_CONCURRENT_CONNECTIONS = 'daemon.max_concurrent_connections'
    DROP_TUNNEL_TTL = 'daemon.drop_tunnel_ttl'
    AUTO_RECONNECT_LIVE = 'daemon.auto_reconnect_live'

    @property
    def is_ui(self) -> bool:
        """
        Determines if the setting belongs to the User Interface domain.

        Args:
            None

        Returns:
            bool: True if it is a UI setting.
        """
        return self.value.startswith('ui.')

    @property
    def is_daemon(self) -> bool:
        """
        Determines if the setting belongs to the Daemon domain.

        Args:
            None

        Returns:
            bool: True if it is a Daemon setting.
        """
        return self.value.startswith('daemon.')


class Settings:
    """Dynamic application settings manager reading from and writing to a nested global JSON file."""

    _DEFAULTS: Dict[str, SettingValue] = {
        SettingKey.DEFAULT_PROFILE.value: 'default',
        SettingKey.PROMPT_SIGN.value: '$',
        SettingKey.CHAT_LIMIT.value: 50,
        SettingKey.HISTORY_LIMIT.value: 50,
        SettingKey.MESSAGES_LIMIT.value: 50,
        SettingKey.CHAT_BUFFER_PADDING.value: 20,
        SettingKey.IPC_TIMEOUT.value: 15.0,
        SettingKey.MAX_TOR_RETRIES.value: 3,
        SettingKey.MAX_CONNECT_RETRIES.value: 3,
        SettingKey.TOR_TIMEOUT.value: 10.0,
        SettingKey.STREAM_IDLE_TIMEOUT.value: 60.0,
        SettingKey.LATE_ACCEPTANCE_TIMEOUT.value: 60.0,
        SettingKey.DAEMON_IPC_TIMEOUT.value: 15.0,
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
        SettingKey.MAX_CONCURRENT_CONNECTIONS.value: 50,
        SettingKey.DROP_TUNNEL_TTL.value: 30.0,
        SettingKey.AUTO_RECONNECT_LIVE.value: True,
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
    def _load_settings(cls) -> Dict[str, Dict[str, SettingValue]]:
        """
        Loads the settings from the JSON file into a nested structure.
        Creates the default structure and writes it to disk if the file is missing.

        Args:
            None

        Returns:
            Dict[str, Dict[str, SettingValue]]: The loaded settings dictionary partitioned by domain.
        """
        path: Path = cls.get_global_settings_path()
        if path.exists():
            try:
                with path.open('r', encoding='utf-8') as f:
                    data: Dict[str, Dict[str, SettingValue]] = json.load(f)

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
    def get(cls, key: SettingKey) -> Optional[SettingValue]:
        """
        Retrieves a setting value by its strongly-typed key. Uses default if not found.

        Args:
            key (SettingKey): The setting key enum to retrieve.

        Returns:
            Optional[SettingValue]: The value of the setting, or None if completely missing.
        """
        data: Dict[str, Dict[str, SettingValue]] = cls._load_settings()
        category: str
        sub_key: str
        category, sub_key = key.value.split('.', 1)

        if category in data and sub_key in data[category]:
            return data[category][sub_key]

        return cls._DEFAULTS.get(key.value)

    @classmethod
    def get_str(cls, key: SettingKey) -> str:
        """
        Retrieves a setting and guarantees a string return type.

        Args:
            key (SettingKey): The setting key enum.

        Returns:
            str: The configuration value as a string.
        """
        val: Optional[SettingValue] = cls.get(key)
        if val is not None:
            return TypeCaster.to_str(val)

        default_val: Optional[SettingValue] = cls._DEFAULTS.get(key.value)
        return TypeCaster.to_str(default_val)

    @classmethod
    def get_int(cls, key: SettingKey) -> int:
        """
        Retrieves a setting and safely coerces it into an integer.

        Args:
            key (SettingKey): The setting key enum.

        Returns:
            int: The configuration value as an integer.
        """
        val: Optional[SettingValue] = cls.get(key)
        if val is not None:
            return TypeCaster.to_int(val)

        default_val: Optional[SettingValue] = cls._DEFAULTS.get(key.value)
        return TypeCaster.to_int(default_val)

    @classmethod
    def get_float(cls, key: SettingKey) -> float:
        """
        Retrieves a setting and safely coerces it into a float.

        Args:
            key (SettingKey): The setting key enum.

        Returns:
            float: The configuration value as a float.
        """
        val: Optional[SettingValue] = cls.get(key)
        if val is not None:
            return TypeCaster.to_float(val)

        default_val: Optional[SettingValue] = cls._DEFAULTS.get(key.value)
        return TypeCaster.to_float(default_val)

    @classmethod
    def get_bool(cls, key: SettingKey) -> bool:
        """
        Retrieves a setting and safely coerces it into a boolean.

        Args:
            key (SettingKey): The setting key enum.

        Returns:
            bool: The configuration value as a boolean.
        """
        val: Optional[SettingValue] = cls.get(key)
        if val is not None:
            return TypeCaster.to_bool(val)

        default_val: Optional[SettingValue] = cls._DEFAULTS.get(key.value)
        return TypeCaster.to_bool(default_val)

    @classmethod
    def set(cls, key: SettingKey, value: SettingValue) -> None:
        """
        Updates a setting value and saves it safely to the nested JSON file using a lock.
        Enforces strict type validation against the default configuration schema.

        Args:
            key (SettingKey): The setting key enum to update.
            value (SettingValue): The new value for the setting.

        Raises:
            TypeError: If the provided value does not match the expected type schema.

        Returns:
            None
        """
        default_val: Optional[SettingValue] = cls._DEFAULTS.get(key.value)
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
            data: Dict[str, Dict[str, SettingValue]] = cls._load_settings()
            category: str
            sub_key: str
            category, sub_key = key.value.split('.', 1)

            data[category][sub_key] = value

            with path.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
