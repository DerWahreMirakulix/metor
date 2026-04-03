"""Administrative and destructive command DTOs."""

from dataclasses import dataclass, field

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


@register_command(CommandType.CLEAR_PROFILE_DB)
@dataclass
class ClearProfileDbCommand(IpcCommand):
    """Requests a full profile-database wipe."""

    command_type: CommandType = field(
        default=CommandType.CLEAR_PROFILE_DB,
        init=False,
    )


@register_command(CommandType.SELF_DESTRUCT)
@dataclass
class SelfDestructCommand(IpcCommand):
    """Triggers daemon self-destruction."""

    command_type: CommandType = field(
        default=CommandType.SELF_DESTRUCT,
        init=False,
    )
