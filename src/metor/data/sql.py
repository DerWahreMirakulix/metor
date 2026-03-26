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
from sqlcipher3 import dbapi2 as sqlite3
from typing import Any, List, Tuple, Optional, Iterator, Dict
from pathlib import Path

from metor.data.settings import Settings, SettingKey
from metor.ui.theme import Theme


@contextmanager
def _capture_c_stderr() -> Iterator[None]:
    """
    Temporarily redirects OS-level stderr to a temporary file to capture C-library logs.
    Outputs them formatted if SQL logging is enabled. Ensures execution even on exceptions.

    Args:
        None

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

            if Settings.get(SettingKey.ENABLE_SQL_LOGGING):
                temp_file.seek(0)
                for line in temp_file:
                    clean_line: str = line.strip()
                    if clean_line:
                        sys.stdout.write(
                            f'\r\033[K{Theme.CYAN}[SQL-LOG]{Theme.RESET} {clean_line}\n'
                        )
                sys.stdout.flush()
    finally:
        temp_file.close()
        try:
            os.close(old_fd)
        except OSError:
            pass


class SqlManager:
    """Manages SQLite database connections using a Connection Pool to prevent lock crashes."""

    # Class-level dictionary to reuse identical connections across managers
    _connections: Dict[str, sqlite3.Connection] = {}
    _pool_lock: threading.Lock = threading.Lock()

    def __init__(self, db_path: str | Path, password: Optional[str] = None) -> None:
        """
        Initializes the database connection and ensures base tables exist.

        Args:
            db_path (str | Path): The absolute path to the SQLite .db file.
            password (Optional[str]): The master password for SQLCipher encryption.

        Returns:
            None
        """
        self.db_path: Path = Path(db_path)
        self._password: Optional[str] = password
        self._ensure_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Establishes and returns a persistent connection from the pool.
        Applies SQLCipher encryption pragmas if a password is provided.

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
                conn.execute(f"PRAGMA key = '{safe_password}'")

            SqlManager._connections[path_str] = conn
            return conn

    def _ensure_tables(self) -> None:
        """
        Creates necessary tables if they do not exist yet.
        Tests decryption before creating tables to avoid memory corruption faults.

        Args:
            None

        Raises:
            ValueError: If the database is corrupted or the password is wrong.

        Returns:
            None
        """
        contacts_query: str = """
        CREATE TABLE IF NOT EXISTS contacts (
            onion TEXT PRIMARY KEY,
            alias TEXT UNIQUE NOT NULL,
            is_saved BOOLEAN NOT NULL DEFAULT 0
        );
        """

        history_query: str = """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL,
            onion TEXT,
            reason TEXT
        );
        """

        try:
            with _capture_c_stderr():
                conn = self._get_connection()
                with conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT count(*) FROM sqlite_master;')
                    cursor.fetchone()

                    cursor.execute(contacts_query)
                    cursor.execute(history_query)
        except (sqlite3.DatabaseError, sqlite3.OperationalError, MemoryError) as e:
            # Clean up the corrupted connection from the pool to allow fresh retries
            path_str: str = str(self.db_path.absolute())
            with SqlManager._pool_lock:
                if path_str in SqlManager._connections:
                    SqlManager._connections[path_str].close()
                    del SqlManager._connections[path_str]
            raise ValueError(
                f'Invalid master password or corrupted database. Details: {str(e)}'
            ) from e

    def execute(self, query: str, params: Tuple[Any, ...] = ()) -> None:
        """
        Executes a database query that does not return rows (INSERT, UPDATE, DELETE).

        Args:
            query (str): The SQL query string.
            params (Tuple[Any, ...]): Parameters to inject into the SQL query safely.

        Returns:
            None
        """
        conn = self._get_connection()
        with conn:
            cursor = conn.cursor()
            cursor.execute(query, params)

    def fetchall(
        self, query: str, params: Tuple[Any, ...] = ()
    ) -> List[Tuple[Any, ...]]:
        """
        Executes a database query and returns all matching rows.

        Args:
            query (str): The SQL SELECT query string.
            params (Tuple[Any, ...]): Parameters to inject into the SQL query safely.

        Returns:
            List[Tuple[Any, ...]]: A list of tuples representing the rows.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
