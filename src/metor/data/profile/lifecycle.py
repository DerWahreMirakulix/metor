"""Lifecycle operations for local profile creation, mutation, cleanup, and recovery."""

import json
import os
import secrets
import shutil
from pathlib import Path
from typing import Optional, cast

from metor.data import DatabaseCorruptedError, SettingKey, Settings, SqlManager
from metor.utils import Constants, secure_remove_path, secure_shred_file

# Local Package Imports
from metor.data.profile.models import (
    ProfileConfigKey,
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSecurityMode,
)
from metor.data.profile.support import normalize_profile_name

_MIGRATION_JOURNAL_VERSION = 1
_MIGRATION_PREPARED = 'prepared'
_MIGRATION_COMMITTED = 'committed'


def _migration_checkpoint(_stage: str) -> None:
    """Provides a private no-op boundary for deterministic lifecycle fault tests.

    Args:
        _stage (str): Named migration transition.

    Returns:
        None
    """


def _migration_paths(profile_name: str) -> tuple[Path, Path, Path]:
    """Returns the durable journal and sibling generation paths for one profile.

    Args:
        profile_name (str): Validated local profile name.

    Returns:
        tuple[Path, Path, Path]: Journal, staged target, and source-backup paths.
    """
    prefix = f'.{profile_name}.security-migration'
    return (
        Constants.DATA / f'{prefix}.json',
        Constants.DATA / f'{prefix}.staged',
        Constants.DATA / f'{prefix}.backup',
    )


def _fsync_directory(directory: Path) -> None:
    """Best-effort syncs one directory after a durable filesystem transition.

    Args:
        directory (Path): Existing directory to synchronize.

    Returns:
        None
    """
    if os.name == 'nt':
        return
    try:
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        pass


def _fsync_tree(path: Path) -> None:
    """Best-effort syncs regular files and directories in a staged profile tree.

    Args:
        path (Path): Staged profile root or child path.

    Returns:
        None
    """
    if path.is_symlink():
        return
    if path.is_file():
        try:
            with path.open('rb') as handle:
                os.fsync(handle.fileno())
        except OSError:
            pass
        return
    if path.is_dir():
        for child in path.iterdir():
            _fsync_tree(child)
        _fsync_directory(path)


