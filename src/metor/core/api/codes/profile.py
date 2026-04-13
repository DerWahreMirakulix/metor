"""Profile-operation codes shared across the strict IPC boundary."""

from enum import Enum


class ProfileOperationCode(str, Enum):
    """Enumeration of local profile operation outcomes transported over IPC."""

    INVALID_NAME = 'invalid_name'
    DEFAULT_SET = 'default_set'
    REMOTE_PORT_REQUIRED = 'remote_port_required'
    PASSWORDLESS_REMOTE_NOT_ALLOWED = 'passwordless_remote_not_allowed'
    PROFILE_EXISTS = 'profile_exists'
    PROFILE_CREATED = 'profile_created'
    PROFILE_CREATED_WITH_PORT = 'profile_created_with_port'
    SECURITY_MIGRATION_REMOTE_NOT_ALLOWED = 'security_migration_remote_not_allowed'
    CANNOT_MIGRATE_RUNNING = 'cannot_migrate_running'
    SECURITY_MODE_UNCHANGED = 'security_mode_unchanged'
    SECURITY_MODE_MIGRATED = 'security_mode_migrated'
    SECURITY_MIGRATION_FAILED = 'security_migration_failed'
    PROFILE_NOT_FOUND = 'profile_not_found'
    CANNOT_REMOVE_ACTIVE = 'cannot_remove_active'
    CANNOT_REMOVE_DEFAULT = 'cannot_remove_default'
    CANNOT_REMOVE_RUNNING = 'cannot_remove_running'
    PROFILE_REMOVED = 'profile_removed'
    CANNOT_RENAME_RUNNING = 'cannot_rename_running'
    PROFILE_RENAMED = 'profile_renamed'
    CANNOT_CLEAR_RUNNING_DB = 'cannot_clear_running_db'
    DATABASE_NOT_FOUND = 'database_not_found'
    DATABASE_CLEARED = 'database_cleared'
    DATABASE_CLEAR_FAILED = 'database_clear_failed'
