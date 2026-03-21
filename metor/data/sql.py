"""
Module for managing SQLite database connections and dynamic table setups.
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
        query = """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL,
            alias TEXT,
            onion TEXT,
            reason TEXT
        );
        """
        self.execute(query)

    def execute(self, query: str, params: Tuple = ()) -> None:
        """
        Executes a database query that does not return rows (INSERT, UPDATE, DELETE).

        Args:
            query (str): The SQL query string.
            params (Tuple): Parameters to inject into the SQL query safely.
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