def _write_migration_journal(journal_path: Path, profile_name: str, state: str) -> None:
    """Atomically persists one explicit security-migration journal state.

    Args:
        journal_path (Path): Sibling journal path.
        profile_name (str): Validated local profile name.
        state (str): Prepared or committed migration state.

    Returns:
        None
    """
    document = json.dumps(
        {
            'profile': profile_name,
            'state': state,
            'version': _MIGRATION_JOURNAL_VERSION,
        },
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    journal_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp_path = journal_path.parent / f'.{journal_path.name}.{secrets.token_hex(8)}.tmp'
    try:
        with temp_path.open('xb') as handle:
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o600)
        temp_path.replace(journal_path)
        journal_path.chmod(0o600)
        _fsync_directory(journal_path.parent)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_migration_journal(journal_path: Path, profile_name: str) -> str:
    """Reads one strict migration journal without trusting path-like metadata.

    Args:
        journal_path (Path): Existing sibling journal path.
        profile_name (str): Expected validated local profile name.

    Raises:
        ValueError: If the durable migration journal is malformed or unexpected.

    Returns:
        str: The validated migration state.
    """
    try:
        document = json.loads(journal_path.read_text('utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Profile security migration journal is unreadable.') from exc
    if not isinstance(document, dict) or set(document) != {
        'profile',
        'state',
        'version',
    }:
        raise ValueError('Profile security migration journal is invalid.')
    typed_document = cast(dict[str, object], document)
    if (
        typed_document['version'] != _MIGRATION_JOURNAL_VERSION
        or typed_document['profile'] != profile_name
        or typed_document['state'] not in (_MIGRATION_PREPARED, _MIGRATION_COMMITTED)
    ):
        raise ValueError('Profile security migration journal is unsupported.')
    return cast(str, typed_document['state'])


def recover_profile_security_migration(profile_name: str) -> None:
    """Recovers a staged profile migration according to its explicit journal state.

    A prepared journal means the source remains authoritative and its staged target
    is discarded. A committed journal means the staged target is authoritative and
    activation is completed before any profile is opened.

    Args:
        profile_name (str): Local profile name whose sibling journal is checked.

    Raises:
        ValueError: If committed migration state cannot be completed safely.

    Returns:
        None
    """
    safe_name = normalize_profile_name(profile_name)
    if not safe_name:
        return
    journal_path, staged_path, backup_path = _migration_paths(safe_name)
    if not journal_path.exists():
        return
    state = _read_migration_journal(journal_path, safe_name)
    source_path = Constants.DATA / safe_name

    if state == _MIGRATION_PREPARED:
        secure_remove_path(staged_path)
        journal_path.unlink(missing_ok=True)
        _fsync_directory(journal_path.parent)
        return

    if not source_path.exists():
        if not staged_path.exists():
            raise ValueError('Committed profile migration is missing its target.')
        staged_path.replace(source_path)
        _fsync_directory(source_path.parent)
    elif staged_path.exists():
        if backup_path.exists():
            raise ValueError('Committed profile migration has conflicting generations.')
        source_path.replace(backup_path)
        _fsync_directory(source_path.parent)
        staged_path.replace(source_path)
        _fsync_directory(source_path.parent)

    try:
        _migration_checkpoint('during_old_state_cleanup')
        secure_remove_path(backup_path)
    except OSError:
        return
    journal_path.unlink(missing_ok=True)
    _fsync_directory(journal_path.parent)


def add_profile_folder(
    name: str,
    is_remote: bool = False,
    port: Optional[int] = None,
    security_mode: ProfileSecurityMode = ProfileSecurityMode.ENCRYPTED,
    master_password: Optional[str] = None,
) -> ProfileOperationResult:
    """
    Creates one new profile directory safely.

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

    if (
        security_mode is ProfileSecurityMode.PLAINTEXT
        and not Settings.get_bool(SettingKey.ALLOW_PLAINTEXT_PROFILES)
    ):
        return ProfileOperationResult(
            False,
            ProfileOperationType.PLAINTEXT_PROFILES_DISABLED,
            {'profile': safe_name},
        )

    target_dir: Path = Constants.DATA / safe_name
    if target_dir.exists():
        return ProfileOperationResult(
            False,
            ProfileOperationType.PROFILE_EXISTS,
            {'profile': safe_name},
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
    from metor.core.daemon import (
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

    if (
        target_mode is ProfileSecurityMode.PLAINTEXT
        and not Settings.get_bool(SettingKey.ALLOW_PLAINTEXT_PROFILES)
    ):
        return ProfileOperationResult(
            False,
            ProfileOperationType.PLAINTEXT_PROFILES_DISABLED,
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

    db_path: Path = pm.paths.get_db_file()
    journal_path, staged_path, backup_path = _migration_paths(safe_name)
    key_manager = KeyManager(pm, old_password)

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

    try:
        _write_migration_journal(journal_path, safe_name, _MIGRATION_PREPARED)
        secure_remove_path(staged_path)
        secure_remove_path(backup_path)
        shutil.copytree(pm.paths.get_config_dir(), staged_path, symlinks=True)

        staged_pm = ProfileManager(staged_path.name)
        staged_db_path = staged_pm.paths.get_db_file()
        _migration_checkpoint('before_target_db_creation')
        secure_shred_file(staged_db_path)
        current_db_key: Optional[bytes] = (
            key_manager.get_database_key()
            if current_mode is ProfileSecurityMode.ENCRYPTED and db_path.exists()
            else None
        )
        staged_key_manager = KeyManager(staged_pm, old_password)
        try:
            _migration_checkpoint('during_secret_transformation')
            if target_mode is ProfileSecurityMode.ENCRYPTED:
                staged_key_manager.rewrite_password_protection(target_password or '')
                staged_pm.config.set(
                    ProfileConfigKey.SECURITY_MODE,
                    target_mode.value,
                    allow_mutating_structural_keys=True,
                )
                target_db_key: Optional[bytes] = staged_key_manager.get_database_key()
                _migration_checkpoint('after_target_keyslot_creation')
            else:
                if staged_key_manager.has_metor_key():
                    staged_key_manager.rewrite_password_protection(None)
                else:
                    staged_key_manager.clear_sensitive_state()
                    secure_shred_file(staged_pm.paths.get_keyslot_file())
                staged_pm.config.set(
                    ProfileConfigKey.SECURITY_MODE,
                    target_mode.value,
                    allow_mutating_structural_keys=True,
                )
                target_db_key = None

            if db_path.exists():
                _migration_checkpoint('during_db_copy')
                SqlManager.export_database_copy(
                    db_path,
                    staged_db_path,
                    current_key=current_db_key,
                    target_key=target_db_key,
                )
            SqlManager.close_connection(staged_db_path)
            _migration_checkpoint('after_target_db_creation')

            validation_key_manager = KeyManager(staged_pm, target_password)
            try:
                _migration_checkpoint('before_validation')
                validated_key: Optional[bytes] = (
                    validation_key_manager.get_database_key()
                    if target_mode is ProfileSecurityMode.ENCRYPTED
                    else None
                )
                _migration_checkpoint('during_validation')
                SqlManager(staged_db_path, staged_pm.config, validated_key)
                SqlManager.close_connection(staged_db_path)
                if validation_key_manager.has_metor_key():
                    validation_key_manager.get_metor_key()
                staged_pm.validate_integrity()
            finally:
                validation_key_manager.clear_sensitive_state()
        finally:
            staged_key_manager.clear_sensitive_state()

        _fsync_tree(staged_path)
        _migration_checkpoint('immediately_before_commit')
        _write_migration_journal(journal_path, safe_name, _MIGRATION_COMMITTED)
        _migration_checkpoint('immediately_after_commit')
        recover_profile_security_migration(safe_name)
    except DatabaseCorruptedError as exc:
        key_manager.clear_sensitive_state()
        return ProfileOperationResult(
            False,
            ProfileOperationType.SECURITY_MIGRATION_FAILED,
            {'profile': safe_name, 'reason': str(exc)},
        )
    except Exception as exc:
        key_manager.clear_sensitive_state()
        return ProfileOperationResult(
            False,
            ProfileOperationType.SECURITY_MIGRATION_FAILED,
            {'profile': safe_name, 'reason': str(exc) or 'Migration failed.'},
        )

    key_manager.clear_sensitive_state()

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

    from metor.core.profile_destruction import destroy_profile_storage

    destroy_profile_storage(pm)
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


def clear_profile_db(
    name: str,
    master_password: Optional[str] = None,
) -> ProfileOperationResult:
    """
    Clears the SQLite database for one profile.

    Args:
        name (str): The target profile name.
        master_password (Optional[str]): Required credential for encrypted storage.

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

    key_manager = None
    try:
        encryption_key: Optional[bytes] = None
        if pm.uses_encrypted_storage():
            from metor.core.key import KeyManager

            key_manager = KeyManager(pm, master_password)
            encryption_key = key_manager.get_database_key()
        sql = SqlManager(db_path, pm.config, encryption_key)
        sql.clear_all_profile_data()
        SqlManager.close_connection(db_path)
        return ProfileOperationResult(
            True,
            ProfileOperationType.DATABASE_CLEARED,
            {'profile': safe_name},
        )
    except Exception:
        SqlManager.close_connection(db_path)
        return ProfileOperationResult(
            False,
            ProfileOperationType.DATABASE_CLEAR_FAILED,
            {},
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
