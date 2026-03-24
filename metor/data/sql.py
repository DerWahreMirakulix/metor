"""
Module for managing SQLite database connections and dynamic table setups.
Ensures single-source-of-truth normalization for contacts and logs.
Utilizes SQLCipher for secure Data-At-Rest encryption.
"""

from sqlcipher3 import dbapi2 as sqlite3
from typing import Any, List, Tuple, Optional
from pathlib import Path


class SqlManager:
    """Manages SQLite database connections and executes queries securely."""

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
        Establishes and returns a connection to the SQLite database.
        Applies SQLCipher encryption pragmas if a password is provided.

        Args:
            None

        Returns:
            sqlite3.Connection: The active database connection.
        """
        # Ensure parent directories exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))

        if self._password:
            # Fix SQL Injection Vector: Escape single quotes in password for PRAGMA
            escaped_password: str = self._password.replace("'", "''")
            conn.execute(f"PRAGMA key = '{escaped_password}';")

        return conn

    def _ensure_tables(self) -> None:
        """
        Creates necessary tables if they do not exist yet.

        Args:
            None

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

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(contacts_query)
            cursor.execute(history_query)
            conn.commit()

    def execute(self, query: str, params: Tuple[Any, ...] = ()) -> None:
        """
        Executes a database query that does not return rows (INSERT, UPDATE, DELETE).

        Args:
            query (str): The SQL query string.
            params (Tuple[Any, ...]): Parameters to inject into the SQL query safely.

        Returns:
            None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()

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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
