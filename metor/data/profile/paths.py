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

    def get_config_dir(self) -> Path:
        """
        Retrieves and ensures the configuration directory exists.

        Args:
            None

        Returns:
            Path: The path object to the config directory.
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)
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
        Retrieves and ensures correct permissions for the Tor hidden service directory.

        Args:
            None

        Returns:
            Path: The hidden service directory path.
        """
        hs_dir: Path = self.get_config_dir() / Constants.HIDDEN_SERVICE_DIR
        hs_dir.mkdir(mode=0o700, exist_ok=True)
        hs_dir.chmod(0o700)
        return hs_dir

    def get_tor_data_dir(self) -> Path:
        """
        Retrieves and ensures correct permissions for the Tor data directory.

        Args:
            None

        Returns:
            Path: The Tor data directory path.
        """
        data_dir: Path = self.get_config_dir() / Constants.TOR_DATA_DIR
        data_dir.mkdir(mode=0o700, exist_ok=True)
        data_dir.chmod(0o700)
        return data_dir

    def get_db_file(self) -> Path:
        """
        Returns the path to the SQLite database file.

        Args:
            None

        Returns:
            Path: The database file path.
        """
        return self.get_config_dir() / Constants.DB_FILE
