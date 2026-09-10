"""Generation of the deterministic Metor release compatibility manifest."""

import json
from pathlib import Path
from typing import Any, cast

from metor.core.daemon.managed.models import TorCommand
from metor.core.profile_keys import (
    BLOB_KEY_CONTEXT,
    DB_KEY_CONTEXT,
    KEYSLOT_FORMAT,
    KEYSLOT_KDF,
    KEYSLOT_WRAP,
    SECRET_KEY_CONTEXT,
)
from metor.data.blob.store import (
    BLOB_AUTH_BYTES,
    BLOB_FORMAT_MAGIC,
    BLOB_NONCE_BYTES,
    PER_BLOB_CONTEXT,
)
from metor.data.sql.backends import SqlCipherConnection, sqlite3
from metor.data.sql.schema import initialize_database
from metor.versioning import (
    APP_VERSION,
    BLOB_FORMAT_MIN_SUPPORTED,
    BLOB_FORMAT_VERSION,
    BLOB_OBJECT_DERIVATION_VERSION,
    DB_SCHEMA_MIN_SUPPORTED,
    DB_SCHEMA_VERSION,
    IPC_PROTOCOL_MIN_SUPPORTED,
    IPC_PROTOCOL_VERSION,
    KEYSLOT_FORMAT_MIN_SUPPORTED,
    KEYSLOT_FORMAT_VERSION,
    PEER_PROTOCOL_MIN_SUPPORTED,
    PEER_PROTOCOL_VERSION,
    PROFILE_KEY_DERIVATION_VERSION,
)


JsonObject = dict[str, Any]


def _quote_identifier(identifier: str) -> str:
    """Quotes a database-owned SQLite identifier for introspection.

    Args:
        identifier (str): Identifier read from ``sqlite_master``.

    Returns:
        str: Safely double-quoted identifier.
    """
    return '"' + identifier.replace('"', '""') + '"'


def _normalized_database_schema() -> JsonObject:
    """Builds a deterministic structural description of the current SQL schema.

    Args:
        None

    Returns:
        JsonObject: Sorted tables, columns, constraints, indexes, and foreign keys.
    """
    connection: SqlCipherConnection = sqlite3.connect(':memory:')
    try:
        initialize_database(connection)
        cursor = connection.cursor()
        cursor.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables: list[JsonObject] = []
        for raw_name, raw_sql in cursor.fetchall():
            name: str = cast(str, raw_name)
            quoted: str = _quote_identifier(name)
            cursor.execute(f'PRAGMA table_xinfo({quoted})')
            columns: list[list[object]] = [list(row) for row in cursor.fetchall()]
            cursor.execute(f'PRAGMA foreign_key_list({quoted})')
            foreign_keys: list[list[object]] = [list(row) for row in cursor.fetchall()]
            cursor.execute(f'PRAGMA index_list({quoted})')
            index_rows: list[tuple[object, ...]] = cursor.fetchall()
            indexes: list[JsonObject] = []
            for index_row in sorted(index_rows, key=lambda row: str(row[1])):
                index_name: str = cast(str, index_row[1])
                cursor.execute(f'PRAGMA index_xinfo({_quote_identifier(index_name)})')
                indexes.append(
                    {
                        'name': index_name,
                        'unique': index_row[2],
                        'origin': index_row[3],
                        'partial': index_row[4],
                        'columns': [list(row) for row in cursor.fetchall()],
                    }
                )
            tables.append(
                {
                    'name': name,
                    'sql': raw_sql,
                    'columns': columns,
                    'foreign_keys': foreign_keys,
                    'indexes': indexes,
                }
            )
        return {'tables': tables}
    finally:
        connection.close()


def build_compatibility_manifest(ipc_schema_path: Path) -> JsonObject:
    """Builds the complete compatibility state from authoritative code.

    Args:
        ipc_schema_path (Path): Current generated IPC JSON Schema.

    Returns:
        JsonObject: Release compatibility manifest.
    """
    ipc_schema: JsonObject = json.loads(ipc_schema_path.read_text(encoding='utf-8'))
    return {
        'manifest_version': 1,
        'application_version': APP_VERSION,
        'ipc': {
            'current': IPC_PROTOCOL_VERSION,
            'minimum_supported': IPC_PROTOCOL_MIN_SUPPORTED,
            'schema': ipc_schema,
        },
        'peer': {
            'current': PEER_PROTOCOL_VERSION,
            'minimum_supported': PEER_PROTOCOL_MIN_SUPPORTED,
            'contract': {
                'framing': 'newline-delimited UTF-8 command frames',
                'challenge': (
                    f'{TorCommand.CHALLENGE.value} <hex-nonce> '
                    '<current-generation> <minimum-supported-generation>'
                ),
                'auth': (
                    f'{TorCommand.AUTH.value} <onion> <signature> '
                    '<current-generation> <minimum-supported-generation> [mode]'
                ),
                'negotiation': 'highest generation in the inclusive range overlap',
                'commands': sorted(command.value for command in TorCommand),
            },
        },
        'database': {
            'current': DB_SCHEMA_VERSION,
            'minimum_supported': DB_SCHEMA_MIN_SUPPORTED,
            'schema': _normalized_database_schema(),
        },
        'keyslot': {
            'current': KEYSLOT_FORMAT_VERSION,
            'minimum_supported': KEYSLOT_FORMAT_MIN_SUPPORTED,
            'contract': {
                'format': KEYSLOT_FORMAT,
                'top_level_fields': ['format', 'kdf', 'version', 'wrap'],
                'kdf_fields': ['algorithm', 'memlimit', 'opslimit', 'salt'],
                'wrap_fields': ['algorithm', 'ciphertext', 'nonce'],
                'kdf_algorithm': KEYSLOT_KDF,
                'wrap_algorithm': KEYSLOT_WRAP,
            },
        },
        'blob': {
            'current': BLOB_FORMAT_VERSION,
            'minimum_supported': BLOB_FORMAT_MIN_SUPPORTED,
            'contract': {
                'magic_hex': BLOB_FORMAT_MAGIC.hex(),
                'version_bytes': 1,
                'nonce_bytes': BLOB_NONCE_BYTES,
                'authentication_bytes': BLOB_AUTH_BYTES,
                'framing': 'magic || version || nonce || ciphertext-and-tag',
            },
        },
        'derivation': {
            'profile_key': {
                'current': PROFILE_KEY_DERIVATION_VERSION,
                'contexts_hex': {
                    'database': DB_KEY_CONTEXT.hex(),
                    'identity_secret': SECRET_KEY_CONTEXT.hex(),
                    'blob_root': BLOB_KEY_CONTEXT.hex(),
                },
            },
            'blob_object': {
                'current': BLOB_OBJECT_DERIVATION_VERSION,
                'context_prefix_hex': PER_BLOB_CONTEXT.hex(),
            },
        },
    }


def write_compatibility_manifest(ipc_schema_path: Path, output_path: Path) -> None:
    """Writes the generated compatibility manifest deterministically.

    Args:
        ipc_schema_path (Path): Current generated IPC JSON Schema.
        output_path (Path): Manifest destination.

    Returns:
        None
    """
    document: JsonObject = build_compatibility_manifest(ipc_schema_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8'
    )
