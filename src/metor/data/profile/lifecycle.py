"""Public profile lifecycle operations and compatibility entry points."""

from typing import Optional

from metor.data import SettingKey, Settings, SqlManager
from metor.utils import Constants, secure_remove_path

# Local Package Imports
from metor.data.profile import migration
from metor.data.profile.models import (
    ProfileConfigKey,
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSecurityMode,
)
from metor.data.profile.support import normalize_profile_name


def recover_profile_security_migration(profile_name: str) -> None:
    """Recovers an interrupted profile security migration before profile access.

    Args:
        profile_name (str): Local profile name whose sibling journal is checked.

    Returns:
        None
    """
    migration.recover_profile_security_migration(profile_name)


def add_profile_folder(
    name: str,
    is_remote: bool = False,
    port: Optional[int] = None,
    security_mode: ProfileSecurityMode = ProfileSecurityMode.ENCRYPTED,
    master_password: Optional[str] = None,
) -> ProfileOperationResult:
    """Creates one new profile directory safely.

    Args:
        name (str): The requested profile name.
        is_remote (bool): Whether the profile represents a remote daemon.
        port (Optional[int]): The optional static daemon port.
        security_mode (ProfileSecurityMode): The requested storage protection mode.
        master_password (Optional[str]): Password for encrypted local storage.

    Returns:
        ProfileOperationResult: Structured local outcome for the CLI layer.
    """
    from metor.data.profile.manager import ProfileManager

    safe_name = normalize_profile_name(name)
    if not safe_name:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})
    if is_remote and not port:
        return ProfileOperationResult(
            False, ProfileOperationType.REMOTE_PORT_REQUIRED, {}
        )
    if is_remote and security_mode is ProfileSecurityMode.PLAINTEXT:
        return ProfileOperationResult(
            False, ProfileOperationType.PASSWORDLESS_REMOTE_NOT_ALLOWED, {}
        )
    if security_mode is ProfileSecurityMode.PLAINTEXT and not Settings.get_bool(
        SettingKey.ALLOW_PLAINTEXT_PROFILES
    ):
        return ProfileOperationResult(
            False,
            ProfileOperationType.PLAINTEXT_PROFILES_DISABLED,
            {'profile': safe_name},
        )

    target_dir = Constants.DATA / safe_name
    if target_dir.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.PROFILE_EXISTS, {'profile': safe_name}
        )
    recover_profile_security_migration(safe_name)
    pm = ProfileManager(safe_name)
    pm.initialize()
    if security_mode is not ProfileSecurityMode.ENCRYPTED:
        pm.config.set(
            ProfileConfigKey.SECURITY_MODE,
            security_mode.value,
            allow_mutating_structural_keys=True,
        )

    if not is_remote and security_mode is ProfileSecurityMode.ENCRYPTED:
        from metor.core.key import KeyManager
        from metor.core.profile_destruction import destroy_profile_storage

        km = KeyManager(pm, password=master_password)
        try:
            if not master_password:
                raise ValueError(
                    'A master password is required for encrypted profiles.'
                )
            km.unlock_profile_keys()
            km.generate_keys()
            SqlManager(pm.paths.get_db_file(), pm.config, km.get_database_key())
            SqlManager.close_connection(pm.paths.get_db_file())
        except Exception as exc:
            km.clear_sensitive_state()
            destroy_profile_storage(pm)
            return ProfileOperationResult(
                False,
                ProfileOperationType.PROFILE_CREATION_FAILED,
                {'profile': safe_name, 'reason': str(exc)},
            )
        km.clear_sensitive_state()

    if is_remote or port:
        if is_remote:
            pm.config.set(
                ProfileConfigKey.IS_REMOTE,
                True,
                allow_mutating_structural_keys=True,
            )
        if port:
            pm.config.set(ProfileConfigKey.DAEMON_PORT, port)
        remote_tag = 'Remote ' if is_remote else 'Static '
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
    """Migrates one local profile between encrypted and plaintext storage modes.

    Args:
        name (str): The target profile name.
        target_mode (ProfileSecurityMode): The desired storage protection mode.
        current_password (Optional[str]): The current password for encrypted source profiles.
        new_password (Optional[str]): The new password for encrypted target profiles.

    Returns:
        ProfileOperationResult: Structured local outcome for the CLI layer.
    """
    return migration.migrate_profile_security(
        name,
        target_mode,
        current_password,
        new_password,
    )


