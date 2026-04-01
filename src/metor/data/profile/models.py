"""
Module defining data models and enumerations for profile configurations.
Enforces strict typing for profile-level settings and local profile operation results.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Union

from metor.data import SettingValue


# Types
ProfileConfigValue = Union[SettingValue, None]
NestedConfigDict = Dict[str, Union[ProfileConfigValue, Dict[str, ProfileConfigValue]]]


class ProfileConfigKey(str, Enum):
    """Keys strictly reserved for profile-specific internal states, NOT global overrides."""

    IS_REMOTE = 'is_remote'
    DAEMON_PORT = 'daemon_port'


ProfileResultValue = Union[str, int, float, bool, None]
ProfileResultParams = Dict[str, ProfileResultValue]


class ProfileOperationType(str, Enum):
    """Enumeration of local profile management outcomes outside the IPC API."""

    INVALID_NAME = 'invalid_name'
    DEFAULT_SET = 'default_set'
    REMOTE_PORT_REQUIRED = 'remote_port_required'
    PROFILE_EXISTS = 'profile_exists'
    PROFILE_CREATED = 'profile_created'
    PROFILE_CREATED_WITH_PORT = 'profile_created_with_port'
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


@dataclass(frozen=True)
class ProfileOperationResult:
    """Structured local profile operation result consumed directly by the CLI."""

    success: bool
    operation_type: ProfileOperationType
    params: ProfileResultParams
