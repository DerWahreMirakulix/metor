"""
Module for managing user profiles, their directories, and daemon lock states.
"""

import shutil
from pathlib import Path
from typing import List, Tuple, Optional, Set, Dict, Any

from metor.core.api import TransCode
from metor.data import SettingKey, Settings, SqlManager
from metor.utils import Constants

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

    def exists(self) -> bool:
        """
        Checks if the profile physically exists on disk.

        Args:
            None

        Returns:
            bool: True if it exists, False otherwise.
        """
        return self.paths.exists()

    def initialize(self) -> None:
        """
        Explicitly creates the profile filesystem structure with strict permissions.

        Args:
            None

        Returns:
            None
        """
        self.paths.create_directories()

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
        if not self.exists():
            self.initialize()
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
    def set_default_profile(
        cls, profile_name: str
    ) -> Tuple[bool, TransCode, Dict[str, Any]]:
        """
        Sets a new default profile.

        Args:
            profile_name (str): New profile name.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any]]: A success flag, domain state code, and parameters.
        """
        safe_name: str = ''.join(
            c for c in profile_name if c.isalnum() or c in ('-', '_')
        )
        if not safe_name:
            return False, TransCode.INVALID_PROFILE_NAME, {}
        Settings.set(SettingKey.DEFAULT_PROFILE, safe_name)
        return True, TransCode.PROFILE_SET_DEFAULT, {'profile': safe_name}

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

        ignored_folders: Set[str] = {
            Constants.HIDDEN_SERVICE_DIR,
            Constants.TOR_DATA_DIR,
        }
        return [
            d.name
            for d in data_dir.iterdir()
            if d.is_dir() and d.name not in ignored_folders
        ]

    @classmethod
    def get_profiles_data(cls, active_profile: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves raw metadata for all profiles.

        Args:
            active_profile (Optional[str]): Current active profile.

        Returns:
            Dict[str, Any]: Profile data dictionary.
        """
        active: str = active_profile if active_profile else cls.load_default_profile()
        profiles: List[str] = cls.get_all_profiles()
        profile_list: List[Dict[str, Any]] = []

        for p in profiles:
            pm: 'ProfileManager' = cls(p)
            profile_list.append(
                {
                    'name': p,
                    'is_active': p == active,
                    'is_remote': pm.is_remote(),
                    'port': pm.get_static_port(),
                }
            )

        return {'profiles': profile_list}

    @staticmethod
    def add_profile_folder(
        name: str, is_remote: bool = False, port: Optional[int] = None
    ) -> Tuple[bool, TransCode, Dict[str, Any]]:
        """
        Creates a new profile directory safely.

        Args:
            name (str): Profile name.
            is_remote (bool): Is remote configuration.
            port (Optional[int]): Static port.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any]]: A success flag, domain state code, and parameters.
        """
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))
        if not safe_name:
            return False, TransCode.INVALID_PROFILE_NAME, {}

        if is_remote and not port:
            return False, TransCode.REMOTE_REQUIRES_PORT, {}

        target_dir: Path = Constants.DATA / safe_name
        if target_dir.exists():
            return False, TransCode.PROFILE_EXISTS, {'profile': safe_name}

        pm: 'ProfileManager' = ProfileManager(safe_name)
        pm.initialize()

        if is_remote or port:
            if is_remote:
                pm.config.set(ProfileConfigKey.IS_REMOTE, True)
            if port:
                pm.config.set(ProfileConfigKey.DAEMON_PORT, port)

            remote_tag: str = 'Remote ' if is_remote else 'Static '
            return (
                True,
                TransCode.PROFILE_CREATED_PORT,
                {'remote_tag': remote_tag, 'profile': safe_name, 'port': port},
            )

        return True, TransCode.PROFILE_CREATED, {'profile': safe_name}

    @classmethod
    def remove_profile_folder(
        cls, name: str, active_profile: Optional[str] = None
    ) -> Tuple[bool, TransCode, Dict[str, Any]]:
        """
        Removes a profile completely.

        Args:
            name (str): Target profile.
            active_profile (Optional[str]): The currently running profile to prevent deletion.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any]]: A success flag, domain state code, and parameters.
        """
        default: str = cls.load_default_profile()
        active: str = active_profile if active_profile else default
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))

        if not safe_name:
            return False, TransCode.INVALID_PROFILE_NAME, {}

        target_dir: Path = Constants.DATA / safe_name

        if active == safe_name:
            return (
                False,
                TransCode.CANT_REMOVE_ACTIVE_PROFILE,
                {},
            )
        if default == safe_name:
            return False, TransCode.CANT_REMOVE_DEFAULT_PROFILE, {}
        if not target_dir.exists():
            return False, TransCode.PROFILE_NOT_FOUND, {'profile': safe_name}

        pm: 'ProfileManager' = cls(safe_name)
        if pm.is_daemon_running() and not pm.is_remote():
            return (
                False,
                TransCode.DAEMON_RUNNING_CANT_REMOVE,
                {'profile': safe_name},
            )

        shutil.rmtree(target_dir)
        return True, TransCode.PROFILE_REMOVED, {'profile': safe_name}

    @classmethod
    def rename_profile_folder(
        cls, old_name: str, new_name: str
    ) -> Tuple[bool, TransCode, Dict[str, Any]]:
        """
        Renames an existing profile directory.

        Args:
            old_name (str): Current name.
            new_name (str): New name.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any]]: A success flag, domain state code, and parameters.
        """
        safe_old: str = ''.join(c for c in old_name if c.isalnum() or c in ('-', '_'))
        safe_new: str = ''.join(c for c in new_name if c.isalnum() or c in ('-', '_'))

        old_dir: Path = Constants.DATA / safe_old
        new_dir: Path = Constants.DATA / safe_new

        if not old_dir.exists():
            return False, TransCode.PROFILE_NOT_FOUND, {'profile': safe_old}
        if new_dir.exists():
            return False, TransCode.PROFILE_EXISTS, {'profile': safe_new}

        pm: 'ProfileManager' = cls(safe_old)
        if pm.is_daemon_running() and not pm.is_remote():
            return (
                False,
                TransCode.DAEMON_RUNNING_CANT_RENAME,
                {'old_profile': safe_old},
            )

        old_dir.rename(new_dir)
        return (
            True,
            TransCode.PROFILE_RENAMED,
            {'old_profile': safe_old, 'new_profile': safe_new},
        )

    @classmethod
    def clear_profile_db(cls, name: str) -> Tuple[bool, TransCode, Dict[str, Any]]:
        """
        Clears the SQLite database for a profile.

        Args:
            name (str): The profile name.

        Returns:
            Tuple[bool, TransCode, Dict[str, Any]]: A success flag, domain state code, and parameters.
        """
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))
        if not safe_name:
            return False, TransCode.INVALID_PROFILE_NAME, {}

        pm: 'ProfileManager' = cls(safe_name)
        if not pm.exists():
            return False, TransCode.PROFILE_NOT_FOUND, {'profile': safe_name}

        if pm.is_daemon_running() and not pm.is_remote():
            return (
                False,
                TransCode.DAEMON_RUNNING_CANT_CLEAR_DB,
                {'profile': safe_name},
            )

        db_path: Path = pm.paths.get_db_file()
        if not db_path.exists():
            return False, TransCode.NO_DB_FOUND, {'profile': safe_name}

        try:
            sql: SqlManager = SqlManager(db_path)
            sql.execute('DELETE FROM history')
            sql.execute('DELETE FROM messages')
            sql.execute('DELETE FROM contacts')
            return True, TransCode.DB_CLEARED, {'profile': safe_name}
        except Exception:
            return False, TransCode.DB_CLEAR_FAILED, {}
