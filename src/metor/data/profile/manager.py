"""
Module for managing user-profile runtime state and filesystem metadata.
Enforces validation checks to prevent runtime operation on tampered profiles.
"""

from pathlib import Path
from typing import List, Optional

from metor.utils import Constants, ProcessManager

# Local Package Imports
from metor.data.profile.config import Config
from metor.data.profile.paths import Paths
from metor.data.profile.models import (
    ProfileConfigKey,
    ProfileOperationResult,
    ProfileSecurityMode,
    ProfileSummary,
)


class ProfileManager:
    """Manages one profile's runtime state, configuration, and filesystem paths."""

    @staticmethod
    def _read_int_file(file_path: Path) -> Optional[int]:
        """
        Reads one integer value from a small state file.

        Args:
            file_path (Path): The state file path.

        Returns:
            Optional[int]: The parsed integer, or None if missing or invalid.
        """
        if not file_path.exists():
            return None

        try:
            with file_path.open('r') as f:
                raw_value: str = f.read().strip()
            return int(raw_value)
        except (OSError, ValueError):
            return None

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

    def validate_integrity(self) -> None:
        """
        Validates the JSON integrity of the profile configuration and strictly
        enforces the cryptographic hard-lock for tampered remote profiles.

        Args:
            None

        Raises:
            ValueError: If a corruption or tampering mismatch is detected.

        Returns:
            None
        """
        self.config.validate_integrity()

        security_mode: ProfileSecurityMode = self.get_security_mode()

        if self.is_remote() and security_mode is not ProfileSecurityMode.ENCRYPTED:
            raise ValueError(
                'Profile state corruption detected: remote profiles must keep the default encrypted security metadata.'
            )

        if self.is_remote():
            db_path: Path = self.paths.get_db_file()
            hs_dir: Path = self.paths.get_hidden_service_dir()

            db_exists: bool = db_path.exists()
            hs_exists: bool = hs_dir.exists() and any(hs_dir.iterdir())

            if db_exists or hs_exists:
                raise ValueError(
                    "Profile state corruption detected: 'is_remote' flag is true, "
                    'but local cryptographic keys or databases exist. '
                    'Revert config.json manually or delete the profile.'
                )

        hs_dir = self.paths.get_hidden_service_dir()
        salt_file: Path = hs_dir / 'crypto.salt'
        metor_key_path: Path = hs_dir / Constants.METOR_SECRET_KEY

        if security_mode is ProfileSecurityMode.PLAINTEXT and salt_file.exists():
            raise ValueError(
                "Profile state corruption detected: security_mode is 'plaintext', but encrypted key salt exists. Use the security migration workflow or delete the profile."
            )

        if (
            security_mode is ProfileSecurityMode.ENCRYPTED
            and metor_key_path.exists()
            and not salt_file.exists()
        ):
            raise ValueError(
                "Profile state corruption detected: security_mode is 'encrypted', but the key salt is missing. Use the security migration workflow or delete the profile."
            )

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

    # --- Daemon & Network State ---
    def is_remote(self) -> bool:
        """
        Checks if this profile is configured as a remote client.

        Args:
            None

        Returns:
            bool: True if remote, False otherwise.
        """
        return self.config.get_bool(ProfileConfigKey.IS_REMOTE)

    def get_security_mode(self) -> ProfileSecurityMode:
        """
        Returns the structural storage security mode for this profile.

        Args:
            None

        Returns:
            ProfileSecurityMode: The configured profile security mode.
        """
        return self.config.get_profile_security_mode()

    def uses_encrypted_storage(self) -> bool:
        """
        Indicates whether this profile stores keys and database data encrypted at rest.

        Args:
            None

        Returns:
            bool: True for encrypted storage mode.
        """
        return self.get_security_mode() is ProfileSecurityMode.ENCRYPTED

    def uses_plaintext_storage(self) -> bool:
        """
        Indicates whether this profile stores keys and database data in plaintext.

        Args:
            None

        Returns:
            bool: True for plaintext storage mode.
        """
        return self.get_security_mode() is ProfileSecurityMode.PLAINTEXT

    def supports_password_auth(self) -> bool:
        """
        Indicates whether this profile supports password-based daemon unlock or session auth.

        Args:
            None

        Returns:
            bool: True only for local encrypted-storage profiles.
        """
        return not self.is_remote() and self.uses_encrypted_storage()

    def get_static_port(self) -> Optional[int]:
        """
        Returns the static daemon port if configured.

        Args:
            None

        Returns:
            Optional[int]: The static port, or None.
        """
        val = self.config.get(ProfileConfigKey.DAEMON_PORT)
        return int(str(val)) if val is not None else None

    def set_daemon_port(self, port: int, pid: Optional[int] = None) -> None:
        """
        Saves the active daemon runtime state for this profile.

        Args:
            port (int): The port number to save.
            pid (Optional[int]): The daemon process identifier, if available.

        Returns:
            None
        """
        if not self.exists():
            self.initialize()

        if pid is not None:
            with self.paths.get_daemon_pid_file().open('w') as f:
                f.write(str(pid))
            self.paths.get_daemon_pid_file().chmod(0o600)

        with self.paths.get_daemon_port_file().open('w') as f:
            f.write(str(port))
        self.paths.get_daemon_port_file().chmod(0o600)

    def get_daemon_pid(self) -> Optional[int]:
        """
        Reads the active local daemon PID if present.

        Args:
            None

        Returns:
            Optional[int]: The daemon PID, or None when unavailable.
        """
        if self.is_remote():
            return None

        return self._read_int_file(self.paths.get_daemon_pid_file())

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

        daemon_pid: Optional[int] = self.get_daemon_pid()
        if daemon_pid is not None and not ProcessManager.is_pid_running(daemon_pid):
            self.clear_daemon_port(expected_pid=daemon_pid)
            return None

        return self._read_int_file(self.paths.get_daemon_port_file())

    def clear_daemon_port(
        self,
        expected_pid: Optional[int] = None,
        expected_port: Optional[int] = None,
    ) -> None:
        """
        Clears the local daemon runtime state files.
        When an expected PID or port is provided, state is only removed if this
        profile state still belongs to that daemon instance.

        Args:
            expected_pid (Optional[int]): The daemon PID expected to own the state.
            expected_port (Optional[int]): The daemon IPC port expected to own the state.

        Returns:
            None
        """
        if self.is_remote():
            return

        current_pid: Optional[int] = self.get_daemon_pid()
        current_port: Optional[int] = self._read_int_file(
            self.paths.get_daemon_port_file()
        )

        if (
            expected_pid is not None
            and current_pid is not None
            and current_pid != expected_pid
        ):
            return

        if (
            expected_port is not None
            and current_port is not None
            and current_port != expected_port
        ):
            return

        self.paths.get_daemon_port_file().unlink(missing_ok=True)
        self.paths.get_daemon_pid_file().unlink(missing_ok=True)

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
        return self.get_daemon_port() is not None

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
        from metor.data.profile.catalog import load_default_profile

        return load_default_profile()

    @classmethod
    def set_default_profile(cls, profile_name: str) -> ProfileOperationResult:
        """
        Sets a new default profile.

        Args:
            profile_name (str): New profile name.

        Returns:
            ProfileOperationResult: Structured local outcome for the CLI layer.
        """
        from metor.data.profile.catalog import set_default_profile

        return set_default_profile(profile_name)

    @staticmethod
    def get_all_profiles() -> List[str]:
        """
        Scans the data directory and returns all profile names.

        Args:
            None

        Returns:
            List[str]: List of valid profile folder names.
        """
        from metor.data.profile.catalog import get_all_profiles

        return get_all_profiles()

    @classmethod
    def get_profile_summaries(
        cls, active_profile: Optional[str] = None
    ) -> list[ProfileSummary]:
        """
        Retrieves typed metadata for all profiles.

        Args:
            active_profile (Optional[str]): Current active profile.

        Returns:
            list[ProfileSummary]: Typed local profile summaries.
        """
        from metor.data.profile.catalog import get_profile_summaries

        return get_profile_summaries(active_profile)

    @staticmethod
    def add_profile_folder(
        name: str,
        is_remote: bool = False,
        port: Optional[int] = None,
        security_mode: ProfileSecurityMode = ProfileSecurityMode.ENCRYPTED,
    ) -> ProfileOperationResult:
        """
        Creates a new profile directory safely.

        Args:
            name (str): Profile name.
            is_remote (bool): Is remote configuration.
            port (Optional[int]): Static port.

        Returns:
            ProfileOperationResult: Structured local outcome for the CLI layer.
        """
        from metor.data.profile.lifecycle import add_profile_folder

        return add_profile_folder(name, is_remote, port, security_mode)

    @classmethod
    def migrate_profile_security(
        cls,
        name: str,
        target_mode: ProfileSecurityMode,
        current_password: Optional[str] = None,
        new_password: Optional[str] = None,
    ) -> ProfileOperationResult:
        """
        Migrates one local profile between encrypted and plaintext storage modes.

        Args:
            name (str): Target profile name.
            target_mode (ProfileSecurityMode): The desired storage protection mode.
            current_password (Optional[str]): The current password for encrypted source profiles.
            new_password (Optional[str]): The new password for encrypted target profiles.

        Returns:
            ProfileOperationResult: Structured local outcome for the CLI layer.
        """
        from metor.data.profile.lifecycle import migrate_profile_security

        return migrate_profile_security(
            name,
            target_mode,
            current_password=current_password,
            new_password=new_password,
        )

    @classmethod
    def remove_profile_folder(
        cls, name: str, active_profile: Optional[str] = None
    ) -> ProfileOperationResult:
        """
        Removes a profile completely.

        Args:
            name (str): Target profile.
            active_profile (Optional[str]): The currently running profile to prevent deletion.

        Returns:
            ProfileOperationResult: Structured local outcome for the CLI layer.
        """
        from metor.data.profile.lifecycle import remove_profile_folder

        return remove_profile_folder(name, active_profile)

    @classmethod
    def rename_profile_folder(
        cls, old_name: str, new_name: str
    ) -> ProfileOperationResult:
        """
        Renames an existing profile directory.

        Args:
            old_name (str): Current name.
            new_name (str): New name.

        Returns:
            ProfileOperationResult: Structured local outcome for the CLI layer.
        """
        from metor.data.profile.lifecycle import rename_profile_folder

        return rename_profile_folder(old_name, new_name)

    @classmethod
    def clear_profile_db(cls, name: str) -> ProfileOperationResult:
        """
        Clears the SQLite database for a profile.

        Args:
            name (str): The profile name.

        Returns:
            ProfileOperationResult: Structured local outcome for the CLI layer.
        """
        from metor.data.profile.lifecycle import clear_profile_db

        return clear_profile_db(name)
