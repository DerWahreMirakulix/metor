"""
Module for managing SQLite database connections and dynamic table setups.
Ensures single-source-of-truth normalization for contacts and logs.
Utilizes SQLCipher for secure Data-At-Rest encryption with a Connection Pool.
"""

import os
import sys
import threading
import tempfile
from contextlib import contextmanager
from sqlcipher3 import dbapi2 as sqlite3  # type: ignore
from typing import (
    List,
    Tuple,
    Optional,
    Iterator,
    Dict,
    Callable,
    Union,
    cast,
    TYPE_CHECKING,
)
from pathlib import Path

from metor.utils import Constants, secure_shred_file

# Local Package Imports
from metor.data.settings import SettingKey

if TYPE_CHECKING:
    from metor.data.profile.config import Config


# Types
SqlParam = Union[str, int, float, bytes, None]


class DatabaseCorruptedError(ValueError):
    """Raised when the profile database cannot be opened safely."""


@contextmanager
def _capture_c_stderr(
    config: 'Config',
    log_callback: Optional[Callable[[str], None]] = None,
) -> Iterator[None]:
    """
    Temporarily redirects OS-level stderr to a temporary file to capture C-library logs.
    Outputs them formatted if SQL logging is enabled. Ensures execution even on exceptions.

    Args:
        config (Config): The profile configuration instance.
        log_callback (Optional[Callable[[str], None]]): UI-injected logging function.

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


class SqlManager:
    """Manages SQLite database connections using a Connection Pool to prevent lock crashes."""

    _connections: Dict[str, sqlite3.Connection] = {}
    _pool_lock: threading.Lock = threading.Lock()
    _db_lock: threading.Lock = threading.Lock()
    _log_callback: Optional[Callable[[str], None]] = None

    @classmethod
    def set_log_callback(cls, callback: Callable[[str], None]) -> None:
        """
        Sets a global callback for SQL logging to keep the Data layer UI-agnostic.

        Args:
            callback (Callable[[str], None]): The logging function.

        Returns:
            None
        """
        cls._log_callback = callback

    @classmethod
    def close_connection(cls, db_path: str | Path) -> None:
        """
        Closes one pooled connection explicitly so offline migration workflows can replace the file.

        Args:
            db_path (str | Path): The database path whose connection should be closed.

        Returns:
            None
        """
        path_str: str = str(Path(db_path).absolute())
        with cls._pool_lock:
            conn: Optional[sqlite3.Connection] = cls._connections.pop(path_str, None)

        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    @classmethod
    def export_database_copy(
        cls,
        source_path: str | Path,
        target_path: str | Path,
        current_password: Optional[str] = None,
        target_password: Optional[str] = None,
    ) -> None:
        """
        Exports one profile database into a new database file with the target encryption mode.

        Args:
            source_path (str | Path): The current database path.
            target_path (str | Path): The destination database path.
            current_password (Optional[str]): The current SQLCipher password, if any.
            target_password (Optional[str]): The target SQLCipher password, if any.

        Raises:
            DatabaseCorruptedError: If the source database cannot be opened or exported safely.

        Returns:
            None
        """
        source_db: Path = Path(source_path)
        target_db: Path = Path(target_path)

        if not source_db.exists():
            return

        cls.close_connection(source_db)
        target_db.parent.mkdir(parents=True, exist_ok=True)
        target_db.unlink(missing_ok=True)

        conn = sqlite3.connect(str(source_db.absolute()), check_same_thread=False)
        try:
            if current_password:
                safe_current_password: str = current_password.replace("'", "''")
                conn.execute(f"PRAGMA key = '{safe_current_password}'")

            cursor = conn.cursor()
            cursor.execute('SELECT count(*) FROM sqlite_master;')
            cursor.fetchone()

            safe_target_path: str = str(target_db.absolute()).replace("'", "''")
            safe_target_password: str = (
                target_password.replace("'", "''") if target_password else ''
            )

            cursor.execute(
                f"ATTACH DATABASE '{safe_target_path}' AS migrated KEY '{safe_target_password}'"
            )
            try:
                cursor.execute("SELECT sqlcipher_export('migrated')")
            finally:
                try:
                    cursor.execute('DETACH DATABASE migrated')
                except Exception:
                    pass

            conn.commit()
        except (sqlite3.DatabaseError, sqlite3.OperationalError, MemoryError) as e:
            target_db.unlink(missing_ok=True)
            error_text: str = str(e).strip() or e.__class__.__name__
            raise DatabaseCorruptedError(
                f'Profile database could not be migrated safely. Details: {error_text}'
            ) from e
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def __init__(
        self, db_path: str | Path, config: 'Config', password: Optional[str] = None
    ) -> None:
        """
        Initializes the database connection and ensures base tables exist.

        Args:
            db_path (str | Path): The absolute path to the SQLite .db file.
            config (Config): The profile configuration instance.
            password (Optional[str]): The master password for SQLCipher encryption.

        Returns:
            None
        """
        self.db_path: Path = Path(db_path)
        self._config: 'Config' = config
        self._password: Optional[str] = password
        self._ensure_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Establishes and returns a persistent connection from the pool.
        Applies SQLCipher encryption pragmas if a password is provided.
        Proactively creates parent directories to prevent missing path crashes.

        Args:
            None

        Returns:
            sqlite3.Connection: The active database connection.
        """
        path_str: str = str(self.db_path.absolute())

        with SqlManager._pool_lock:
            if path_str in SqlManager._connections:
                return SqlManager._connections[path_str]

            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(path_str, check_same_thread=False)
            if self._password:
                safe_password: str = self._password.replace("'", "''")
                # AUDIT EXCEPTION: SQLite PRAGMA statements do not support parameter binding (?).
                # F-Strings are required here. The password is mathematically secured by escaping
                # single quotes above to prevent SQL injection.
                conn.execute(f"PRAGMA key = '{safe_password}'")

            SqlManager._connections[path_str] = conn
            return conn

    def _get_runtime_db_path(self) -> Path:
        """
        Resolves the plaintext runtime mirror path for external inspection tools.

        Args:
            None

        Returns:
            Path: The runtime mirror database path.
        """
        return self.db_path.parent / Constants.DB_RUNTIME_FILE

    def _refresh_runtime_mirror(self, conn: sqlite3.Connection) -> None:
        """
        Exports the encrypted SQLCipher database to a plaintext runtime mirror.

        Args:
            conn (sqlite3.Connection): The active encrypted database connection.

        Returns:
            None
        """
        if not self._password:
            self.cleanup_runtime_mirror()
            return

        if not self._config.get_bool(SettingKey.ENABLE_RUNTIME_DB_MIRROR):
            self.cleanup_runtime_mirror()
            return

        runtime_db_path: Path = self._get_runtime_db_path()
        runtime_db_path.parent.mkdir(parents=True, exist_ok=True)

        safe_runtime_path: str = str(runtime_db_path.absolute()).replace("'", "''")
        cursor = conn.cursor()
        self._detach_runtime_mirror(cursor)

        if runtime_db_path.exists():
            runtime_db_path.unlink()

        cursor.execute(f"ATTACH DATABASE '{safe_runtime_path}' AS runtime KEY ''")
        try:
            cursor.execute("SELECT sqlcipher_export('runtime')")
        finally:
            self._detach_runtime_mirror(cursor)

    def _detach_runtime_mirror(self, cursor: sqlite3.Cursor) -> None:
        """
        Detaches an existing runtime mirror alias from the active SQLCipher connection.

        Args:
            cursor (sqlite3.Cursor): The active cursor bound to the encrypted connection.

        Returns:
            None
        """
        try:
            rows: List[Tuple[object, ...]] = cast(
                List[Tuple[object, ...]],
                cursor.execute('PRAGMA database_list').fetchall(),
            )
            for row in rows:
                if len(row) >= 2 and str(row[1]) == 'runtime':
                    cursor.execute('DETACH DATABASE runtime')
                    break
        except Exception:
            pass

    def _ensure_tables(self) -> None:
        """
        Creates necessary tables if they do not exist yet.
        Tests decryption before creating tables to avoid memory corruption faults.

        Args:
            None

        Raises:
            DatabaseCorruptedError: If the database cannot be opened safely.

        Returns:
            None
        """
        contacts_query: str = """
        CREATE TABLE IF NOT EXISTS contacts (
            onion TEXT PRIMARY KEY NOT NULL CHECK (onion <> ''),
            alias TEXT UNIQUE NOT NULL,
            is_saved BOOLEAN NOT NULL DEFAULT 0 CHECK (is_saved IN (0, 1))
        );
        """

        history_query: str = """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL CHECK (timestamp <> ''),
            family TEXT NOT NULL CHECK (family <> ''),
            event_code TEXT NOT NULL CHECK (event_code <> ''),
            peer_onion TEXT CHECK (peer_onion IS NULL OR peer_onion <> ''),
            actor TEXT NOT NULL CHECK (actor <> ''),
            trigger TEXT,
            detail_code TEXT,
            detail_text TEXT NOT NULL DEFAULT '',
            flow_id TEXT NOT NULL CHECK (flow_id <> '')
        );
        """

        try:
            with _capture_c_stderr(self._config, SqlManager._log_callback):
                conn = self._get_connection()
                with SqlManager._db_lock:
                    with conn:
                        cursor = conn.cursor()
                        cursor.execute('SELECT count(*) FROM sqlite_master;')
                        cursor.fetchone()

                        cursor.execute(contacts_query)
                        cursor.execute(history_query)
                        try:
                            self._refresh_runtime_mirror(conn)
                        except Exception:
                            pass
        except (sqlite3.DatabaseError, sqlite3.OperationalError, MemoryError) as e:
            path_str: str = str(self.db_path.absolute())
            with SqlManager._pool_lock:
                if path_str in SqlManager._connections:
                    SqlManager._connections[path_str].close()
                    del SqlManager._connections[path_str]
            error_text: str = str(e).strip() or e.__class__.__name__
            raise DatabaseCorruptedError(
                f'Profile database could not be opened safely. Details: {error_text}'
            ) from e

    def execute(self, query: str, params: Tuple[SqlParam, ...] = ()) -> None:
        """
        Executes a database query that does not return rows (INSERT, UPDATE, DELETE).

        Args:
            query (str): The SQL query string.
            params (Tuple[SqlParam, ...]): Parameters to inject into the SQL query safely.

        Returns:
            None
        """
        conn = self._get_connection()
        with SqlManager._db_lock:
            with conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                try:
                    self._refresh_runtime_mirror(conn)
                except Exception:
                    pass

    def cleanup_runtime_mirror(self) -> None:
        """
        Removes the plaintext runtime mirror if one exists.

        Args:
            None

        Returns:
            None
        """
        runtime_db_path: Path = self._get_runtime_db_path()
        if runtime_db_path.exists():
            secure_shred_file(runtime_db_path)

    def fetchall(
        self, query: str, params: Tuple[SqlParam, ...] = ()
    ) -> List[Tuple[SqlParam, ...]]:
        """
        Executes a database query and returns all matching rows.

        Args:
            query (str): The SQL SELECT query string.
            params (Tuple[SqlParam, ...]): Parameters to inject into the SQL query safely.

        Returns:
            List[Tuple[SqlParam, ...]]: A list of tuples representing the rows.
        """
        conn = self._get_connection()
        with SqlManager._db_lock:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cast(List[Tuple[SqlParam, ...]], cursor.fetchall())