def remove_profile_folder(
    name: str,
    active_profile: Optional[str] = None,
) -> ProfileOperationResult:
    """Removes one profile completely.

    Args:
        name (str): The target profile name.
        active_profile (Optional[str]): The currently active profile to protect.

    Returns:
        ProfileOperationResult: Structured local outcome for the CLI layer.
    """
    from metor.data.profile.catalog import load_default_profile
    from metor.data.profile.manager import ProfileManager

    default = load_default_profile()
    active = active_profile if active_profile else default
    safe_name = normalize_profile_name(name)
    if not safe_name:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})
    target_dir = Constants.DATA / safe_name
    if active == safe_name:
        return ProfileOperationResult(
            False, ProfileOperationType.CANNOT_REMOVE_ACTIVE, {}
        )
    if default == safe_name:
        return ProfileOperationResult(
            False, ProfileOperationType.CANNOT_REMOVE_DEFAULT, {}
        )
    if not target_dir.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.PROFILE_NOT_FOUND, {'profile': safe_name}
        )
    pm = ProfileManager(safe_name)
    if pm.is_daemon_running() and not pm.is_remote():
        return ProfileOperationResult(
            False,
            ProfileOperationType.CANNOT_REMOVE_RUNNING,
            {'profile': safe_name},
        )
    from metor.core.profile_destruction import destroy_profile_storage

    destroy_profile_storage(pm)
    return ProfileOperationResult(
        True, ProfileOperationType.PROFILE_REMOVED, {'profile': safe_name}
    )


def rename_profile_folder(old_name: str, new_name: str) -> ProfileOperationResult:
    """Renames one existing profile directory.

    Args:
        old_name (str): The current profile name.
        new_name (str): The requested new profile name.

    Returns:
        ProfileOperationResult: Structured local outcome for the CLI layer.
    """
    from metor.data.profile.manager import ProfileManager

    safe_old = normalize_profile_name(old_name)
    safe_new = normalize_profile_name(new_name)
    old_dir = Constants.DATA / safe_old
    new_dir = Constants.DATA / safe_new
    if not old_dir.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.PROFILE_NOT_FOUND, {'profile': safe_old}
        )
    if new_dir.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.PROFILE_EXISTS, {'profile': safe_new}
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


def clear_profile_db(
    name: str,
    master_password: Optional[str] = None,
) -> ProfileOperationResult:
    """Clears the SQLite database for one profile.

    Args:
        name (str): The target profile name.
        master_password (Optional[str]): Required credential for encrypted storage.

    Returns:
        ProfileOperationResult: Structured local outcome for the CLI layer.
    """
    from metor.data.profile.manager import ProfileManager

    safe_name = normalize_profile_name(name)
    if not safe_name:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})
    pm = ProfileManager(safe_name)
    if not pm.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.PROFILE_NOT_FOUND, {'profile': safe_name}
        )
    if pm.is_daemon_running() and not pm.is_remote():
        return ProfileOperationResult(
            False,
            ProfileOperationType.CANNOT_CLEAR_RUNNING_DB,
            {'profile': safe_name},
        )
    db_path = pm.paths.get_db_file()
    if not db_path.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.DATABASE_NOT_FOUND, {'profile': safe_name}
        )
    key_manager = None
    try:
        encryption_key = None
        if pm.uses_encrypted_storage():
            from metor.core.key import KeyManager

            key_manager = KeyManager(pm, master_password)
            encryption_key = key_manager.get_database_key()
        sql = SqlManager(db_path, pm.config, encryption_key)
        sql.clear_all_profile_data()
        SqlManager.close_connection(db_path)
        return ProfileOperationResult(
            True, ProfileOperationType.DATABASE_CLEARED, {'profile': safe_name}
        )
    except Exception:
        SqlManager.close_connection(db_path)
        return ProfileOperationResult(
            False, ProfileOperationType.DATABASE_CLEAR_FAILED, {}
        )
    finally:
        if key_manager is not None:
            key_manager.clear_sensitive_state()


def purge_all_profile_data() -> None:
    """Destroys every local keyslot before removing the global data tree.

    Args:
        None

    Returns:
        None
    """
    from metor.core.profile_destruction import destroy_profile_storage
    from metor.data.profile.manager import ProfileManager

    if not Constants.DATA.exists():
        return
    for entry in tuple(Constants.DATA.iterdir()):
        if entry.is_dir():
            destroy_profile_storage(ProfileManager(entry.name))
    secure_remove_path(Constants.DATA)
