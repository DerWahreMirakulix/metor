"""Shared CLI renderers for local profile lifecycle results."""

from typing import Mapping, cast

from metor.core.api import JsonValue
from metor.core.api.codes import ProfileOperationCode
from metor.data.profile import (
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSecurityMode,
)
from metor.data.profile.models import ProfileResultParams, ProfileResultValue


def format_profile_result(result: ProfileOperationResult) -> str:
    """
    Renders one local profile operation result directly for the CLI.

    Args:
        result (ProfileOperationResult): The local profile operation outcome.

    Returns:
        str: The user-facing CLI message.
    """
    params = result.params

    if result.operation_type is ProfileOperationType.INVALID_NAME:
        return 'Invalid profile name.'
    if result.operation_type is ProfileOperationType.DEFAULT_SET:
        return f"Default profile permanently set to '{params['profile']}'."
    if result.operation_type is ProfileOperationType.REMOTE_PORT_REQUIRED:
        return 'A remote profile requires a static port (--port <int>).'
    if result.operation_type is ProfileOperationType.PASSWORDLESS_REMOTE_NOT_ALLOWED:
        return 'Remote profiles cannot be created without password protection.'
    if result.operation_type is ProfileOperationType.PROFILE_EXISTS:
        return f"Profile '{params['profile']}' already exists."
    if result.operation_type is ProfileOperationType.PROFILE_CREATED:
        if params.get('security_mode') == ProfileSecurityMode.PLAINTEXT.value:
            return f"Profile '{params['profile']}' successfully created without password protection."
        return f"Profile '{params['profile']}' successfully created."
    if result.operation_type is ProfileOperationType.PROFILE_CREATED_WITH_PORT:
        storage_suffix: str = ''
        if params.get('security_mode') == ProfileSecurityMode.PLAINTEXT.value:
            storage_suffix = ' without password protection'
        return f"{params['remote_tag']}profile '{params['profile']}' successfully created{storage_suffix} (Port {params['port']})."
    if (
        result.operation_type
        is ProfileOperationType.SECURITY_MIGRATION_REMOTE_NOT_ALLOWED
    ):
        return 'Remote profiles cannot migrate local storage security mode.'
    if result.operation_type is ProfileOperationType.CANNOT_MIGRATE_RUNNING:
        return f"Cannot migrate security mode for '{params['profile']}' while its daemon is running."
    if result.operation_type is ProfileOperationType.SECURITY_MODE_UNCHANGED:
        return f"Profile '{params['profile']}' is already using {params['security_mode']} storage."
    if result.operation_type is ProfileOperationType.SECURITY_MODE_MIGRATED:
        return f"Profile '{params['profile']}' successfully migrated to {params['security_mode']} storage."
    if result.operation_type is ProfileOperationType.SECURITY_MIGRATION_FAILED:
        reason: str = str(params.get('reason') or 'Security migration failed.')
        return reason
    if result.operation_type is ProfileOperationType.PROFILE_NOT_FOUND:
        return f"Profile '{params['profile']}' does not exist."
    if result.operation_type is ProfileOperationType.CANNOT_REMOVE_ACTIVE:
        return 'Cannot remove active profile! Switch to another profile first.'
    if result.operation_type is ProfileOperationType.CANNOT_REMOVE_DEFAULT:
        return 'Cannot remove default profile! Change default first.'
    if result.operation_type is ProfileOperationType.CANNOT_REMOVE_RUNNING:
        return (
            f"Cannot remove profile '{params['profile']}' while its daemon is running!"
        )
    if result.operation_type is ProfileOperationType.PROFILE_REMOVED:
        return f"Profile '{params['profile']}' successfully removed."
    if result.operation_type is ProfileOperationType.CANNOT_RENAME_RUNNING:
        return f"Cannot rename profile '{params['old_profile']}' while its daemon is running!"
    if result.operation_type is ProfileOperationType.PROFILE_RENAMED:
        return f"Profile '{params['old_profile']}' successfully renamed to '{params['new_profile']}'."
    if result.operation_type is ProfileOperationType.CANNOT_CLEAR_RUNNING_DB:
        return (
            f"Cannot clear database for '{params['profile']}' while daemon is running."
        )
    if result.operation_type is ProfileOperationType.DATABASE_NOT_FOUND:
        return f"No database found for profile '{params['profile']}'."
    if result.operation_type is ProfileOperationType.DATABASE_CLEARED:
        return f"Database for profile '{params['profile']}' successfully cleared."
    if result.operation_type is ProfileOperationType.DATABASE_CLEAR_FAILED:
        return 'Error clearing database.'

    return 'Unknown profile operation result.'


def format_profile_result_payload(
    success: bool,
    operation_type: ProfileOperationCode,
    params: Mapping[str, JsonValue],
) -> str:
    """
    Renders one IPC-carried local profile operation payload for the CLI.

    Args:
        success (bool): The local operation success flag.
        operation_type (ProfileOperationCode): The typed IPC operation code.
        params (Mapping[str, JsonValue]): The serialized result parameters.

    Returns:
        str: The user-facing CLI message.
    """
    typed_params: ProfileResultParams = {
        key: cast(ProfileResultValue, value) for key, value in params.items()
    }
    return format_profile_result(
        ProfileOperationResult(
            success=success,
            operation_type=ProfileOperationType(operation_type.value),
            params=typed_params,
        )
    )
