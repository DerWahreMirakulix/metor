"""Central schema bootstrap helpers for the SQL persistence package."""

from metor.data.sql.backends import SqlCipherConnection, SqlCipherCursor
from metor.versioning import DB_SCHEMA_VERSION


PEER_TABLE_QUERY: str = """
CREATE TABLE IF NOT EXISTS peers (
    onion TEXT PRIMARY KEY NOT NULL CHECK (onion <> ''),
    alias TEXT UNIQUE NOT NULL CHECK (alias <> ''),
    alias_state TEXT NOT NULL CHECK (alias_state IN ('saved', 'discovered')),
    created_at TEXT NOT NULL CHECK (created_at <> ''),
    updated_at TEXT NOT NULL CHECK (updated_at <> '')
)
"""

HISTORY_TABLE_QUERY: str = """
CREATE TABLE IF NOT EXISTS history_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL CHECK (timestamp <> ''),
    family TEXT NOT NULL CHECK (family <> ''),
    event_code TEXT NOT NULL CHECK (event_code <> ''),
    peer_onion TEXT CHECK (peer_onion IS NULL OR peer_onion <> '') REFERENCES peers(onion) ON DELETE RESTRICT,
    actor TEXT NOT NULL CHECK (actor <> ''),
    trigger TEXT,
    detail_code TEXT,
    detail_text TEXT NOT NULL DEFAULT '',
    flow_id TEXT NOT NULL CHECK (flow_id <> ''),
    transport TEXT
)
"""

MESSAGE_RECEIPTS_TABLE_QUERY: str = """
CREATE TABLE IF NOT EXISTS message_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id TEXT NOT NULL CHECK (msg_id <> ''),
    peer_onion TEXT NOT NULL CHECK (peer_onion <> '') REFERENCES peers(onion) ON DELETE RESTRICT,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    delivery TEXT NOT NULL CHECK (delivery IN ('live', 'drop')),
    content_type TEXT NOT NULL CHECK (content_type IN ('text')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'unread', 'read')),
    visible_in_history INTEGER NOT NULL DEFAULT 0 CHECK (visible_in_history IN (0, 1)),
    created_at TEXT NOT NULL CHECK (created_at <> ''),
    updated_at TEXT NOT NULL CHECK (updated_at <> '')
)
"""

INBOUND_SPOOL_TABLE_QUERY: str = """
CREATE TABLE IF NOT EXISTS inbound_spool (
    receipt_id INTEGER PRIMARY KEY REFERENCES message_receipts(id) ON DELETE CASCADE,
    payload TEXT NOT NULL
)
"""

OUTBOX_SPOOL_TABLE_QUERY: str = """
CREATE TABLE IF NOT EXISTS outbox_spool (
    receipt_id INTEGER PRIMARY KEY REFERENCES message_receipts(id) ON DELETE CASCADE,
    payload TEXT NOT NULL
)
"""

MESSAGE_ARCHIVE_TABLE_QUERY: str = """
CREATE TABLE IF NOT EXISTS message_archive (
    receipt_id INTEGER PRIMARY KEY REFERENCES message_receipts(id) ON DELETE CASCADE,
    payload TEXT NOT NULL
)
"""

INDEX_QUERIES: tuple[str, ...] = (
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_message_receipts_identity ON message_receipts (peer_onion, msg_id, direction)',
    'CREATE INDEX IF NOT EXISTS idx_message_receipts_unread ON message_receipts (peer_onion, direction, status)',
    'CREATE INDEX IF NOT EXISTS idx_message_receipts_outbox ON message_receipts (direction, status, created_at)',
    'CREATE INDEX IF NOT EXISTS idx_history_ledger_peer ON history_ledger (peer_onion, timestamp)',
    'CREATE INDEX IF NOT EXISTS idx_history_ledger_flow ON history_ledger (flow_id)',
)


def create_core_schema(cursor: SqlCipherCursor) -> None:
    """
    Creates the central persistence schema on the active cursor.

    Args:
        cursor (SqlCipherCursor): The active schema-bootstrap cursor.

    Returns:
        None
    """
    cursor.execute(PEER_TABLE_QUERY)
    cursor.execute(HISTORY_TABLE_QUERY)
    cursor.execute(MESSAGE_RECEIPTS_TABLE_QUERY)
    cursor.execute(INBOUND_SPOOL_TABLE_QUERY)
    cursor.execute(OUTBOX_SPOOL_TABLE_QUERY)
    cursor.execute(MESSAGE_ARCHIVE_TABLE_QUERY)
    for index_query in INDEX_QUERIES:
        cursor.execute(index_query)


def initialize_schema(cursor: SqlCipherCursor) -> None:
    """Creates a new schema and stamps it only after all DDL succeeds.

    Args:
        cursor (SqlCipherCursor): Cursor for a new, empty database transaction.

    Returns:
        None
    """
    create_core_schema(cursor)
    cursor.execute(f'PRAGMA user_version = {DB_SCHEMA_VERSION}')


def initialize_database(connection: SqlCipherConnection) -> None:
    """Creates and versions an empty database in one explicit transaction.

    Args:
        connection (SqlCipherConnection): Keyed connection to an empty database.

    Returns:
        None
    """
    cursor = connection.cursor()
    try:
        cursor.execute('BEGIN IMMEDIATE')
        initialize_schema(cursor)
        connection.commit()
    except Exception:
        try:
            cursor.execute('ROLLBACK')
        except Exception:
            pass
        raise


def read_schema_version(cursor: SqlCipherCursor) -> int:
    """Reads the durable SQLite schema generation.

    Args:
        cursor (SqlCipherCursor): Cursor on an already keyed database.

    Returns:
        int: Current ``PRAGMA user_version`` value.
    """
    cursor.execute('PRAGMA user_version')
    row: object = cursor.fetchone()
    if not isinstance(row, tuple) or not row or type(row[0]) is not int:
        raise ValueError('Database schema version could not be read.')
    return row[0]


def has_user_schema(cursor: SqlCipherCursor) -> bool:
    """Reports whether an unversioned database already contains application tables.

    Args:
        cursor (SqlCipherCursor): Cursor on an already keyed database.

    Returns:
        bool: True when a non-internal table already exists.
    """
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' LIMIT 1"
    )
    return cursor.fetchone() is not None
