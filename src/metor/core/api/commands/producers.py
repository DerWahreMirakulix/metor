"""Explicit disposable Voice owner registration and lifecycle release."""

from dataclasses import dataclass, field

# Local Package Imports
from ..base import IpcCommand
from ..codes import CommandType
from ..registry import register_command


@register_command(CommandType.REGISTER_VOICE_OWNER)
@dataclass
class RegisterVoiceOwnerCommand(IpcCommand):
    """Registers disposable DROP staging and interrupted-LIVE producer cleanup."""

    disposable_drop: bool = True
    command_type: CommandType = field(
        default=CommandType.REGISTER_VOICE_OWNER, init=False
    )


@register_command(CommandType.RELEASE_VOICE_OWNER)
@dataclass(repr=False)
class ReleaseVoiceOwnerCommand(IpcCommand):
    """Releases only this session's owner; pending cleanup remains Core-owned."""

    owner_token: str = ''
    command_type: CommandType = field(
        default=CommandType.RELEASE_VOICE_OWNER, init=False
    )
