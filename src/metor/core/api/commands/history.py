"""History command DTOs for projected and raw history retrieval."""

from dataclasses import dataclass, field
from typing import Optional

from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


@register_command(CommandType.GET_HISTORY)
@dataclass
class GetHistoryCommand(IpcCommand):
    """Requests projected user-facing history summary."""

    target: Optional[str] = None
    limit: Optional[int] = None
    command_type: CommandType = field(default=CommandType.GET_HISTORY, init=False)


@register_command(CommandType.GET_RAW_HISTORY)
@dataclass
class GetRawHistoryCommand(IpcCommand):
    """Requests the raw transport history ledger."""

    target: Optional[str] = None
    limit: Optional[int] = None
    command_type: CommandType = field(
        default=CommandType.GET_RAW_HISTORY,
        init=False,
    )


@register_command(CommandType.CLEAR_HISTORY)
@dataclass
class ClearHistoryCommand(IpcCommand):
    """Clears persisted history rows."""

    target: Optional[str] = None
    command_type: CommandType = field(default=CommandType.CLEAR_HISTORY, init=False)
