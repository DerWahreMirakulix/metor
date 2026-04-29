"""Runtime-mirror and SQLCipher stderr capture helpers for the SQL package."""

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator, Optional

from metor.utils import Constants, secure_shred_file
from metor.data.settings import SettingKey

# Local Package Imports
from metor.data.sql.backends import SqlCipherConnection, SqlCipherCursor

if TYPE_CHECKING:
    from metor.data.profile import Config


@contextmanager
def capture_sqlcipher_stderr(
    config: 'Config',
    log_callback: Optional[Callable[[str], None]] = None,
) -> Iterator[None]:
    """
    Temporarily redirects OS-level stderr to capture SQLCipher C-library messages.

    Args:
        config (Config): The profile configuration instance.
        log_callback (Optional[Callable[[str], None]]): Optional log sink.

    Yields:
        None
    """
    try:
        fd: int = sys.stderr.fileno()
        old_fd: int = os.dup(fd)
    except Exception:
        yield
        return

    temp_file = tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='ignore')
    try:
        os.dup2(temp_file.fileno(), fd)
        try:
            yield
        finally:
            os.dup2(old_fd, fd)

            if config.get_bool(SettingKey.ENABLE_SQL_LOGGING) and log_callback:
                temp_file.seek(0)
                for line in temp_file:
                    clean_line: str = line.strip()
                    if clean_line:
                        log_callback(clean_line)
    finally:
        temp_file.close()
        try:
            os.close(old_fd)
        except OSError:
            pass


def get_runtime_db_path(db_path: Path) -> Path:
    """
    Resolves the plaintext runtime mirror path for one profile database.

    Args:
        db_path (Path): The encrypted profile database path.

    Returns:
        Path: The runtime mirror database path.
    """
    return db_path.parent / Constants.DB_RUNTIME_FILE


def cleanup_runtime_mirror_file(runtime_db_path: Path) -> None:
    """
    Removes the plaintext runtime mirror file if one exists.

    Args:
        runtime_db_path (Path): The runtime mirror database path.

    Returns:
        None
    """
    if runtime_db_path.exists():
        secure_shred_file(runtime_db_path)


def _detach_runtime_mirror(cursor: SqlCipherCursor) -> None:
    """
    Detaches the runtime alias from the active SQLCipher connection when present.

    Args:
        cursor (SqlCipherCursor): The active cursor bound to the encrypted connection.

    Returns:
        None
    """
    try:
        rows = cursor.execute('PRAGMA database_list').fetchall()
        for row in rows:
            if len(row) >= 2 and str(row[1]) == 'runtime':
                cursor.execute('DETACH DATABASE runtime')
                break
    except Exception:
        pass


def refresh_runtime_mirror(
    conn: SqlCipherConnection,
    db_path: Path,
    uses_sqlcipher_password: bool,
    config: 'Config',
) -> None:
    """
    Exports the encrypted database into a plaintext runtime mirror when enabled.

    Args:
        conn (SqlCipherConnection): The active encrypted database connection.
        db_path (Path): The encrypted profile database path.
        uses_sqlcipher_password (bool): Whether the database is encrypted.
        config (Config): The profile configuration instance.

    Returns:
        None
    """
    runtime_db_path: Path = get_runtime_db_path(db_path)
    if not uses_sqlcipher_password:
        cleanup_runtime_mirror_file(runtime_db_path)
        return

    if not config.get_bool(SettingKey.ENABLE_RUNTIME_DB_MIRROR):
        cleanup_runtime_mirror_file(runtime_db_path)
        return

    runtime_db_path.parent.mkdir(parents=True, exist_ok=True)
    safe_runtime_path: str = str(runtime_db_path.absolute()).replace("'", "''")

    cursor = conn.cursor()
    _detach_runtime_mirror(cursor)
    if runtime_db_path.exists():
        secure_shred_file(runtime_db_path)

    cursor.execute(f"ATTACH DATABASE '{safe_runtime_path}' AS runtime KEY ''")
    try:
        cursor.execute("SELECT sqlcipher_export('runtime')")
    finally:
        _detach_runtime_mirror(cursor)
