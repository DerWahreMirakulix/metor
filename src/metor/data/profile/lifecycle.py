"""Create, rename, clear, and remove current profiles."""

import re
from contextlib import ExitStack
from functools import partial
from typing import TYPE_CHECKING, Optional

from metor.data import SettingKey, Settings, SettingValidationError, SqlManager
from metor.utils import Constants, FileLock, ProcessManager, secure_remove_path

# Local Package Imports
from metor.data.profile.models import (
    ProfileConfigKey,
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSecurityMode,
)
from metor.data.profile.paths import Paths
from metor.data.profile.locking import offline_profile_guard
from metor.data.profile.support import normalize_profile_name
from metor.data.profile.catalog import get_all_profiles, load_default_profile

if TYPE_CHECKING:
    from metor.data.profile.manager import ProfileManager


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
    from metor.utils import create_private_directory_tree

    create_private_directory_tree(Constants.DATA, ())
    with FileLock(Constants.DATA / '.profile-catalog'):
        previous_profiles = get_all_profiles()
        result = _add_profile_folder_locked(
            name, is_remote, port, security_mode, master_password
        )
        if result.success and not previous_profiles:
            Settings.set(SettingKey.DEFAULT_PROFILE, normalize_profile_name(name))
        return result


def _add_profile_folder_locked(
    name: str,
    is_remote: bool,
    port: Optional[int],
    security_mode: ProfileSecurityMode,
    master_password: Optional[str],
) -> ProfileOperationResult:
    """Complete one profile creation while the shared catalog lock is held.

    Args:
        name: Requested profile name.
        is_remote: Whether this is a remote entry.
        port: Optional static endpoint.
        security_mode: Local storage protection.
        master_password: One-use initial storage secret.
    Returns:
        ProfileOperationResult: Actual creation result.
    """
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

    try:
        paths = Paths(safe_name)
    except ValueError:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})
    with offline_profile_guard(paths) as offline:
        if not offline:
            return ProfileOperationResult(
                False,
                ProfileOperationType.PROFILE_CREATION_FAILED,
                {'profile': safe_name, 'reason': 'Profile is currently in use.'},
            )
        return _initialize_new_profile_locked(
            safe_name, is_remote, port, security_mode, master_password
        )


def _initialize_new_profile_locked(
    safe_name: str,
    is_remote: bool,
    port: Optional[int],
    security_mode: ProfileSecurityMode,
    master_password: Optional[str],
) -> ProfileOperationResult:
    """Initializes complete storage while catalog, startup and instance gates are held."""
    from metor.data.profile.manager import ProfileManager

    pm = ProfileManager(safe_name)
    if pm.paths.base_dir.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.PROFILE_EXISTS, {'profile': safe_name}
        )
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
        except Exception:
            km.clear_sensitive_state()
            destroy_profile_storage(pm)
            return ProfileOperationResult(
                False,
                ProfileOperationType.PROFILE_CREATION_FAILED,
                {
                    'profile': safe_name,
                    'reason': (
                        'A master password is required for encrypted profiles.'
                        if not master_password
                        else 'Profile creation failed.'
                    ),
                },
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


def remove_profile_folder(
    name: str,
    active_profile: Optional[str] = None,
) -> ProfileOperationResult:
    """Serialize confirmed removal with creation and default reconciliation.

    Args:
        name: Requested profile name.
        active_profile: Authenticated active profile to protect.
    Returns:
        ProfileOperationResult: Actual removal and default outcome.
    """
    if not Constants.DATA.exists():
        return _remove_profile_folder_locked(name, active_profile)
    with FileLock(Constants.DATA / '.profile-catalog'):
        return _remove_profile_folder_locked(name, active_profile)


def _remove_profile_folder_locked(
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
    from metor.data.profile.manager import ProfileManager

    default = load_default_profile()
    active = active_profile
    safe_name = normalize_profile_name(name)
    if not safe_name:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})
    try:
        target_dir = Paths(safe_name).base_dir
    except ValueError:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})
    if active == safe_name:
        return ProfileOperationResult(
            False, ProfileOperationType.CANNOT_REMOVE_ACTIVE, {}
        )
    if not target_dir.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.PROFILE_NOT_FOUND, {'profile': safe_name}
        )
    with offline_profile_guard(Paths(safe_name)) as offline:
        if not offline:
            return ProfileOperationResult(
                False,
                ProfileOperationType.CANNOT_REMOVE_RUNNING,
                {'profile': safe_name},
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
        remaining = get_all_profiles()
        if default == safe_name or (len(remaining) == 1 and default not in remaining):
            Settings.set(
                SettingKey.DEFAULT_PROFILE, remaining[0] if len(remaining) == 1 else ''
            )
        return ProfileOperationResult(
            True, ProfileOperationType.PROFILE_REMOVED, {'profile': safe_name}
        )


def rename_profile_folder(old_name: str, new_name: str) -> ProfileOperationResult:
    """Serialize rename with catalog creation and default reconciliation.

    Args:
        old_name: Existing profile name.
        new_name: Requested replacement name.
    Returns:
        ProfileOperationResult: Actual rename and default outcome.
    """
    if not Constants.DATA.exists():
        return _rename_profile_folder_locked(old_name, new_name)
    with FileLock(Constants.DATA / '.profile-catalog'):
        return _rename_profile_folder_locked(old_name, new_name)


def _rename_profile_folder_locked(
    old_name: str, new_name: str
) -> ProfileOperationResult:
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
    if not safe_old or not safe_new:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})
    try:
        old_dir = Paths(safe_old).base_dir
        new_dir = Paths(safe_new).base_dir
    except ValueError:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})
    if not old_dir.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.PROFILE_NOT_FOUND, {'profile': safe_old}
        )
    if new_dir.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.PROFILE_EXISTS, {'profile': safe_new}
        )
    with offline_profile_guard(Paths(safe_old)) as offline:
        if not offline:
            return ProfileOperationResult(
                False,
                ProfileOperationType.CANNOT_RENAME_RUNNING,
                {'old_profile': safe_old},
            )
        pm = ProfileManager(safe_old)
        if pm.is_daemon_running() and not pm.is_remote():
            return ProfileOperationResult(
                False,
                ProfileOperationType.CANNOT_RENAME_RUNNING,
                {'old_profile': safe_old},
            )
        old_dir.rename(new_dir)
        if load_default_profile() == safe_old:
            try:
                Settings.set(
                    SettingKey.DEFAULT_PROFILE, safe_new, expected_value=safe_old
                )
            except SettingValidationError:
                pass
            except OSError:
                return ProfileOperationResult(
                    False,
                    ProfileOperationType.RENAMED_DEFAULT_UNCONFIRMED,
                    {'old_profile': safe_old, 'new_profile': safe_new},
                )
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
    try:
        pm = ProfileManager(safe_name)
    except ValueError:
        return ProfileOperationResult(False, ProfileOperationType.INVALID_NAME, {})
    if not pm.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.PROFILE_NOT_FOUND, {'profile': safe_name}
        )
    with offline_profile_guard(pm.paths) as offline:
        if not offline or (pm.is_daemon_running() and not pm.is_remote()):
            return ProfileOperationResult(
                False,
                ProfileOperationType.CANNOT_CLEAR_RUNNING_DB,
                {'profile': safe_name},
            )
        return _clear_offline_storage(pm, master_password)


