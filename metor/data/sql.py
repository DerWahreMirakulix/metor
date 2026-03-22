"""
Module for managing SQLite database connections and dynamic table setups.
Ensures single-source-of-truth normalization for contacts and logs.
"""

import sqlite3
from typing import Any, List, Tuple


class SqlManager:
    """Manages SQLite database connections and executes queries."""

    def __init__(self, db_path: str) -> None:
        """
        Initializes the database connection and ensures base tables exist.

        Args:
            db_path (str): The absolute path to the SQLite .db file.
        """
        self.db_path: str = db_path
        self._ensure_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Establishes and returns a connection to the SQLite database.

        Returns:
            sqlite3.Connection: The active database connection.
        """
        return sqlite3.connect(self.db_path)

    def _ensure_tables(self) -> None:
        """
        Creates necessary tables if they do not exist yet.
        """
        # The contacts table acts as the normalized source of truth for aliases
        contacts_query: str = """
        CREATE TABLE IF NOT EXISTS contacts (
            onion TEXT PRIMARY KEY,
            alias TEXT UNIQUE NOT NULL,
            is_saved BOOLEAN NOT NULL DEFAULT 0
        );
        """

        # History relies on the onion string to JOIN with the contacts table
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
