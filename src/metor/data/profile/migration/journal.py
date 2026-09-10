"""Durable journal, recovery, and filesystem synchronization for profile migration."""

import json
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import cast

from metor.data import SqlManager
from metor.utils import Constants, secure_remove_path

# Local Package Imports
from metor.data.profile.support import normalize_profile_name

MIGRATION_PREPARED = 'prepared'
MIGRATION_COMMITTED = 'committed'
_MIGRATION_JOURNAL_VERSION = 1
MigrationCheckpoint = Callable[[str], None]


def _migration_checkpoint(_stage: str) -> None:
    """Provides the default no-op hook for direct recovery calls.

    Args:
        _stage (str): Named migration transition.

    Returns:
        None
    """


def migration_paths(profile_name: str) -> tuple[Path, Path, Path]:
    """Returns durable sibling paths for one validated profile migration.

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


def fsync_directory(directory: Path) -> None:
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


def fsync_tree(path: Path) -> None:
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
            fsync_tree(child)
        fsync_directory(path)


def write_migration_journal(journal_path: Path, profile_name: str, state: str) -> None:
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
        fsync_directory(journal_path.parent)
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
        or typed_document['state'] not in (MIGRATION_PREPARED, MIGRATION_COMMITTED)
    ):
        raise ValueError('Profile security migration journal is unsupported.')
    return cast(str, typed_document['state'])


def close_generation_database(generation_path: Path) -> None:
    """Closes the pooled database handle owned by one profile generation.

    Args:
        generation_path (Path): Source, staged, or backup profile directory.

    Returns:
        None
    """
    SqlManager.close_connection(generation_path / Constants.DB_FILE)


def recover_profile_security_migration(profile_name: str) -> None:
    """Recovers an interrupted migration through the public subsystem boundary.

    Args:
        profile_name (str): Local profile name whose sibling journal is checked.

    Returns:
        None
    """
    recover_staged_profile_migration(profile_name, _migration_checkpoint)


def recover_staged_profile_migration(
    profile_name: str,
    checkpoint: MigrationCheckpoint,
) -> None:
    """Recovers a staged profile migration according to its journal state.

    Args:
        profile_name (str): Local profile name whose sibling journal is checked.
        checkpoint (MigrationCheckpoint): Internal fault-test hook when recovery
            is orchestrated as part of a migration.

    Raises:
        ValueError: If committed migration state cannot be completed safely.

    Returns:
        None
    """
    safe_name = normalize_profile_name(profile_name)
    if not safe_name:
        return
    journal_path, staged_path, backup_path = migration_paths(safe_name)
    if not journal_path.exists():
        return
    state = _read_migration_journal(journal_path, safe_name)
    source_path = Constants.DATA / safe_name

    if state == MIGRATION_PREPARED:
        close_generation_database(staged_path)
        close_generation_database(backup_path)
        secure_remove_path(staged_path)
        secure_remove_path(backup_path)
        journal_path.unlink(missing_ok=True)
        fsync_directory(journal_path.parent)
        return

    if not source_path.exists():
        if not staged_path.exists():
            raise ValueError('Committed profile migration is missing its target.')
        close_generation_database(staged_path)
        staged_path.replace(source_path)
        fsync_directory(source_path.parent)
    elif staged_path.exists():
        if backup_path.exists():
            raise ValueError('Committed profile migration has conflicting generations.')
        close_generation_database(source_path)
        close_generation_database(staged_path)
        source_path.replace(backup_path)
        fsync_directory(source_path.parent)
        staged_path.replace(source_path)
        fsync_directory(source_path.parent)

    try:
        checkpoint('during_old_state_cleanup')
        close_generation_database(backup_path)
        secure_remove_path(backup_path)
    except OSError:
        return
    journal_path.unlink(missing_ok=True)
    fsync_directory(journal_path.parent)
