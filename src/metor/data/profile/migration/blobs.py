"""Blob transformation and database-reference validation for profile migrations."""

from contextlib import closing
import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from metor.data import SqlManager
from metor.data.blob import (
    BlobLifecycle,
    open_blob_store,
    EncryptedBlobStore,
    InvalidBlobIdError,
)
from metor.utils import Constants, secure_remove_path

# Local Package Imports
from metor.data.profile.migration.journal import MigrationCheckpoint

if TYPE_CHECKING:
    from metor.data.profile.manager import ProfileManager

_BLOB_FILE_SUFFIX = '.blob'


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


def required_voice_segments(sql: SqlManager) -> dict[str, int]:
    """Read finalized DROP ownership from the current archive and delivery spools."""
    rows = sql.fetchall(
        'SELECT DISTINCT COALESCE(a.payload, i.payload, o.payload) '
        'FROM message_receipts r '
        'LEFT JOIN message_archive a ON a.receipt_id = r.id '
        'LEFT JOIN inbound_spool i ON i.receipt_id = r.id '
        'LEFT JOIN outbox_spool o ON o.receipt_id = r.id '
        "WHERE r.delivery = 'drop' AND r.content_type = 'voice' "
        "AND r.status <> 'draft' AND COALESCE(a.payload,i.payload,o.payload) IS NOT NULL"
    )
    segments: dict[str, int] = {}
    for (payload,) in rows:
        if (
            not isinstance(payload, str)
            or len(payload.encode('utf-8')) > Constants.VOICE_METADATA_MAX_BYTES
        ):
            raise ValueError('Invalid retained Voice metadata.')
        metadata = json.loads(payload)
        if metadata['finalized'] is False:
            continue
        ids, sizes = metadata['chunk_ids'], metadata['chunk_sizes']
        if (
            metadata['finalized'] is not True
            or not isinstance(ids, list)
            or not isinstance(sizes, list)
            or len(ids) != len(sizes)
            or len(ids) > Constants.VOICE_MAX_SEGMENTS
            or any(
                type(size) is not int or not 0 < size <= Constants.VOICE_CHUNK_MAX_BYTES
                for size in sizes
            )
            or type(metadata['size_bytes']) is not int
            or not 0 <= metadata['size_bytes'] <= Constants.VOICE_TURN_HARD_MAX_BYTES
            or sum(sizes) != metadata['size_bytes']
        ):
            raise ValueError('Invalid finalized Voice manifest.')
        for blob_id, size in zip([metadata['blob_id'], *ids], [0, *sizes], strict=True):
            if not isinstance(blob_id, str):
                raise InvalidBlobIdError('Invalid Voice object identifier.')
            EncryptedBlobStore._validate_blob_id(blob_id)
            if blob_id in segments and segments[blob_id] != size:
                raise ValueError('Conflicting Voice object lengths.')
            segments[blob_id] = size
    return segments


def migrate_persistent_blobs(
    source_pm: 'ProfileManager',
    staged_pm: 'ProfileManager',
    load_source_key: Callable[[], bytes],
    load_target_key: Callable[[], bytes],
    required_segments: dict[str, int],
    checkpoint: MigrationCheckpoint,
) -> list[str]:
    """Transforms persistent blobs while explicitly closing both logical stores.

    Finalized DROP receipts can already own segments in the temporary namespace.
    Other temporary spool objects are discarded while the profile is offline.

    Args:
        source_pm: Active source profile manager.
        staged_pm: Prepared target profile manager.
        load_source_key: Read the source blob key if its store is encrypted.
        load_target_key: Read the target blob key if its store is encrypted.
        required_segments: Sizes of every anchor and segment owned by a finalized DROP.
        checkpoint (MigrationCheckpoint): Internal deterministic fault-test hook.

    Returns:
        list[str]: Migrated logical blob identifiers.
    """
    persistent_ids = set(
        _persistent_blob_ids(source_pm.paths.get_persistent_blob_dir())
    )
    blob_ids = sorted(persistent_ids | required_segments.keys())
    secure_remove_path(staged_pm.paths.get_persistent_blob_dir())
    secure_remove_path(staged_pm.paths.get_temporary_blob_dir())
    with (
        closing(open_blob_store(source_pm, load_source_key)) as source_store,
        closing(open_blob_store(staged_pm, load_target_key)) as target_store,
    ):
        for index, blob_id in enumerate(blob_ids):
            checkpoint(f'before_blob_read:{index}')
            lifecycle = (
                BlobLifecycle.PERSISTENT
                if blob_id in persistent_ids
                else BlobLifecycle.TEMPORARY
            )
            plaintext = source_store.read(blob_id, lifecycle)
            if (
                blob_id in required_segments
                and len(plaintext) != required_segments[blob_id]
            ):
                raise ValueError(
                    'Finalized Voice object length does not match the receipt.'
                )
            checkpoint(f'before_blob_write:{index}')
            target_store.put_with_id(blob_id, plaintext)
            checkpoint(f'after_blob_write:{index}')
            if target_store.read(blob_id) != plaintext:
                raise ValueError('Migrated blob validation failed.')
            checkpoint(f'after_blob_validation:{index}')
        if _persistent_blob_ids(staged_pm.paths.get_persistent_blob_dir()) != blob_ids:
            raise ValueError('Migrated persistent blob set is incomplete.')
        checkpoint('after_all_blob_writes')
        return blob_ids


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
