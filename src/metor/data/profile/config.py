"""
Module managing the profile-specific JSON configuration file.
Provides thread-safe read/write operations and cascading lookups
falling back to global application settings.
"""

import json
from enum import Enum
from typing import Dict, Union, cast
from pathlib import Path

from metor.data import SettingKey, Settings, SettingValue
from metor.utils import FileLock

# Local Package Imports
from metor.data.profile.paths import Paths
from metor.data.profile.models import ProfileConfigKey, ProfileConfigValue


class Config:
    """Manages reading and writing to the profile's configuration JSON."""

    def __init__(self, paths: Paths) -> None:
        """
        Initializes the configuration manager.

        Args:
            paths (Paths): The path resolver.

        Returns:
            None
        """
        self._paths: Paths = paths

    def _load(self) -> Dict[str, ProfileConfigValue]:
        """
        Loads the JSON configuration from disk safely. Generates default config if missing.

        Args:
            None

        Returns:
            Dict[str, ProfileConfigValue]: The loaded configuration data.
        """
        config_file: Path = self._paths.get_config_file()
        if config_file.exists():
            try:
                with config_file.open('r', encoding='utf-8') as f:
                    return cast(Dict[str, ProfileConfigValue], json.load(f))
            except (json.JSONDecodeError, IOError):
                pass

        default_data: Dict[str, ProfileConfigValue] = {
            ProfileConfigKey.IS_REMOTE.value: False,
            ProfileConfigKey.DAEMON_PORT.value: None,
        }

        # ONLY create the file if the profile folder physically exists
        if self._paths.exists():
            try:
                with FileLock(config_file):
                    with config_file.open('w', encoding='utf-8') as f:
                        json.dump(default_data, f, indent=4)
            except IOError:
                pass

        return default_data

    def get(
        self,
        key: Union[ProfileConfigKey, SettingKey, str],
        default: ProfileConfigValue = None,
    ) -> Union[ProfileConfigValue, SettingValue]:
        """
        Retrieves a setting, cascading from local config to global defaults.

        Args:
            key (Union[ProfileConfigKey, SettingKey, str]): The setting to retrieve.
            default (ProfileConfigValue): Fallback value.

        Returns:
            Union[ProfileConfigValue, SettingValue]: The resolved configuration value.
        """
        key_str: str = key.value if isinstance(key, Enum) else key
        data: Dict[str, ProfileConfigValue] = self._load()

        if key_str in data:
            return data[key_str]

        try:
            global_key: SettingKey = SettingKey(key_str)
            return Settings.get(global_key)
        except ValueError:
            pass

        return default

    def set(
        self, key: Union[ProfileConfigKey, SettingKey, str], value: ProfileConfigValue
    ) -> None:
        """
        Writes a setting safely using a file lock.
        Implies directory creation if a setting is deliberately saved.

        Args:
            key (Union[ProfileConfigKey, SettingKey, str]): The setting to save.
            value (ProfileConfigValue): The value to persist.

        Returns:
            None
        """
        if not self._paths.exists():
            self._paths.create_directories()

        key_str: str = key.value if isinstance(key, Enum) else key
        config_file: Path = self._paths.get_config_file()

        with FileLock(config_file):
            data: Dict[str, ProfileConfigValue] = self._load()
            data[key_str] = value
            with config_file.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
