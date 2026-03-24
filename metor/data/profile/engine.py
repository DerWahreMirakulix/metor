"""
Module for managing user profiles, their directories, and daemon lock states.
"""

import shutil
from pathlib import Path
from typing import List, Tuple, Optional

from metor.data.settings import SettingKey, Settings
from metor.data.sql import SqlManager
from metor.ui.theme import Theme
from metor.utils.constants import Constants

# Local Package Imports
from metor.data.profile.config import Config
from metor.data.profile.paths import Paths
from metor.data.profile.models import ProfileConfigKey


class ProfileManager:
    """High-level orchestrator for profile states, daemons, and metadata."""

    def __init__(self, profile_name: Optional[str] = None) -> None:
        """
        Initializes the ProfileManager.

        Args:
            profile_name (Optional[str]): Target profile name, or default if None.

        Returns:
            None
        """
        self.profile_name: str = (
            profile_name if profile_name else self.load_default_profile()
        )
        self.paths: Paths = Paths(self.profile_name)
        self.config: Config = Config(self.paths)

    # --- Directory Compatibility Proxies for existing architecture ---
    def get_config_dir(self) -> str:
        """
        Returns the config dir as a string for compatibility with older modules.

        Args:
            None

        Returns:
            str: Directory path.
        """
        return str(self.paths.get_config_dir())

    def get_hidden_service_dir(self) -> str:
        """
        Returns HS dir as a string.

        Args:
            None

        Returns:
            str: Directory path.
        """
        return str(self.paths.get_hidden_service_dir())

    def get_tor_data_dir(self) -> str:
        """
        Returns Tor data dir as a string.

        Args:
            None

        Returns:
            str: Directory path.
        """
        return str(self.paths.get_tor_data_dir())

    # --- Daemon & Network State ---
    def is_remote(self) -> bool:
        """
        Checks if this profile is configured as a remote client.

        Args:
            None

        Returns:
            bool: True if remote, False otherwise.
        """
        return bool(self.config.get(ProfileConfigKey.IS_REMOTE, False))

    def get_static_port(self) -> Optional[int]:
        """
        Returns the static daemon port if configured.

        Args:
            None

        Returns:
            Optional[int]: The static port, or None.
        """
        return self.config.get(ProfileConfigKey.DAEMON_PORT)

    def set_daemon_port(self, port: int) -> None:
        """
        Saves the given port number to the daemon port file.

        Args:
            port (int): The port number to save.

        Returns:
            None
        """
        with self.paths.get_daemon_port_file().open('w') as f:
            f.write(str(port))

    def get_daemon_port(self) -> Optional[int]:
        """
        Reads the active daemon port.

        Args:
            None

        Returns:
            Optional[int]: The active daemon port, or None.
        """
        if self.is_remote():
            return self.get_static_port()

        port_file: Path = self.paths.get_daemon_port_file()
        if port_file.exists():
            try:
                with port_file.open('r') as f:
                    return int(f.read().strip())
            except Exception:
                pass
        return None

    def clear_daemon_port(self) -> None:
        """
        Deletes the daemon port file to signal stopped daemon.

        Args:
            None

        Returns:
            None
        """
        self.paths.get_daemon_port_file().unlink(missing_ok=True)

    def is_daemon_running(self) -> bool:
        """
        Checks if the daemon is currently active.

        Args:
            None

        Returns:
            bool: True if running, False otherwise.
        """
        if self.is_remote():
            return True
        return self.paths.get_daemon_port_file().exists()

    # --- Class Methods for Global Profile Operations ---
    @classmethod
    def load_default_profile(cls) -> str:
        """
        Retrieves the default profile from settings.

        Args:
            None

        Returns:
            str: Default profile name.
        """
        return Settings.get(SettingKey.DEFAULT_PROFILE)

    @classmethod
    def set_default_profile(cls, profile_name: str) -> Tuple[bool, str]:
        """
        Sets a new default profile.

        Args:
            profile_name (str): New profile name.

        Returns:
            Tuple[bool, str]: Status.
        """
        safe_name: str = ''.join(
            c for c in profile_name if c.isalnum() or c in ('-', '_')
        )
        if not safe_name:
            return False, 'Invalid profile name.'
        Settings.set(SettingKey.DEFAULT_PROFILE, safe_name)
        return True, f"Default profile permanently set to '{safe_name}'."

    @staticmethod
    def get_all_profiles() -> List[str]:
        """
        Scans the data directory and returns all profile names.

        Args:
            None

        Returns:
            List[str]: List of valid profile folder names.
        """
        data_dir: Path = Constants.DATA
        if not data_dir.exists():
            return []

        ignored_folders = {Constants.HIDDEN_SERVICE_DIR, Constants.TOR_DATA_DIR}
        return [
            d.name
            for d in data_dir.iterdir()
            if d.is_dir() and d.name not in ignored_folders
        ]

    @staticmethod
    def add_profile_folder(
        name: str, is_remote: bool = False, port: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Creates a new profile directory safely.

        Args:
            name (str): Profile name.
            is_remote (bool): Is remote configuration.
            port (Optional[int]): Static port.

        Returns:
            Tuple[bool, str]: Success flag and message.
        """
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))
        if not safe_name:
            return False, 'Invalid profile name.'

        if is_remote and not port:
            return False, 'A remote profile requires a static port (--port <int>).'

        target_dir: Path = Constants.DATA / safe_name
        if target_dir.exists():
            return False, f"Profile '{safe_name}' already exists."

        target_dir.mkdir(parents=True)

        if is_remote or port:
            pm = ProfileManager(safe_name)
            if is_remote:
                pm.config.set(ProfileConfigKey.IS_REMOTE, True)
            if port:
                pm.config.set(ProfileConfigKey.DAEMON_PORT, port)

            remote_tag: str = 'Remote ' if is_remote else 'Static '
            return (
                True,
                f"{remote_tag}profile '{safe_name}' successfully created (Port {port}).",
            )

        return True, f"Profile '{safe_name}' successfully created."

    @classmethod
    def remove_profile_folder(
        cls, name: str, active_profile: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Removes a profile completely.

        Args:
            name (str): Target profile.
            active_profile (Optional[str]): The currently running profile to prevent deletion.

        Returns:
            Tuple[bool, str]: Success flag and message.
        """
        default: str = cls.load_default_profile()
        active: str = active_profile if active_profile else default
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))

        if not safe_name:
            return False, 'Invalid profile name.'

        target_dir: Path = Constants.DATA / safe_name

        if active == safe_name:
            return (
                False,
                'Cannot remove active profile! Switch to another profile first.',
            )
        if default == safe_name:
            return False, 'Cannot remove default profile! Change default first.'
        if not target_dir.exists():
            return False, f"Profile '{safe_name}' does not exist."

        pm = cls(safe_name)
        if pm.is_daemon_running() and not pm.is_remote():
            return (
                False,
                f"Cannot remove profile '{safe_name}' while its daemon is running!",
            )

        shutil.rmtree(target_dir)
        return True, f"Profile '{safe_name}' successfully removed."

    @classmethod
    def rename_profile_folder(cls, old_name: str, new_name: str) -> Tuple[bool, str]:
        """
        Renames an existing profile directory.

        Args:
            old_name (str): Current name.
            new_name (str): New name.

        Returns:
            Tuple[bool, str]: Status.
        """
        safe_old: str = ''.join(c for c in old_name if c.isalnum() or c in ('-', '_'))
        safe_new: str = ''.join(c for c in new_name if c.isalnum() or c in ('-', '_'))

        old_dir: Path = Constants.DATA / safe_old
        new_dir: Path = Constants.DATA / safe_new

        if not old_dir.exists():
            return False, f"Profile '{safe_old}' does not exist."
        if new_dir.exists():
            return False, f"Profile '{safe_new}' already exists."

        pm = cls(safe_old)
        if pm.is_daemon_running() and not pm.is_remote():
            return (
                False,
                f"Cannot rename profile '{safe_old}' while its daemon is running!",
            )

        old_dir.rename(new_dir)
        return True, f"Profile '{safe_old}' successfully renamed to '{safe_new}'."

    @classmethod
    def clear_profile_db(cls, name: str) -> Tuple[bool, str]:
        """
        Clears the SQLite database for a profile.

        Args:
            name (str): The profile name.

        Returns:
            Tuple[bool, str]: Success flag and message.
        """
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))
        if not safe_name:
            return False, 'Invalid profile name.'

        pm = cls(safe_name)
        if pm.is_daemon_running() and not pm.is_remote():
            return (
                False,
                f"Cannot clear database for '{safe_name}' while daemon is running.",
            )

        db_path: Path = pm.paths.get_db_file()
        if not db_path.exists():
            return False, f"No database found for profile '{safe_name}'."

        try:
            sql = SqlManager(db_path)  # Accepts Path now
            sql.execute('DELETE FROM history')
            sql.execute('DELETE FROM messages')
            sql.execute('DELETE FROM contacts')
            return True, f"Database for profile '{safe_name}' successfully cleared."
        except Exception:
            return False, 'Error clearing database.'

    @classmethod
    def show(cls, active_profile: Optional[str] = None) -> str:
        """
        Returns a formatted string representing all profiles.

        Args:
            active_profile (Optional[str]): Current profile.

        Returns:
            str: Formatted string.
        """
        active: str = active_profile if active_profile else cls.load_default_profile()
        profiles: List[str] = cls.get_all_profiles()
        if not profiles:
            return 'No profiles found.'

        lines: List[str] = ['Available profiles:']
        for p in profiles:
            pm = ProfileManager(p)
            marker: str = '*' if p == active else ' '
            tags: List[str] = []

            if pm.is_remote():
                tags.append('REMOTE')
            elif pm.get_static_port():
                tags.append(f'PORT:{pm.get_static_port()}')

            tag_str: str = (
                f' [{Theme.YELLOW}{"|".join(tags)}{Theme.RESET}]' if tags else ''
            )

            if p == active:
                lines.append(f' {Theme.GREEN}{marker} {p}{Theme.RESET}{tag_str}')
            else:
                lines.append(f'   {p}{tag_str}')

        return '\n'.join(lines)
