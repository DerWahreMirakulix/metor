"""
Module defining data models and enumerations for profile configurations.
Enforces strict typing for profile-level settings and local profile operation results.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Union

from metor.data import SettingValue


# Types
ProfileConfigValue = Union[SettingValue, None]
NestedConfigDict = Dict[str, Union[ProfileConfigValue, Dict[str, ProfileConfigValue]]]


class ProfileConfigKey(str, Enum):
    """Keys strictly reserved for profile-specific internal states, NOT global overrides."""

    IS_REMOTE = 'is_remote'
    DAEMON_PORT = 'daemon_port'
    SECURITY_MODE = 'security_mode'


class ProfileSecurityMode(str, Enum):
    """Enumeration of supported profile storage security modes."""

    ENCRYPTED = 'encrypted'
    PLAINTEXT = 'plaintext'


class ProfileConfigValidationError(ValueError):
    """Raised when a profile configuration value violates semantic constraints."""


@dataclass(frozen=True)
class ProfileConfigSpec:
    """Describes one structural profile configuration key."""

    key: ProfileConfigKey
    default: ProfileConfigValue
    description: str
    constraints: str
    mutable_after_creation: bool
    min_value: Optional[int] = None
    max_value: Optional[int] = None


PROFILE_CONFIG_SPECS: Dict[ProfileConfigKey, ProfileConfigSpec] = {
    ProfileConfigKey.IS_REMOTE: ProfileConfigSpec(
        key=ProfileConfigKey.IS_REMOTE,
        default=False,
        description='Marks the profile as a remote client profile instead of a local daemon owner.',
        constraints='Boolean. Immutable after profile creation.',
        mutable_after_creation=False,
    ),
    ProfileConfigKey.DAEMON_PORT: ProfileConfigSpec(
        key=ProfileConfigKey.DAEMON_PORT,
        default=None,
        description='Stores the static IPC port for remote profiles or the current daemon port file value.',
        constraints='Positive integer between 1 and 65535, or null.',
        mutable_after_creation=True,
        min_value=1,
        max_value=65535,
    ),
    ProfileConfigKey.SECURITY_MODE: ProfileConfigSpec(
        key=ProfileConfigKey.SECURITY_MODE,
        default=ProfileSecurityMode.ENCRYPTED.value,
        description='Declares whether the local profile stores keys and the database encrypted or plaintext at rest.',
        constraints="One of 'encrypted' or 'plaintext'. Immutable after profile creation except through the dedicated migration workflow.",
        mutable_after_creation=False,
    ),
}


def validate_profile_config_value(
    key: ProfileConfigKey,
    value: ProfileConfigValue,
) -> ProfileConfigValue:
    """
    Validates and normalizes one profile configuration value.

    Args:
        key (ProfileConfigKey): The structural profile configuration key.
        value (ProfileConfigValue): The candidate value.

    Raises:
        TypeError: If the value type is invalid.
        ProfileConfigValidationError: If the value violates semantic constraints.

    Returns:
        ProfileConfigValue: The normalized value.
    """
    spec: ProfileConfigSpec = PROFILE_CONFIG_SPECS[key]

    if key is ProfileConfigKey.IS_REMOTE:
        if type(value) is not bool:
            raise TypeError(
                f"Invalid type for '{key.value}'. Expected bool, got {type(value).__name__}."
            )
        return value

    if key is ProfileConfigKey.DAEMON_PORT:
        if value is None:
            return None
        if type(value) is not int:
            raise TypeError(
                f"Invalid type for '{key.value}'. Expected int, got {type(value).__name__}."
            )
        if spec.min_value is not None and value < spec.min_value:
            raise ProfileConfigValidationError(
                f"Setting '{key.value}' must be >= {spec.min_value}."
            )
        if spec.max_value is not None and value > spec.max_value:
            raise ProfileConfigValidationError(
                f"Setting '{key.value}' must be <= {spec.max_value}."
            )
        return value

    if key is ProfileConfigKey.SECURITY_MODE:
        if isinstance(value, ProfileSecurityMode):
            return value.value
        if type(value) is not str:
            raise TypeError(
                f"Invalid type for '{key.value}'. Expected str, got {type(value).__name__}."
            )

        try:
            mode: ProfileSecurityMode = ProfileSecurityMode(value.strip().lower())
        except ValueError as exc:
            raise ProfileConfigValidationError(
                f"Setting '{key.value}' must be one of: encrypted, plaintext."
            ) from exc

        return mode.value

    return value


ProfileResultValue = Union[str, int, float, bool, None]
ProfileResultParams = Dict[str, ProfileResultValue]


class ProfileOperationType(str, Enum):
    """Enumeration of local profile management outcomes outside the IPC API."""

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


@dataclass(frozen=True)
class ProfileOperationResult:
    """Structured local profile operation result consumed directly by the CLI."""

    success: bool
    operation_type: ProfileOperationType
    params: ProfileResultParams
