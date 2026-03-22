"""
Module for managing user profiles, their directories, and daemon lock states.
"""

import os
import shutil
from typing import List, Tuple, Optional

from metor.data.settings import SettingKey, Settings
from metor.data.sql import SqlManager
from metor.ui.theme import Theme
from metor.utils.constants import Constants


class ProfileManager:
    """Manages profile directories, configurations, and session locks."""

    def __init__(self, profile_name: Optional[str] = None) -> None:
        """
        Initializes the ProfileManager. Uses the default profile if none is provided.

        Args:
            profile_name (Optional[str]): The name of the profile to manage.
        """
        self.profile_name: str = (
            profile_name if profile_name else self.load_default_profile()
        )

    @classmethod
    def load_default_profile(cls) -> str:
        """
        Retrieves the default profile name from the global settings.

        Returns:
            str: The name of the default profile.
        """
        return Settings.get(SettingKey.DEFAULT_PROFILE)

    @classmethod
    def set_default_profile(cls, profile_name: str) -> Tuple[bool, str]:
        """
        Sets a new default profile in the global settings.

        Args:
            profile_name (str): The name of the new default profile.

        Returns:
            Tuple[bool, str]: A success flag and a status message.
        """
        safe_name: str = ''.join(
            c for c in profile_name if c.isalnum() or c in ('-', '_')
        )
        if not safe_name:
            return False, 'Invalid profile name.'

        Settings.set(SettingKey.DEFAULT_PROFILE, safe_name)
        return True, f"Default profile permanently set to '{safe_name}'."

    def get_config_dir(self) -> str:
        """
        Retrieves the absolute path to the configuration directory for the current profile.

        Returns:
            str: The path to the profile's config directory.
        """
        config_dir: str = os.path.join(Constants.DATA, self.profile_name)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        return config_dir

    def get_daemon_port_file(self) -> str:
        """
        Returns the path to the file storing the daemon IPC port.

        Returns:
            str: The path to the daemon port file.
        """
        return os.path.join(self.get_config_dir(), Constants.DAEMON_PORT_FILE)

    def set_daemon_port(self, port: int) -> None:
        """
        Saves the given port number to the daemon port file.

        Args:
            port (int): The port number to save.
        """
        with open(self.get_daemon_port_file(), 'w') as f:
            f.write(str(port))

    def get_daemon_port(self) -> Optional[int]:
        """
        Reads the active daemon port from disk, if it exists.

        Returns:
            Optional[int]: The active daemon port, or None if not found.
        """
        port_file: str = self.get_daemon_port_file()
        if os.path.exists(port_file):
            try:
                with open(port_file, 'r') as f:
                    return int(f.read().strip())
            except Exception:
                pass
        return None

    def clear_daemon_port(self) -> None:
        """Deletes the daemon port file, signaling that the daemon is stopped."""
        port_file: str = self.get_daemon_port_file()
        if os.path.exists(port_file):
            try:
                os.remove(port_file)
            except OSError:
                pass

    def is_daemon_running(self) -> bool:
        """Checks whether the daemon is currently running for this profile."""
        return os.path.exists(self.get_daemon_port_file())

    def get_hidden_service_dir(self) -> str:
        """Retrieves and ensures correct permissions for the Tor hidden service directory."""
        hs_dir: str = os.path.join(self.get_config_dir(), Constants.HIDDEN_SERVICE_DIR)
        if not os.path.exists(hs_dir):
            os.makedirs(hs_dir, mode=0o700)
        else:
            os.chmod(hs_dir, 0o700)
        return hs_dir

    def get_tor_data_dir(self) -> str:
        """Retrieves and ensures correct permissions for the Tor data directory."""
        data_dir: str = os.path.join(self.get_config_dir(), Constants.TOR_DATA_DIR)
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, mode=0o700)
        else:
            os.chmod(data_dir, 0o700)
        return data_dir

    @staticmethod
    def get_all_profiles() -> List[str]:
        """
        Scans the data directory and returns a list of all existing profiles.

        Returns:
            List[str]: A list of profile folder names.
        """
        data_dir: str = os.path.join(Constants.DATA)
        if not os.path.exists(data_dir):
            return []

        ignored_folders = {Constants.HIDDEN_SERVICE_DIR, Constants.TOR_DATA_DIR}

        return [
            d
            for d in os.listdir(Constants.DATA)
            if os.path.isdir(os.path.join(Constants.DATA, d))
            and d not in ignored_folders
        ]

    @staticmethod
    def add_profile_folder(name: str) -> Tuple[bool, str]:
        """Creates a new profile directory safely."""
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))
        if not safe_name:
            return False, 'Invalid profile name.'

        target_dir: str = os.path.join(Constants.DATA, safe_name)
        if os.path.exists(target_dir):
            return False, f"Profile '{safe_name}' already exists."

        os.makedirs(target_dir)
        return True, f"Profile '{safe_name}' successfully created."

    @classmethod
    def rename_profile_folder(cls, old_name: str, new_name: str) -> Tuple[bool, str]:
        """Renames an existing profile directory, ensuring no daemon is running."""
        safe_old: str = ''.join(c for c in old_name if c.isalnum() or c in ('-', '_'))
        safe_new: str = ''.join(c for c in new_name if c.isalnum() or c in ('-', '_'))

        if not safe_old or not safe_new:
            return False, 'Invalid profile names.'

        old_dir: str = os.path.join(Constants.DATA, safe_old)
        new_dir: str = os.path.join(Constants.DATA, safe_new)

        if not os.path.exists(old_dir):
            return False, f"Profile '{safe_old}' does not exist."
        if os.path.exists(new_dir):
            return False, f"Profile '{safe_new}' already exists."

        if cls(safe_old).is_daemon_running():
            return (
                False,
                f"Cannot rename profile '{safe_old}' while its daemon is running!",
            )

        os.rename(old_dir, new_dir)
        return True, f"Profile '{safe_old}' successfully renamed to '{safe_new}'."

    @classmethod
    def remove_profile_folder(
        cls, name: str, active_profile: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Removes a profile directory and all its contents safely."""
        default: str = cls.load_default_profile()
        active: str = active_profile if active_profile else default
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))

        if not safe_name:
            return False, 'Invalid profile name.'

        target_dir: str = os.path.join(Constants.DATA, safe_name)

        if active == safe_name:
            return (
                False,
                'Cannot remove active profile! Switch to another profile first.',
            )
        if default == safe_name:
            return False, 'Cannot remove default profile! Change default first.'
        if not os.path.exists(target_dir):
            return False, f"Profile '{safe_name}' does not exist."
        if cls(safe_name).is_daemon_running():
            return (
                False,
                f"Cannot remove profile '{safe_name}' while its daemon is running!",
            )

        shutil.rmtree(target_dir)
        return True, f"Profile '{safe_name}' successfully removed."

    @classmethod
    def clear_profile_db(cls, name: str) -> Tuple[bool, str]:
        """
        Clears the entire SQLite database (history, messages, contacts) for a profile.

        Args:
            name (str): The name of the profile.

        Returns:
            Tuple[bool, str]: Success flag and status message.
        """
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))
        if not safe_name:
            return False, 'Invalid profile name.'

        if cls(safe_name).is_daemon_running():
            return (
                False,
                f"Cannot clear database for '{safe_name}' while daemon is running.",
            )

        db_path: str = os.path.join(Constants.DATA, safe_name, Constants.DB_FILE)
        if not os.path.exists(db_path):
            return False, f"No database found for profile '{safe_name}'."

        try:
            sql = SqlManager(db_path)
            sql.execute('DELETE FROM history')
            sql.execute('DELETE FROM messages')
            sql.execute('DELETE FROM contacts')
            return True, f"Database for profile '{safe_name}' successfully cleared."
        except Exception as e:
            return False, f'Error clearing database: {e}'

    @classmethod
    def show(cls, active_profile: Optional[str] = None) -> str:
        """
        Returns a formatted string representing all available profiles.

        Args:
            active_profile (Optional[str]): The currently active profile to highlight.

        Returns:
            str: The formatted profile list.
        """
        active: str = active_profile if active_profile else cls.load_default_profile()
        profiles: List[str] = cls.get_all_profiles()
        if not profiles:
            return 'No profiles found.'

        lines: List[str] = ['Available profiles:']
        for p in profiles:
            marker: str = '*' if p == active else ' '
            if p == active:
                lines.append(f' {Theme.GREEN}{marker} {p}{Theme.RESET}')
            else:
                lines.append(f'   {p}')

        return '\n'.join(lines)
