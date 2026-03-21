"""
Module for handling global application settings securely.
Utilizes a centralized cross-platform file locking mechanism to prevent race conditions.
"""

import os
import json
from typing import Any, Dict

from metor.utils.constants import Constants
from metor.utils.lock import FileLock


class Settings:
    """Dynamic application settings manager reading from and writing to a global JSON file."""

    # Default values fallback
    _DEFAULTS: Dict[str, Any] = {
        'default_profile': 'default',
        'prompt_sign': '$',
        'max_tor_retries': 3,
        'enable_tor_logging': False,
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
    def get(cls, key: str) -> Any:
        """
        Retrieves a setting value by key. Uses default if not found in JSON.

        Args:
            key (str): The setting key to retrieve.

        Returns:
            Any: The value of the setting.
        """
        data: Dict[str, Any] = cls._load_settings()
        return data.get(key, cls._DEFAULTS.get(key))

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """
        Updates a setting value and saves it safely to the JSON file using a lock.

        Args:
            key (str): The setting key to update.
            value (Any): The new value for the setting.
        """
        path: str = cls.get_global_settings_path()

        # Centralized locking logic applied via Context Manager
        with FileLock(path):
            data: Dict[str, Any] = cls._load_settings()
            data[key] = value
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
