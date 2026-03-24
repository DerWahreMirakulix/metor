"""
Module for managing SQLite database connections and dynamic table setups.
Ensures single-source-of-truth normalization for contacts and logs.
Utilizes SQLCipher for secure Data-At-Rest encryption.
"""

from sqlcipher3 import dbapi2 as sqlite3
from typing import Any, List, Tuple, Optional


class SqlManager:
    """Manages SQLite database connections and executes queries securely."""

    def __init__(self, db_path: str, password: Optional[str] = None) -> None:
        """
        Initializes the database connection and ensures base tables exist.

        Args:
            db_path (str): The absolute path to the SQLite .db file.
            password (Optional[str]): The master password for SQLCipher encryption.
        """
        self.db_path: str = db_path
        self._password: Optional[str] = password
        self._ensure_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Establishes and returns a connection to the SQLite database.
        Applies SQLCipher encryption pragmas if a password is provided.

        Returns:
            sqlite3.Connection: The active database connection.
        """
        conn = sqlite3.connect(self.db_path)
        if self._password:
            conn.execute(f"PRAGMA key = '{self._password}';")
        return conn

    def _ensure_tables(self) -> None:
        """
        Creates necessary tables if they do not exist yet.
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

    def execute(self, query: str, params: Tuple = ()) -> None:
        """
        Executes a database query that does not return rows (INSERT, UPDATE, DELETE).

        Args:
            query (str): The SQL query string.
            params (Tuple): Parameters to inject into the SQL query safely.

        Returns:
            None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()

    def fetchall(self, query: str, params: Tuple = ()) -> List[Tuple[Any, ...]]:
        """
        Executes a database query and returns all matching rows.

        Args:
            query (str): The SQL SELECT query string.
            params (Tuple): Parameters to inject into the SQL query safely.

        Returns:
            List[Tuple[Any, ...]]: A list of tuples representing the rows.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
