"""Blob transformation and database-reference validation for profile migrations."""

from pathlib import Path
from typing import Optional, cast

from metor.data import SqlManager
from metor.data.blob import (
    BlobStore,
    EncryptedBlobStore,
    InvalidBlobIdError,
    PlaintextBlobStore,
)
from metor.utils import secure_remove_path

# Local Package Imports
from metor.data.profile.migration.journal import MigrationCheckpoint
from metor.data.profile.models import ProfileSecurityMode

_BLOB_FILE_SUFFIX = '.blob'


def open_blob_store(
    profile_manager: object,
    mode: ProfileSecurityMode,
    blob_key: Optional[bytes],
) -> BlobStore:
    """Creates the mode-appropriate logical blob store for one profile generation.

    Args:
        profile_manager (object): Profile manager exposing storage paths.
        mode (ProfileSecurityMode): Profile storage security mode.
        blob_key (Optional[bytes]): PMK-derived key for encrypted storage.

    Returns:
        BlobStore: Mode-appropriate external-object store.
    """
    from metor.data.profile.manager import ProfileManager

    typed_manager = cast(ProfileManager, profile_manager)
    if mode is ProfileSecurityMode.ENCRYPTED:
        if blob_key is None:
            raise ValueError('Encrypted blob migration requires a blob key.')
        return EncryptedBlobStore(
            typed_manager.paths.get_persistent_blob_dir(),
            typed_manager.paths.get_temporary_blob_dir(),
            blob_key,
        )
    return PlaintextBlobStore(
        typed_manager.paths.get_persistent_blob_dir(),
        typed_manager.paths.get_temporary_blob_dir(),
    )


def _persistent_blob_ids(persistent_dir: Path) -> list[str]:
    """Enumerates every canonical persistent blob without following directories.

    Args:
        persistent_dir (Path): Source persistent-object directory.

    Returns:
        list[str]: Sorted canonical logical blob identifiers.
    """
    if not persistent_dir.exists():
        return []
    blob_ids: list[str] = []
    for path in persistent_dir.iterdir():
        if not path.is_file() or path.is_symlink() or path.suffix != _BLOB_FILE_SUFFIX:
            raise InvalidBlobIdError(
                'Persistent blob storage contains an invalid entry.'
            )
        blob_id = path.stem
        if path.name != f'{blob_id}{_BLOB_FILE_SUFFIX}':
            raise InvalidBlobIdError('Persistent blob filename is invalid.')
        EncryptedBlobStore._validate_blob_id(blob_id)
        blob_ids.append(blob_id)
    if len(blob_ids) != len(set(blob_ids)):
        raise InvalidBlobIdError('Persistent blob IDs conflict.')
    return sorted(blob_ids)


def migrate_persistent_blobs(
    source_pm: object,
    staged_pm: object,
    source_mode: ProfileSecurityMode,
    target_mode: ProfileSecurityMode,
    source_blob_key: Optional[bytes],
    target_blob_key: Optional[bytes],
    checkpoint: MigrationCheckpoint,
) -> list[str]:
    """Transforms persistent blobs while explicitly closing both logical stores.

    Temporary blobs are non-durable runtime spool state and are intentionally
    discarded while the profile is offline.

    Args:
        source_pm (object): Active source profile manager.
        staged_pm (object): Prepared target profile manager.
        source_mode (ProfileSecurityMode): Active source storage mode.
        target_mode (ProfileSecurityMode): Prepared target storage mode.
        source_blob_key (Optional[bytes): Source PMK-derived blob key.
        target_blob_key (Optional[bytes): Target PMK-derived blob key.
        checkpoint (MigrationCheckpoint): Internal deterministic fault-test hook.

    Returns:
        list[str]: Migrated logical blob identifiers.
    """
    from metor.data.profile.manager import ProfileManager

    typed_source = cast(ProfileManager, source_pm)
    typed_target = cast(ProfileManager, staged_pm)
    blob_ids = _persistent_blob_ids(typed_source.paths.get_persistent_blob_dir())
    secure_remove_path(typed_target.paths.get_persistent_blob_dir())
    secure_remove_path(typed_target.paths.get_temporary_blob_dir())
    source_store = open_blob_store(typed_source, source_mode, source_blob_key)
    target_store = open_blob_store(typed_target, target_mode, target_blob_key)
    try:
        for index, blob_id in enumerate(blob_ids):
            checkpoint(f'before_blob_read:{index}')
            plaintext = source_store.read(blob_id)
            checkpoint(f'before_blob_write:{index}')
            target_store.put_with_id(blob_id, plaintext)
            checkpoint(f'after_blob_write:{index}')
            if target_store.read(blob_id) != plaintext:
                raise ValueError('Migrated blob validation failed.')
            checkpoint(f'after_blob_validation:{index}')
        if (
            _persistent_blob_ids(typed_target.paths.get_persistent_blob_dir())
            != blob_ids
        ):
            raise ValueError('Migrated persistent blob set is incomplete.')
        checkpoint('after_all_blob_writes')
        return blob_ids
    finally:
        source_store.close()
        target_store.close()


def _quote_sql_identifier(identifier: str) -> str:
    """Quotes one database-owned SQLite identifier safely.

    Args:
        identifier (str): Identifier loaded from SQLite schema metadata.

    Returns:
        str: Double-quoted SQLite identifier.
    """
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def validate_database_blob_references(
    sql_manager: SqlManager,
    persistent_blob_ids: list[str],
) -> None:
    """Rejects invalid or missing persistent blob references in the target DB.

    Args:
        sql_manager (SqlManager): Open staged target database.
        persistent_blob_ids (list[str]): Complete migrated persistent blob set.

    Returns:
        None
    """
    available_ids = set(persistent_blob_ids)
    tables = sql_manager.fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    for (table_name,) in tables:
        if not isinstance(table_name, str):
            raise ValueError('Target database contains an invalid table name.')
        quoted_table = _quote_sql_identifier(table_name)
        columns = sql_manager.fetchall(f'PRAGMA table_info({quoted_table})')
        if not any(len(column) > 1 and column[1] == 'blob_id' for column in columns):
            continue
        references = sql_manager.fetchall(
            f'SELECT {_quote_sql_identifier("blob_id")} FROM {quoted_table}'
        )
        for (blob_id,) in references:
            if blob_id is None:
                continue
            if not isinstance(blob_id, str):
                raise InvalidBlobIdError('Database blob reference is invalid.')
            EncryptedBlobStore._validate_blob_id(blob_id)
            if blob_id not in available_ids:
                raise ValueError('Target database references a missing blob.')
