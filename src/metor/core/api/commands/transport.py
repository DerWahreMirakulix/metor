"""Transport and live-lifecycle command DTOs."""

from dataclasses import dataclass, field
from typing import Optional

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


@register_command(CommandType.GET_TRANSPORT_STATE)
@dataclass
class GetTransportStateCommand(IpcCommand):
    """Requests the current transport state for one peer or the whole daemon."""

    peer: Optional[str] = None
    command_type: CommandType = field(
        default=CommandType.GET_TRANSPORT_STATE,
        init=False,
    )
