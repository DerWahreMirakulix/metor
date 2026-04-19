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
    """
    Requests one global settings update.

    Attributes:
        setting_key (str): The fully-qualified settings key to update.
        setting_value (Union[str, int, float, bool]): The new primitive value.
        command_type (CommandType): The stable IPC routing code.
    """

    setting_key: str
    setting_value: Union[str, int, float, bool]
    command_type: CommandType = field(default=CommandType.SET_SETTING, init=False)


@register_command(CommandType.GET_SETTING)
@dataclass
class GetSettingCommand(IpcCommand):
    """
    Requests one global settings value.

    Attributes:
        setting_key (str): The fully-qualified settings key to fetch.
        command_type (CommandType): The stable IPC routing code.
    """

    setting_key: str
    command_type: CommandType = field(default=CommandType.GET_SETTING, init=False)


@register_command(CommandType.GET_SETTINGS_LIST)
@dataclass
class GetSettingsListCommand(IpcCommand):
    """
    Requests the daemon-side global settings snapshot.

    Attributes:
        command_type (CommandType): The stable IPC routing code.
    """

    command_type: CommandType = field(
        default=CommandType.GET_SETTINGS_LIST,
        init=False,
    )


@register_command(CommandType.SET_CONFIG)
@dataclass
class SetConfigCommand(IpcCommand):
    """
    Requests one profile-local config override update.

    Attributes:
        setting_key (str): The fully-qualified config key to update.
        setting_value (Union[str, int, float, bool]): The new primitive value.
        command_type (CommandType): The stable IPC routing code.
    """

    setting_key: str
    setting_value: Union[str, int, float, bool]
    command_type: CommandType = field(default=CommandType.SET_CONFIG, init=False)


@register_command(CommandType.GET_CONFIG)
@dataclass
class GetConfigCommand(IpcCommand):
    """
    Requests one effective profile config value.

    Attributes:
        setting_key (str): The fully-qualified config key to fetch.
        command_type (CommandType): The stable IPC routing code.
    """

    setting_key: str
    command_type: CommandType = field(default=CommandType.GET_CONFIG, init=False)


@register_command(CommandType.GET_CONFIG_LIST)
@dataclass
class GetConfigListCommand(IpcCommand):
    """
    Requests the daemon-side effective profile-config snapshot.

    Attributes:
        command_type (CommandType): The stable IPC routing code.
    """

    command_type: CommandType = field(default=CommandType.GET_CONFIG_LIST, init=False)


@register_command(CommandType.SYNC_CONFIG)
@dataclass
class SyncConfigCommand(IpcCommand):
    """
    Requests a profile-config sync against global settings.

    Attributes:
        command_type (CommandType): The stable IPC routing code.
    """

    command_type: CommandType = field(default=CommandType.SYNC_CONFIG, init=False)
