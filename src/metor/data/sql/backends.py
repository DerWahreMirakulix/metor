"""SQLCipher backend protocols and backend-loader helpers."""

import importlib
from typing import Callable, List, Protocol, Tuple, Union, cast


SqlParam = Union[str, int, float, bytes, None]


class SqlCipherCursor(Protocol):
    """Protocol describing the cursor features used by the SQL manager."""

    def execute(
        self,
        query: str,
        params: Tuple[SqlParam, ...] = (),
    ) -> 'SqlCipherCursor':
        """Executes one SQL statement and returns the active cursor."""

    def fetchone(self) -> object:
        """Returns the next row from the current result set."""

    def fetchall(self) -> list[tuple[object, ...]]:
        """Returns all rows from the current result set."""


class SqlCipherConnection(Protocol):
    """Protocol describing the connection features used by the SQL manager."""

    def __enter__(self) -> 'SqlCipherConnection':
        """Enters the transactional context manager."""

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> object:
        """Exits the transactional context manager."""

    def cursor(self) -> SqlCipherCursor:
        """Creates one database cursor."""

    def execute(
        self,
        query: str,
        params: Tuple[SqlParam, ...] = (),
    ) -> object:
        """Executes one SQL statement directly on the connection."""

    def commit(self) -> None:
        """Commits the current transaction."""

    def close(self) -> None:
        """Closes the database connection."""


class SqlCipherDbApi(Protocol):
    """Protocol describing the DB-API module surface Metor requires."""

    Connection: type[SqlCipherConnection]
    Cursor: type[SqlCipherCursor]
    DatabaseError: type[Exception]
    OperationalError: type[Exception]

    def connect(
        self,
        database: str,
        check_same_thread: bool = False,
    ) -> SqlCipherConnection:
        """Opens one SQLCipher connection."""


def _import_sqlcipher_module(module_name: str) -> SqlCipherDbApi:
    """
    Imports one SQLCipher DB-API module and narrows it to the required protocol.

    Args:
        module_name (str): The fully qualified module name.

    Returns:
        SqlCipherDbApi: The imported module narrowed to the required DB-API surface.
    """
    return cast(SqlCipherDbApi, importlib.import_module(module_name))


def _load_sqlcipher_dbapi(
    import_module: Callable[[str], SqlCipherDbApi] = _import_sqlcipher_module,
) -> Tuple[SqlCipherDbApi, str]:
    """
    Resolves the first available SQLCipher DB-API module.

    Args:
        import_module (Callable[[str], SqlCipherDbApi]): Import function used for backend lookup.

    Raises:
        ImportError: If no supported SQLCipher backend can be imported.

    Returns:
        Tuple[SqlCipherDbApi, str]: The imported DB-API module and the backend package name.
    """
    candidates: Tuple[Tuple[str, str], ...] = (
        ('sqlcipher3', 'sqlcipher3.dbapi2'),
        ('pysqlcipher3', 'pysqlcipher3.dbapi2'),
    )
    errors: List[str] = []

    for backend_name, module_name in candidates:
        try:
            return import_module(module_name), backend_name
        except ImportError as exc:
            errors.append(f'{backend_name}: {exc}')

    joined_errors: str = '; '.join(errors)
    raise ImportError(
        'No supported SQLCipher backend is installed. '
        'Install sqlcipher3-binary on Linux, sqlcipher3 on Windows, '
        'or pysqlcipher3 when managing SQLCipher manually. '
        f'Import attempts: {joined_errors}'
    )


sqlite3: SqlCipherDbApi
sqlite3, SQLCIPHER_BACKEND = _load_sqlcipher_dbapi()
