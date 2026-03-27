"""
Module handling filesystem path resolutions for individual profiles.
Enforces strict use of pathlib and manages directory permissions (0o700)
for sensitive cryptographic and Tor data.
"""

from pathlib import Path

from metor.utils.constants import Constants


class Paths:
    """Handles all filesystem path resolutions for a specific profile using pathlib."""

    def __init__(self, profile_name: str) -> None:
        """
        Initializes the path resolver for a profile.

        Args:
            profile_name (str): The name of the profile.

        Returns:
            None
        """
        self.profile_name: str = profile_name
        self.base_dir: Path = Constants.DATA / self.profile_name

    def exists(self) -> bool:
        """
        Checks if the base profile directory physically exists on disk.

        Args:
            None

        Returns:
            bool: True if the directory exists, False otherwise.
        """
        return self.base_dir.is_dir()

    def create_directories(self) -> None:
        """
        Explicitly creates the profile directories and sets strict OPSEC permissions.

        Args:
            None

        Returns:
            None
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)

        hs_dir: Path = self.base_dir / Constants.HIDDEN_SERVICE_DIR
        hs_dir.mkdir(mode=0o700, exist_ok=True)
        hs_dir.chmod(0o700)

        data_dir: Path = self.base_dir / Constants.TOR_DATA_DIR
        data_dir.mkdir(mode=0o700, exist_ok=True)
        data_dir.chmod(0o700)

    def get_config_dir(self) -> Path:
        """
        Retrieves the configuration directory path without auto-creating it.

        Args:
            None

        Returns:
            Path: The path object to the config directory.
        """
        return self.base_dir

    def get_config_file(self) -> Path:
        """
        Returns the path to the config.json.

        Args:
            None

        Returns:
            Path: The config.json file path.
        """
        return self.get_config_dir() / 'config.json'

    def get_daemon_port_file(self) -> Path:
        """
        Returns the path to the daemon IPC port file.

        Args:
            None

        Returns:
            Path: The port file path.
        """
        return self.get_config_dir() / Constants.DAEMON_PORT_FILE

    def get_hidden_service_dir(self) -> Path:
        """
        Retrieves the Tor hidden service directory path without auto-creating it.

        Args:
            None

        Returns:
            Path: The hidden service directory path.
        """
        return self.get_config_dir() / Constants.HIDDEN_SERVICE_DIR

    def get_tor_data_dir(self) -> Path:
        """
        Retrieves the Tor data directory path without auto-creating it.

        Args:
            None

        Returns:
            Path: The Tor data directory path.
        """
        return self.get_config_dir() / Constants.TOR_DATA_DIR

    def get_db_file(self) -> Path:
        """
        Returns the path to the SQLite database file.

        Args:
            None

        Returns:
            Path: The database file path.
        """
        return self.get_config_dir() / Constants.DB_FILE
