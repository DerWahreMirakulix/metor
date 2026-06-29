"""Profile-management command DTOs for local headless orchestration."""

from dataclasses import dataclass, field
from typing import Optional

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


@register_command(CommandType.ADD_PROFILE)
@dataclass
class AddProfileCommand(IpcCommand):
    """Requests creation of one local or remote profile entry."""

    name: str
    is_remote: bool = False
    port: Optional[int] = None
    security_mode: str = 'encrypted'
    command_type: CommandType = field(default=CommandType.ADD_PROFILE, init=False)


@register_command(CommandType.MIGRATE_PROFILE_SECURITY)
@dataclass
class MigrateProfileSecurityCommand(IpcCommand):
    """Requests migration of one local profile between encrypted and plaintext storage."""

    name: str
    target_mode: str
    current_password: Optional[str] = None
    new_password: Optional[str] = None
    command_type: CommandType = field(
        default=CommandType.MIGRATE_PROFILE_SECURITY,
        init=False,
    )


@register_command(CommandType.REMOVE_PROFILE)
@dataclass
class RemoveProfileCommand(IpcCommand):
    """Requests complete local removal of one profile."""

    name: str
    active_profile: Optional[str] = None
    command_type: CommandType = field(default=CommandType.REMOVE_PROFILE, init=False)


@register_command(CommandType.RENAME_PROFILE)
@dataclass
class RenameProfileCommand(IpcCommand):
    """Requests renaming of one local profile directory."""

    old_name: str
    new_name: str
    command_type: CommandType = field(default=CommandType.RENAME_PROFILE, init=False)


@register_command(CommandType.SET_DEFAULT_PROFILE)
@dataclass
class SetDefaultProfileCommand(IpcCommand):
    """Requests one new default-profile selection."""

    profile_name: str
    command_type: CommandType = field(
        default=CommandType.SET_DEFAULT_PROFILE,
        init=False,
    )
