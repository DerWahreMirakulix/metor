"""Lifecycle operations for local profile creation, mutation, and cleanup."""

import shutil
from pathlib import Path
from typing import Optional

from metor.data import DatabaseCorruptedError, SqlManager
from metor.utils import Constants, secure_shred_file

# Local Package Imports
from metor.data.profile.models import (
    ProfileConfigKey,
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSecurityMode,
)
from metor.data.profile.support import normalize_profile_name


def add_profile_folder(
    name: str,
    is_remote: bool = False,
    port: Optional[int] = None,
    security_mode: ProfileSecurityMode = ProfileSecurityMode.ENCRYPTED,
) -> ProfileOperationResult:
    """
    Creates one new profile directory safely.

    Args:
        name (str): The requested profile name.
        is_remote (bool): Whether the profile represents a remote daemon.
        port (Optional[int]): The optional static daemon port.
        security_mode (ProfileSecurityMode): The requested storage protection mode.

    Returns:
        ProfileOperationResult: Structured local outcome for the CLI layer.
    """
    from metor.data.profile.manager import ProfileManager

    safe_name: str = normalize_profile_name(name)
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

    pm = ProfileManager(safe_name)
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


def migrate_profile_security(
    name: str,
    target_mode: ProfileSecurityMode,
    current_password: Optional[str] = None,
    new_password: Optional[str] = None,
) -> ProfileOperationResult:
    """
    Migrates one local profile between encrypted and plaintext storage modes.

    Args:
        name (str): The target profile name.
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
    from metor.data.profile.manager import ProfileManager

    safe_name: str = normalize_profile_name(name)
    if not safe_name:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})

    pm = ProfileManager(safe_name)
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


def remove_profile_folder(
    name: str,
    active_profile: Optional[str] = None,
) -> ProfileOperationResult:
    """
    Removes one profile completely.

    Args:
        name (str): The target profile name.
        active_profile (Optional[str]): The currently active profile to protect.

    Returns:
        ProfileOperationResult: Structured local outcome for the CLI layer.
    """
    from metor.data.profile.catalog import load_default_profile
    from metor.data.profile.manager import ProfileManager

    default: str = load_default_profile()
    active: str = active_profile if active_profile else default
    safe_name: str = normalize_profile_name(name)

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

    pm = ProfileManager(safe_name)
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


def rename_profile_folder(old_name: str, new_name: str) -> ProfileOperationResult:
    """
    Renames one existing profile directory.

    Args:
        old_name (str): The current profile name.
        new_name (str): The requested new profile name.

    Returns:
        ProfileOperationResult: Structured local outcome for the CLI layer.
    """
    from metor.data.profile.manager import ProfileManager

    safe_old: str = normalize_profile_name(old_name)
    safe_new: str = normalize_profile_name(new_name)

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

    pm = ProfileManager(safe_old)
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


def clear_profile_db(name: str) -> ProfileOperationResult:
    """
    Clears the SQLite database for one profile.

    Args:
        name (str): The target profile name.

    Returns:
        ProfileOperationResult: Structured local outcome for the CLI layer.
    """
    from metor.data.profile.manager import ProfileManager

    safe_name: str = normalize_profile_name(name)
    if not safe_name:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})

    pm = ProfileManager(safe_name)
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
        sql = SqlManager(db_path, pm.config)
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
