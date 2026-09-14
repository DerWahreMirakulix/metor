"""Administrative and destructive command DTOs."""

from dataclasses import dataclass, field

from metor.shared import Constants

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

    operation_id: str | None = None
    command_type: CommandType = field(
        default=CommandType.SELF_DESTRUCT,
        init=False,
    )

    def __post_init__(self) -> None:
        """Validates an optional exact operation identity without granting authorization.

        Args:
            None
        Returns:
            None
        """
        if self.operation_id is not None and (
            not isinstance(self.operation_id, str)
            or len(self.operation_id) != 2 * Constants.DESTRUCTION_OPERATION_BYTES
            or any(char not in '0123456789abcdef' for char in self.operation_id)
        ):
            raise ValueError('Invalid destruction operation identity')


@register_command(CommandType.PREPARE_PROFILE_EXIT)
@dataclass
class PrepareProfileExitCommand(IpcCommand):
    """Durably prepares normal profile exit without awaiting remote delivery."""

    command_type: CommandType = field(
        default=CommandType.PREPARE_PROFILE_EXIT,
        init=False,
    )
