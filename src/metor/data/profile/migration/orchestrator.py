"""State-machine orchestration for offline profile storage security migration."""

import shutil
from pathlib import Path
from typing import Optional

from metor.core.daemon import InvalidMasterPasswordError, verify_master_password
from metor.core.key import KeyManager
from metor.data import DatabaseCorruptedError, SettingKey, Settings, SqlManager
from metor.utils import secure_remove_path, secure_shred_file

# Local Package Imports
from metor.data.profile.migration.blobs import (
    migrate_persistent_blobs,
    open_blob_store,
    validate_database_blob_references,
)
from metor.data.profile.migration.journal import (
    MIGRATION_COMMITTED,
    MIGRATION_PREPARED,
    MigrationCheckpoint,
    close_generation_database,
    fsync_tree,
    migration_paths,
    recover_staged_profile_migration,
    write_migration_journal,
)
from metor.data.profile.models import (
    ProfileConfigKey,
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSecurityMode,
)
from metor.data.profile.support import normalize_profile_name


def _migration_checkpoint(_stage: str) -> None:
    """Provides a private no-op boundary for deterministic migration fault tests.

    Args:
        _stage (str): Named migration transition.

    Returns:
        None
    """


def migrate_profile_security(
    name: str,
    target_mode: ProfileSecurityMode,
    current_password: Optional[str],
    new_password: Optional[str],
) -> ProfileOperationResult:
    """Migrates one offline profile through a journaled storage state machine.

    Args:
        name (str): Requested local profile name.
        target_mode (ProfileSecurityMode): Desired storage protection mode.
        current_password (Optional[str]): Current encrypted-source credential.
        new_password (Optional[str]): New encrypted-target credential.
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
            False, ProfileOperationType.PROFILE_NOT_FOUND, {'profile': safe_name}
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
    if target_mode is ProfileSecurityMode.PLAINTEXT and not Settings.get_bool(
        SettingKey.ALLOW_PLAINTEXT_PROFILES
    ):
        return ProfileOperationResult(
            False,
            ProfileOperationType.PLAINTEXT_PROFILES_DISABLED,
            {'profile': safe_name},
        )

    current_mode = pm.get_security_mode()
    if current_mode is target_mode:
        return ProfileOperationResult(
            True,
            ProfileOperationType.SECURITY_MODE_UNCHANGED,
            {'profile': safe_name, 'security_mode': current_mode.value},
        )

    old_password = (
        current_password if current_mode is ProfileSecurityMode.ENCRYPTED else None
    )
    target_password = (
        new_password if target_mode is ProfileSecurityMode.ENCRYPTED else None
    )
    db_path = pm.paths.get_db_file()
    journal_path, staged_path, backup_path = migration_paths(safe_name)
    key_manager = KeyManager(pm, old_password)

    if current_mode is ProfileSecurityMode.ENCRYPTED and (
        key_manager.has_any_key_material() or db_path.exists()
    ):
        if not old_password:
            return _migration_failure(
                safe_name,
                'Current master password is required for encrypted profiles.',
            )
        try:
            verify_master_password(key_manager)
        except InvalidMasterPasswordError:
            return _migration_failure(safe_name, 'Current master password is invalid.')

    if target_mode is ProfileSecurityMode.ENCRYPTED and not target_password:
        return _migration_failure(
            safe_name,
            'A new master password is required when migrating to encrypted storage.',
        )

    try:
        write_migration_journal(journal_path, safe_name, MIGRATION_PREPARED)
        close_generation_database(staged_path)
        close_generation_database(backup_path)
        secure_remove_path(staged_path)
        secure_remove_path(backup_path)
        shutil.copytree(pm.paths.get_config_dir(), staged_path, symlinks=True)

        staged_pm = ProfileManager(staged_path.name)
        staged_db_path = staged_pm.paths.get_db_file()
        _migration_checkpoint('before_target_db_creation')
        secure_shred_file(staged_db_path)
        current_db_key = (
            key_manager.get_database_key()
            if current_mode is ProfileSecurityMode.ENCRYPTED and db_path.exists()
            else None
        )
        staged_key_manager = KeyManager(staged_pm, old_password)
        try:
            _migration_checkpoint('during_secret_transformation')
            target_db_key = _configure_staged_security(
                staged_pm,
                staged_key_manager,
                target_mode,
                target_password,
                _migration_checkpoint,
            )
            source_blob_key = (
                key_manager.get_blob_key()
                if current_mode is ProfileSecurityMode.ENCRYPTED
                else None
            )
            target_blob_key = (
                staged_key_manager.get_blob_key()
                if target_mode is ProfileSecurityMode.ENCRYPTED
                else None
            )
            _migration_checkpoint('before_blob_migration')
            migrated_blob_ids = migrate_persistent_blobs(
                pm,
                staged_pm,
                current_mode,
                target_mode,
                source_blob_key,
                target_blob_key,
                _migration_checkpoint,
            )
            _migration_checkpoint('after_blob_migration')
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
            _validate_staged_generation(
                staged_pm,
                staged_db_path,
                target_mode,
                target_password,
                migrated_blob_ids,
                _migration_checkpoint,
            )
        finally:
            staged_key_manager.clear_sensitive_state()

        fsync_tree(staged_path)
        _migration_checkpoint('immediately_before_commit')
        write_migration_journal(journal_path, safe_name, MIGRATION_COMMITTED)
        _migration_checkpoint('immediately_after_commit')
        recover_staged_profile_migration(safe_name, _migration_checkpoint)
    except DatabaseCorruptedError as exc:
        key_manager.clear_sensitive_state()
        return _migration_failure(safe_name, str(exc))
    except Exception as exc:
        key_manager.clear_sensitive_state()
        return _migration_failure(safe_name, str(exc) or 'Migration failed.')

    key_manager.clear_sensitive_state()
    return ProfileOperationResult(
        True,
        ProfileOperationType.SECURITY_MODE_MIGRATED,
        {'profile': safe_name, 'security_mode': target_mode.value},
    )


def _configure_staged_security(
    staged_pm: object,
    staged_key_manager: KeyManager,
    target_mode: ProfileSecurityMode,
    target_password: Optional[str],
    checkpoint: MigrationCheckpoint,
) -> Optional[bytes]:
    """Sets staged key protection and returns the target database key if needed.

    Args:
        staged_pm (object): Prepared target profile manager.
        staged_key_manager (KeyManager): Staged profile key owner.
        target_mode (ProfileSecurityMode): Requested target storage mode.
        target_password (Optional[str]): New password for encrypted targets.
        checkpoint (MigrationCheckpoint): Internal deterministic fault-test hook.

    Returns:
        Optional[bytes]: Target SQLCipher key, or None for plaintext storage.
    """
    from metor.data.profile.manager import ProfileManager

    if not isinstance(staged_pm, ProfileManager):
        raise TypeError('Staged profile manager is invalid.')
    if target_mode is ProfileSecurityMode.ENCRYPTED:
        staged_key_manager.rewrite_password_protection(target_password or '')
        staged_pm.config.set(
            ProfileConfigKey.SECURITY_MODE,
            target_mode.value,
            allow_mutating_structural_keys=True,
        )
        target_db_key = staged_key_manager.get_database_key()
        checkpoint('after_target_keyslot_creation')
        return target_db_key
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
    return None


def _validate_staged_generation(
    staged_pm: object,
    staged_db_path: Path,
    target_mode: ProfileSecurityMode,
    target_password: Optional[str],
    migrated_blob_ids: list[str],
    checkpoint: MigrationCheckpoint,
) -> None:
    """Verifies staged database, key, blob, and configuration integrity.

    Args:
        staged_pm (object): Prepared target profile manager.
        staged_db_path (Path): Target database path.
        target_mode (ProfileSecurityMode): Requested target storage mode.
        target_password (Optional[str]): Password for encrypted targets.
        migrated_blob_ids (list[str]): Every copied persistent blob identifier.
        checkpoint (MigrationCheckpoint): Internal deterministic fault-test hook.

    Returns:
        None
    """
    from metor.data.profile.manager import ProfileManager

    if not isinstance(staged_pm, ProfileManager):
        raise TypeError('Staged profile manager is invalid.')
    validation_key_manager = KeyManager(staged_pm, target_password)
    try:
        checkpoint('before_validation')
        validated_key = (
            validation_key_manager.get_database_key()
            if target_mode is ProfileSecurityMode.ENCRYPTED
            else None
        )
        checkpoint('during_validation')
        try:
            validation_sql = SqlManager(staged_db_path, staged_pm.config, validated_key)
            validate_database_blob_references(validation_sql, migrated_blob_ids)
        finally:
            SqlManager.close_connection(staged_db_path)
        if validation_key_manager.has_metor_key():
            validation_key_manager.get_metor_key()
        validation_blob_key = (
            validation_key_manager.get_blob_key()
            if target_mode is ProfileSecurityMode.ENCRYPTED
            else None
        )
        validation_blob_store = open_blob_store(
            staged_pm,
            target_mode,
            validation_blob_key,
        )
        try:
            for index, blob_id in enumerate(migrated_blob_ids):
                checkpoint(f'during_blob_validation:{index}')
                validation_blob_store.read(blob_id)
        finally:
            validation_blob_store.close()
        staged_pm.validate_integrity()
    finally:
        validation_key_manager.clear_sensitive_state()


def _migration_failure(profile_name: str, reason: str) -> ProfileOperationResult:
    """Builds the stable failure result for a rejected or failed migration.

    Args:
        profile_name (str): Validated profile name.
        reason (str): Safe failure reason intended for the local caller.

    Returns:
        ProfileOperationResult: Typed migration failure outcome.
    """
    return ProfileOperationResult(
        False,
        ProfileOperationType.SECURITY_MIGRATION_FAILED,
        {'profile': profile_name, 'reason': reason},
    )
