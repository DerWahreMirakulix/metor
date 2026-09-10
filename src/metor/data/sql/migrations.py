"""Ordered transactional migration registry for Metor database schemas."""

from dataclasses import dataclass
from typing import Callable

from metor.versioning import DB_SCHEMA_VERSION

# Local Package Imports
from metor.data.sql.backends import SqlCipherConnection, SqlCipherCursor
from metor.data.sql.errors import DatabaseMigrationError


@dataclass(frozen=True)
class SchemaMigration:
    """Defines one adjacent database schema migration.

    Args:
        source_version (int): Schema generation accepted by the migration.
        target_version (int): Adjacent generation produced by the migration.
        apply (Callable[[SqlCipherCursor], None]): Transactional schema update.

    Returns:
        None
    """

    source_version: int
    target_version: int
    apply: Callable[[SqlCipherCursor], None]


# Register future released migrations here, one adjacent generation per entry.
SCHEMA_MIGRATIONS: tuple[SchemaMigration, ...] = ()


def migration_path(source_version: int) -> tuple[SchemaMigration, ...]:
    """Resolves the complete ordered path from a supported version to current.

    Args:
        source_version (int): Existing database schema generation.

    Raises:
        DatabaseMigrationError: If an adjacent migration step is missing or invalid.

    Returns:
        tuple[SchemaMigration, ...]: Ordered migrations ending at current.
    """
    by_source: dict[int, SchemaMigration] = {}
    for registered_migration in SCHEMA_MIGRATIONS:
        if (
            registered_migration.target_version
            != registered_migration.source_version + 1
        ):
            raise DatabaseMigrationError('Schema migrations must be adjacent.')
        if registered_migration.source_version in by_source:
            raise DatabaseMigrationError('Schema migration sources must be unique.')
        by_source[registered_migration.source_version] = registered_migration

    path: list[SchemaMigration] = []
    version: int = source_version
    while version < DB_SCHEMA_VERSION:
        next_migration = by_source.get(version)
        if next_migration is None:
            raise DatabaseMigrationError(
                f'No database migration is registered from schema {version}.'
            )
        path.append(next_migration)
        version = next_migration.target_version
    return tuple(path)


def migrate_schema(connection: SqlCipherConnection, source_version: int) -> None:
    """Runs each registered migration atomically and advances its durable version.

    Args:
        connection (SqlCipherConnection): Keyed and validated database connection.
        source_version (int): Existing supported schema generation.

    Raises:
        DatabaseMigrationError: If a migration fails or the path is incomplete.

    Returns:
        None
    """
    for migration in migration_path(source_version):
        cursor = connection.cursor()
        try:
            cursor.execute('BEGIN IMMEDIATE')
            migration.apply(cursor)
            cursor.execute(f'PRAGMA user_version = {migration.target_version}')
            connection.commit()
        except Exception as exc:
            try:
                cursor.execute('ROLLBACK')
            except Exception:
                pass
            raise DatabaseMigrationError(
                'Database schema migration '
                f'{migration.source_version} -> {migration.target_version} failed.'
            ) from exc