def _clear_offline_storage(
    pm: 'ProfileManager', master_password: str | None
) -> ProfileOperationResult:
    """Clear SQL and its owned objects under the offline profile lifecycle gate."""
    safe_name = pm.profile_name
    db_path = pm.paths.get_db_file()
    if not db_path.exists():
        return ProfileOperationResult(
            False, ProfileOperationType.DATABASE_NOT_FOUND, {'profile': safe_name}
        )
    from metor.data.blob import BlobStore, delete_owned_blob, open_blob_store

    key_manager = None
    blob_store: BlobStore | None = None
    try:
        encryption_key = None
        if pm.uses_encrypted_storage():
            from metor.core.key import KeyManager

            key_manager = KeyManager(pm, master_password)
            encryption_key = key_manager.get_database_key()
        sql = SqlManager(db_path, pm.config, encryption_key)
        blob_store = open_blob_store(
            pm, key_manager.get_blob_key if key_manager else None
        )
        sql.clear_all_profile_data()
        if not sql.messages.finish_voice_deletions(
            partial(delete_owned_blob, blob_store)
        ):
            raise OSError('Voice object cleanup still pending.')
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
        if blob_store is not None:
            blob_store.close()
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
    from metor.data.profile.catalog import get_all_profiles
    from metor.data.profile.manager import ProfileManager

    if not Constants.DATA.exists():
        return
    # Stable gate files must survive the wipe. Replacing a gate while it is
    # locked would split present and future clients across different inodes.
    catalog = FileLock(Constants.DATA / '.profile-catalog')
    with catalog, ExitStack() as guards:
        names = set(get_all_profiles())
        # A mode change can briefly have its source renamed to backup before
        # activating its target. The sibling journal still names that profile.
        for entry in Constants.DATA.glob('.*.security-migration.json'):
            name = entry.name[1:].removesuffix('.security-migration.json')
            if normalize_profile_name(name) == name and name:
                names.add(name)
        for name in sorted(names):
            guards.enter_context(FileLock(Paths(name).get_daemon_start_lock_file()))
        profiles = [ProfileManager(name) for name in sorted(names)]
        ProcessManager.cleanup_processes()
        for pm in profiles:
            guards.enter_context(FileLock(pm.paths.get_daemon_instance_lock_file()))
            for pid_file, role in (
                (pm.paths.get_daemon_pid_file(), Constants.PROCESS_ROLE_DAEMON),
                (pm.paths.get_tor_data_dir() / 'tor.pid', Constants.PROCESS_ROLE_TOR),
            ):
                if pid_file.exists() and not ProcessManager.recorded_lifetime_ended(
                    pid_file, pm.profile_name, role
                ):
                    raise OSError('Cannot confirm release of all managed processes.')
        for pm in profiles:
            destroy_profile_storage(pm)
        for child in Constants.DATA.iterdir():
            if child == catalog.lock_path or (
                child.is_file()
                and not child.is_symlink()
                and re.fullmatch(
                    r'\.(daemon-start|daemon-instance|security-migration)\.[a-f0-9]{64}\.lock',
                    child.name,
                )
            ):
                continue
            secure_remove_path(child)
