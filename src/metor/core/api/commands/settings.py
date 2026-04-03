"""Settings and config command DTOs."""

from dataclasses import dataclass, field
from typing import Union

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


@register_command(CommandType.SET_SETTING)
@dataclass
class SetSettingCommand(IpcCommand):
    """Updates a global setting."""

    setting_key: str
    setting_value: Union[str, int, float, bool]
    command_type: CommandType = field(default=CommandType.SET_SETTING, init=False)


@register_command(CommandType.GET_SETTING)
@dataclass
class GetSettingCommand(IpcCommand):
    """Requests a global setting value."""

    setting_key: str
    command_type: CommandType = field(default=CommandType.GET_SETTING, init=False)


@register_command(CommandType.SET_CONFIG)
@dataclass
class SetConfigCommand(IpcCommand):
    """Updates a profile-specific configuration override."""

    setting_key: str
    setting_value: Union[str, int, float, bool]
    command_type: CommandType = field(default=CommandType.SET_CONFIG, init=False)


@register_command(CommandType.GET_CONFIG)
@dataclass
class GetConfigCommand(IpcCommand):
    """Requests a profile-specific configuration value."""

    setting_key: str
    command_type: CommandType = field(default=CommandType.GET_CONFIG, init=False)


@register_command(CommandType.SYNC_CONFIG)
@dataclass
class SyncConfigCommand(IpcCommand):
    """Syncs profile configuration overrides with global settings."""

    command_type: CommandType = field(default=CommandType.SYNC_CONFIG, init=False)
