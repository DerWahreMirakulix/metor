"""Address-management command DTOs."""

from dataclasses import dataclass, field

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


@register_command(CommandType.GET_ADDRESS)
@dataclass
class GetAddressCommand(IpcCommand):
    """Requests the current onion address."""

    command_type: CommandType = field(
        default=CommandType.GET_ADDRESS,
        init=False,
    )


@register_command(CommandType.GENERATE_ADDRESS)
@dataclass
class GenerateAddressCommand(IpcCommand):
    """Requests generation of a new onion address."""

    command_type: CommandType = field(
        default=CommandType.GENERATE_ADDRESS,
        init=False,
    )
