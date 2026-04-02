"""
Module for managing user profiles, their directories, and daemon lock states.
Enforces validation checks to prevent runtime operation on tampered profiles.
"""

import shutil
from pathlib import Path
from typing import List, Optional, Set

from metor.core.api import ProfileEntry, ProfilesDataEvent
from metor.data import DatabaseCorruptedError, SettingKey, Settings, SqlManager
from metor.utils import Constants, ProcessManager, secure_shred_file

# Local Package Imports
from metor.data.profile.config import Config
from metor.data.profile.paths import Paths
from metor.data.profile.models import (
    ProfileConfigKey,
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSecurityMode,
)


class ProfileManager:
    """High-level orchestrator for profile states, daemons, and metadata."""

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

        with self.paths.get_daemon_port_file().open('w') as f:
            f.write(str(port))

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
        return Settings.get_str(SettingKey.DEFAULT_PROFILE)

    @classmethod
    def set_default_profile(cls, profile_name: str) -> ProfileOperationResult:
        """
        Sets a new default profile.

        Args:
            profile_name (str): New profile name.

        Returns:
            ProfileOperationResult: Structured local outcome for the CLI layer.
        """
        safe_name: str = ''.join(
            c for c in profile_name if c.isalnum() or c in ('-', '_')
        )
        if not safe_name:
            return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})
        Settings.set(SettingKey.DEFAULT_PROFILE, safe_name)
        return ProfileOperationResult(
            True,
            ProfileOperationType.DEFAULT_SET,
            {'profile': safe_name},
        )

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
    def get_profiles_data(
        cls, active_profile: Optional[str] = None
    ) -> ProfilesDataEvent:
        """
        Retrieves typed metadata for all profiles.

        Args:
            active_profile (Optional[str]): Current active profile.

        Returns:
            ProfilesDataEvent: Typed profile listing DTO.
        """
        active: str = active_profile if active_profile else cls.load_default_profile()
        profiles: List[str] = cls.get_all_profiles()
        profile_list: List[ProfileEntry] = []

        for p in profiles:
            pm: 'ProfileManager' = cls(p)
            profile_list.append(
                ProfileEntry(
                    name=p,
                    is_active=p == active,
                    is_remote=pm.is_remote(),
                    port=pm.get_static_port(),
                )
            )

        return ProfilesDataEvent(profiles=profile_list)

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
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))
        if not safe_name:
            return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})

        if is_remote and not port:
            return ProfileOperationResult(
                False,
                ProfileOperationType.REMOTE_PORT_REQUIRED,
                {},
            )

        if is_remote and security_mode is ProfileSecurityMode.PLAINTEXT:
            return ProfileOperationResult(
                False,
                ProfileOperationType.PASSWORDLESS_REMOTE_NOT_ALLOWED,
                {},
            )

        target_dir: Path = Constants.DATA / safe_name
        if target_dir.exists():
            return ProfileOperationResult(
                False,
                ProfileOperationType.PROFILE_EXISTS,
                {'profile': safe_name},
            )

        pm: 'ProfileManager' = ProfileManager(safe_name)
        pm.initialize()

        if security_mode is not ProfileSecurityMode.ENCRYPTED:
            pm.config.set(
                ProfileConfigKey.SECURITY_MODE,
                security_mode.value,
                allow_mutating_structural_keys=True,
            )

        if is_remote or port:
            if is_remote:
                pm.config.set(
                    ProfileConfigKey.IS_REMOTE,
                    True,
                    allow_mutating_structural_keys=True,
                )
            if port:
                pm.config.set(ProfileConfigKey.DAEMON_PORT, port)

            remote_tag: str = 'Remote ' if is_remote else 'Static '
            return ProfileOperationResult(
                True,
                ProfileOperationType.PROFILE_CREATED_WITH_PORT,
                {
                    'remote_tag': remote_tag,
                    'profile': safe_name,
                    'port': port,
                    'security_mode': security_mode.value,
                },
            )

        return ProfileOperationResult(
            True,
            ProfileOperationType.PROFILE_CREATED,
            {'profile': safe_name, 'security_mode': security_mode.value},
        )

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
        from metor.core.daemon.bootstrap import (
            InvalidMasterPasswordError,
            verify_master_password,
        )
        from metor.core.key import KeyManager

        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))
        if not safe_name:
            return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})

        pm: 'ProfileManager' = cls(safe_name)
        if not pm.exists():
            return ProfileOperationResult(
                False,
                ProfileOperationType.PROFILE_NOT_FOUND,
                {'profile': safe_name},
            )

        if pm.is_remote():
            return ProfileOperationResult(
                False,
                ProfileOperationType.SECURITY_MIGRATION_REMOTE_NOT_ALLOWED,
                {'profile': safe_name},
            )

        if pm.is_daemon_running():
            return ProfileOperationResult(
                False,
                ProfileOperationType.CANNOT_MIGRATE_RUNNING,
                {'profile': safe_name},
            )

        current_mode: ProfileSecurityMode = pm.get_security_mode()
        if current_mode is target_mode:
            return ProfileOperationResult(
                True,
                ProfileOperationType.SECURITY_MODE_UNCHANGED,
                {'profile': safe_name, 'security_mode': current_mode.value},
            )

        old_password: Optional[str] = (
            current_password if current_mode is ProfileSecurityMode.ENCRYPTED else None
        )
        target_password: Optional[str] = (
            new_password if target_mode is ProfileSecurityMode.ENCRYPTED else None
        )

        key_manager = KeyManager(pm, old_password)
        db_path: Path = pm.paths.get_db_file()
        config_dir: Path = pm.paths.get_config_dir()
        runtime_db_path: Path = config_dir / Constants.DB_RUNTIME_FILE
        temp_db_path: Path = config_dir / f'{Constants.DB_FILE}.security-migration'
        backup_db_path: Path = config_dir / f'{Constants.DB_FILE}.security-backup'

        if current_mode is ProfileSecurityMode.ENCRYPTED and (
            key_manager.has_any_key_material() or db_path.exists()
        ):
            if not old_password:
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.SECURITY_MIGRATION_FAILED,
                    {
                        'profile': safe_name,
                        'reason': 'Current master password is required for encrypted profiles.',
                    },
                )

            try:
                verify_master_password(key_manager)
            except InvalidMasterPasswordError:
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.SECURITY_MIGRATION_FAILED,
                    {
                        'profile': safe_name,
                        'reason': 'Current master password is invalid.',
                    },
                )

        if target_mode is ProfileSecurityMode.ENCRYPTED and not target_password:
            return ProfileOperationResult(
                False,
                ProfileOperationType.SECURITY_MIGRATION_FAILED,
                {
                    'profile': safe_name,
                    'reason': 'A new master password is required when migrating to encrypted storage.',
                },
            )

        secure_shred_file(temp_db_path)
        secure_shred_file(backup_db_path)

        try:
            if db_path.exists():
                SqlManager.export_database_copy(
                    db_path,
                    temp_db_path,
                    current_password=old_password,
                    target_password=target_password,
                )

            key_manager.rewrite_password_protection(target_password)

            SqlManager.close_connection(db_path)
            SqlManager.close_connection(temp_db_path)

            if db_path.exists():
                db_path.replace(backup_db_path)

            if temp_db_path.exists():
                temp_db_path.replace(db_path)

            secure_shred_file(runtime_db_path)
            pm.config.set(
                ProfileConfigKey.SECURITY_MODE,
                target_mode.value,
                allow_mutating_structural_keys=True,
            )
        except DatabaseCorruptedError as exc:
            secure_shred_file(temp_db_path)
            return ProfileOperationResult(
                False,
                ProfileOperationType.SECURITY_MIGRATION_FAILED,
                {'profile': safe_name, 'reason': str(exc)},
            )
        except Exception as exc:
            secure_shred_file(temp_db_path)

            if backup_db_path.exists():
                try:
                    SqlManager.close_connection(db_path)
                    secure_shred_file(db_path)
                    backup_db_path.replace(db_path)
                except Exception:
                    pass

            try:
                rollback_key_manager = KeyManager(pm, target_password)
                rollback_key_manager.rewrite_password_protection(old_password)
            except Exception:
                pass

            try:
                pm.config.set(
                    ProfileConfigKey.SECURITY_MODE,
                    current_mode.value,
                    allow_mutating_structural_keys=True,
                )
            except Exception:
                pass

            return ProfileOperationResult(
                False,
                ProfileOperationType.SECURITY_MIGRATION_FAILED,
                {'profile': safe_name, 'reason': str(exc) or 'Migration failed.'},
            )

        if backup_db_path.exists():
            secure_shred_file(backup_db_path)

        return ProfileOperationResult(
            True,
            ProfileOperationType.SECURITY_MODE_MIGRATED,
            {'profile': safe_name, 'security_mode': target_mode.value},
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
        default: str = cls.load_default_profile()
        active: str = active_profile if active_profile else default
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))

        if not safe_name:
            return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})

        target_dir: Path = Constants.DATA / safe_name

        if active == safe_name:
            return ProfileOperationResult(
                False,
                ProfileOperationType.CANNOT_REMOVE_ACTIVE,
                {},
            )
        if default == safe_name:
            return ProfileOperationResult(
                False,
                ProfileOperationType.CANNOT_REMOVE_DEFAULT,
                {},
            )
        if not target_dir.exists():
            return ProfileOperationResult(
                False,
                ProfileOperationType.PROFILE_NOT_FOUND,
                {'profile': safe_name},
            )

        pm: 'ProfileManager' = cls(safe_name)
        if pm.is_daemon_running() and not pm.is_remote():
            return ProfileOperationResult(
                False,
                ProfileOperationType.CANNOT_REMOVE_RUNNING,
                {'profile': safe_name},
            )

        shutil.rmtree(target_dir)
        return ProfileOperationResult(
            True,
            ProfileOperationType.PROFILE_REMOVED,
            {'profile': safe_name},
        )

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
        safe_old: str = ''.join(c for c in old_name if c.isalnum() or c in ('-', '_'))
        safe_new: str = ''.join(c for c in new_name if c.isalnum() or c in ('-', '_'))

        old_dir: Path = Constants.DATA / safe_old
        new_dir: Path = Constants.DATA / safe_new

        if not old_dir.exists():
            return ProfileOperationResult(
                False,
                ProfileOperationType.PROFILE_NOT_FOUND,
                {'profile': safe_old},
            )
        if new_dir.exists():
            return ProfileOperationResult(
                False,
                ProfileOperationType.PROFILE_EXISTS,
                {'profile': safe_new},
            )

        pm: 'ProfileManager' = cls(safe_old)
        if pm.is_daemon_running() and not pm.is_remote():
            return ProfileOperationResult(
                False,
                ProfileOperationType.CANNOT_RENAME_RUNNING,
                {'old_profile': safe_old},
            )

        old_dir.rename(new_dir)
        return ProfileOperationResult(
            True,
            ProfileOperationType.PROFILE_RENAMED,
            {'old_profile': safe_old, 'new_profile': safe_new},
        )

    @classmethod
    def clear_profile_db(cls, name: str) -> ProfileOperationResult:
        """
        Clears the SQLite database for a profile.

        Args:
            name (str): The profile name.

        Returns:
            ProfileOperationResult: Structured local outcome for the CLI layer.
        """
        safe_name: str = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))
        if not safe_name:
            return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})

        pm: 'ProfileManager' = cls(safe_name)
        if not pm.exists():
            return ProfileOperationResult(
                False,
                ProfileOperationType.PROFILE_NOT_FOUND,
                {'profile': safe_name},
            )

        if pm.is_daemon_running() and not pm.is_remote():
            return ProfileOperationResult(
                False,
                ProfileOperationType.CANNOT_CLEAR_RUNNING_DB,
                {'profile': safe_name},
            )

        db_path: Path = pm.paths.get_db_file()
        if not db_path.exists():
            return ProfileOperationResult(
                False,
                ProfileOperationType.DATABASE_NOT_FOUND,
                {'profile': safe_name},
            )

        try:
            sql: SqlManager = SqlManager(db_path, pm.config)
            sql.execute('DELETE FROM history')
            sql.execute('DELETE FROM messages')
            sql.execute('DELETE FROM contacts')
            return ProfileOperationResult(
                True,
                ProfileOperationType.DATABASE_CLEARED,
                {'profile': safe_name},
            )
        except Exception:
            return ProfileOperationResult(
                False,
                ProfileOperationType.DATABASE_CLEAR_FAILED,
                {},
            )
