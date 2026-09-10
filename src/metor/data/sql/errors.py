"""Domain errors for SQL persistence and schema compatibility."""


class DatabaseCorruptedError(ValueError):
    """Raised when a profile database cannot be opened safely."""


class UnsupportedDatabaseSchemaError(DatabaseCorruptedError):
    """Raised when a database schema generation cannot be opened safely."""


class NewerDatabaseSchemaError(UnsupportedDatabaseSchemaError):
    """Raised when a database was created by a newer Metor generation."""


class LegacyDatabaseSchemaError(UnsupportedDatabaseSchemaError):
    """Raised when a database predates the oldest supported schema generation."""


class DatabaseMigrationError(DatabaseCorruptedError):
    """Raised when no complete or successful schema migration path exists."""
