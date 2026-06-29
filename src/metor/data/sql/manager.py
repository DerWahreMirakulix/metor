"""Central SQL manager owning connection pooling, schema bootstrap, and runtime mirrors."""

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, TYPE_CHECKING, Tuple, cast

from metor.utils import secure_clear_buffer

# Local Package Imports
from metor.data.sql.backends import (
    SqlCipherConnection,
    SqlCipherCursor,
    SqlParam,
    sqlite3,
)
from metor.data.sql.history import HistoryRepository
from metor.data.sql.message import MessageRepository
from metor.data.sql.peer import PeerRepository
from metor.data.sql.runtime_mirror import (
    capture_sqlcipher_stderr,
    cleanup_runtime_mirror_file,
    get_runtime_db_path,
    refresh_runtime_mirror,
)
from metor.data.sql.schema import ensure_core_schema

if TYPE_CHECKING:
    from metor.data.profile import Config


class DatabaseCorruptedError(ValueError):
    """Raised when the profile database cannot be opened safely."""


class SqlManager:
    """Manages one pooled SQLCipher connection and the central persistence schema."""

    _connections: Dict[str, SqlCipherConnection] = {}
    _pool_lock: threading.Lock = threading.Lock()
    _db_lock: threading.Lock = threading.Lock()
    _log_callback: Optional[Callable[[str], None]] = None

    @classmethod
    def _report_runtime_mirror_error(cls, message: str) -> None:
        """
        Emits one best-effort runtime-mirror error log line.

        Args:
            message (str): The log-safe error message.

        Returns:
            None
        """
        if cls._log_callback is None:
            return

        try:
            cls._log_callback(message)
        except Exception:
            pass

    @classmethod
    def set_log_callback(cls, callback: Callable[[str], None]) -> None:
        """
        Sets a global callback for SQL logging to keep the data layer UI-agnostic.

        Args:
            callback (Callable[[str], None]): The logging function.

        Returns:
            None
        """
        cls._log_callback = callback

    @classmethod
    def close_connection(cls, db_path: str | Path) -> None:
        """
        Closes one pooled connection explicitly so offline workflows can replace the file.

        Args:
            db_path (str | Path): The database path whose connection should be closed.

        Returns:
            None
        """
        path_str: str = str(Path(db_path).absolute())
        with cls._pool_lock:
            conn = cls._connections.pop(path_str, None)

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
            cursor.execute('PRAGMA foreign_keys = ON')
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
        except (sqlite3.DatabaseError, sqlite3.OperationalError, MemoryError) as exc:
            target_db.unlink(missing_ok=True)
            error_text: str = str(exc).strip() or exc.__class__.__name__
            raise DatabaseCorruptedError(
                f'Profile database could not be migrated safely. Details: {error_text}'
            ) from exc
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def __init__(
        self,
        db_path: str | Path,
        config: 'Config',
        password: Optional[str] = None,
    ) -> None:
        """
        Initializes the database connection and ensures the central schema exists.

        Args:
            db_path (str | Path): The absolute path to the SQLite database file.
            config (Config): The profile configuration instance.
            password (Optional[str]): The master password for SQLCipher encryption.

        Returns:
            None
        """
        self.db_path: Path = Path(db_path)
        self._config: 'Config' = config
        self._password: Optional[bytearray] = None
        self._uses_sqlcipher_password: bool = password is not None
        if password is not None:
            self._password = bytearray(password.encode('utf-8'))

        self._ensure_tables()
        self.peers: PeerRepository = PeerRepository(self)
        self.messages: MessageRepository = MessageRepository(self)
        self.history: HistoryRepository = HistoryRepository(self)

    def _get_connection(self) -> SqlCipherConnection:
        """
        Establishes and returns one pooled database connection.

        Args:
            None

        Returns:
            SqlCipherConnection: The active connection.
        """
        path_str: str = str(self.db_path.absolute())

        with SqlManager._pool_lock:
            if path_str in SqlManager._connections:
                return SqlManager._connections[path_str]

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path_str, check_same_thread=False)
            conn.execute('PRAGMA foreign_keys = ON')
            if self._password:
                safe_password: str = self._password.decode('utf-8').replace("'", "''")
                conn.execute(f"PRAGMA key = '{safe_password}'")
                secure_clear_buffer(self._password)
                self._password = None

            SqlManager._connections[path_str] = conn
            return conn

    def _ensure_tables(self) -> None:
        """
        Creates the central schema if it does not already exist.

        Args:
            None

        Raises:
            DatabaseCorruptedError: If the database cannot be opened safely.

        Returns:
            None
        """
        try:
            with capture_sqlcipher_stderr(self._config, SqlManager._log_callback):
                conn = self._get_connection()
                with SqlManager._db_lock:
                    with conn:
                        cursor = conn.cursor()
                        cursor.execute('PRAGMA foreign_keys = ON')
                        cursor.execute('SELECT count(*) FROM sqlite_master;')
                        cursor.fetchone()

                        ensure_core_schema(cursor)

                        try:
                            refresh_runtime_mirror(
                                conn,
                                self.db_path,
                                self._uses_sqlcipher_password,
                                self._config,
                            )
                        except Exception:
                            SqlManager._report_runtime_mirror_error(
                                'Failed to refresh the runtime database mirror.'
                            )
        except (sqlite3.DatabaseError, sqlite3.OperationalError, MemoryError) as exc:
            path_str: str = str(self.db_path.absolute())
            with SqlManager._pool_lock:
                if path_str in SqlManager._connections:
                    try:
                        SqlManager._connections[path_str].close()
                    except Exception:
                        pass
                    del SqlManager._connections[path_str]
            error_text: str = str(exc).strip() or exc.__class__.__name__
            raise DatabaseCorruptedError(
                f'Profile database could not be opened safely. Details: {error_text}'
            ) from exc

    @contextmanager
    def transaction(self) -> Iterator[SqlCipherCursor]:
        """
        Opens one atomic transaction and refreshes the runtime mirror after successful writes.

        Args:
            None

        Yields:
            SqlCipherCursor: The active transaction cursor.
        """
        conn = self._get_connection()
        with SqlManager._db_lock:
            with conn:
                cursor = conn.cursor()
                yield cursor
                try:
                    refresh_runtime_mirror(
                        conn,
                        self.db_path,
                        self._uses_sqlcipher_password,
                        self._config,
                    )
                except Exception:
                    SqlManager._report_runtime_mirror_error(
                        'Failed to refresh the runtime database mirror.'
                    )

    def execute(self, query: str, params: Tuple[SqlParam, ...] = ()) -> None:
        """
        Executes one non-select query.

        Args:
            query (str): The SQL query.
            params (Tuple[SqlParam, ...]): Bound parameters.

        Returns:
            None
        """
        with self.transaction() as cursor:
            cursor.execute(query, params)

    def fetchall(
        self,
        query: str,
        params: Tuple[SqlParam, ...] = (),
    ) -> List[Tuple[SqlParam, ...]]:
        """
        Executes one select query and returns all rows.

        Args:
            query (str): The SQL query.
            params (Tuple[SqlParam, ...]): Bound parameters.

        Returns:
            List[Tuple[SqlParam, ...]]: Result rows.
        """
        conn = self._get_connection()
        with SqlManager._db_lock:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cast(List[Tuple[SqlParam, ...]], cursor.fetchall())

    def cleanup_runtime_mirror(self) -> None:
        """
        Removes the plaintext runtime mirror if one exists.

        Args:
            None

        Returns:
            None
        """
        runtime_db_path: Path = get_runtime_db_path(self.db_path)
        try:
            cleanup_runtime_mirror_file(runtime_db_path)
        except OSError:
            SqlManager._report_runtime_mirror_error(
                'Failed to shred the runtime database mirror.'
            )

    def clear_all_profile_data(self) -> None:
        """
        Clears all new-schema profile data in FK-safe order.

        Args:
            None

        Returns:
            None
        """
        with self.transaction() as cursor:
            cursor.execute('DELETE FROM history_ledger')
            cursor.execute('DELETE FROM message_receipts')
            cursor.execute('DELETE FROM peers')
