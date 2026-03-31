"""
Module defining the ConfigCommandHandler.
Encapsulates operations routing global settings and profile configurations.
"""

from metor.core.api import (
    IpcCommand,
    IpcEvent,
    SystemCode,
    SetSettingCommand,
    GetSettingCommand,
    SetConfigCommand,
    GetConfigCommand,
    SyncConfigCommand,
    ActionErrorEvent,
    SettingUpdatedEvent,
    SettingDataEvent,
    ConfigUpdatedEvent,
    ConfigDataEvent,
    ConfigSyncedEvent,
)
from metor.data import Settings, SettingKey
from metor.data.profile import ProfileManager


class ConfigCommandHandler:
    """Processes configuration and settings IPC commands from the UI."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the ConfigCommandHandler.

        Args:
            pm (ProfileManager): Profile configuration.

        Returns:
            None
        """
        self._pm: ProfileManager = pm

    def handle(self, cmd: IpcCommand) -> IpcEvent:
        """
        Routes the configuration command to the respective persistence manager.

        Args:
            cmd (IpcCommand): The configuration-related IPC command.

        Returns:
            IpcEvent: The strictly typed response event DTO.
        """
        if isinstance(cmd, SetSettingCommand):
            try:
                key_enum = SettingKey(cmd.setting_key)
            except ValueError:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_TYPE_ERROR,
                    reason='Invalid setting key.',
                )

            if key_enum.is_ui:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_UPDATE_FAILED,
                    reason='Daemon cannot manage UI settings.',
                )

            try:
                Settings.set(key_enum, cmd.setting_value)
                return SettingUpdatedEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_UPDATED,
                    key=cmd.setting_key,
                )
            except TypeError as e:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_TYPE_ERROR,
                    reason=str(e),
                )
            except Exception as e:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_UPDATE_FAILED,
                    reason=str(e),
                )

        if isinstance(cmd, GetSettingCommand):
            try:
                key_enum = SettingKey(cmd.setting_key)
            except ValueError:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_TYPE_ERROR,
                    reason='Invalid setting key.',
                )

            if key_enum.is_ui:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_TYPE_ERROR,
                    reason='Daemon cannot manage UI settings.',
                )

            try:
                val: str = Settings.get_str(key_enum)
                return SettingDataEvent(
                    key=cmd.setting_key,
                    value=val,
                )
            except ValueError:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_TYPE_ERROR,
                    reason='Invalid setting key.',
                )

        if isinstance(cmd, SetConfigCommand):
            try:
                key_enum = SettingKey(cmd.setting_key)
            except ValueError:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_TYPE_ERROR,
                    reason='Invalid config key.',
                )

            if key_enum.is_ui:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.CONFIG_UPDATE_FAILED,
                    reason='Daemon cannot manage UI configs.',
                )

            try:
                self._pm.config.set(key_enum, cmd.setting_value)
                return ConfigUpdatedEvent(
                    action=cmd.action,
                    code=SystemCode.CONFIG_UPDATED,
                    key=cmd.setting_key,
                )
            except TypeError as e:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_TYPE_ERROR,
                    reason=str(e),
                )
            except Exception as e:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.CONFIG_UPDATE_FAILED,
                    reason=str(e),
                )

        if isinstance(cmd, GetConfigCommand):
            try:
                key_enum = SettingKey(cmd.setting_key)
            except ValueError:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_TYPE_ERROR,
                    reason='Invalid config key.',
                )

            if key_enum.is_ui:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_TYPE_ERROR,
                    reason='Daemon cannot manage UI configs.',
                )

            try:
                val = self._pm.config.get_str(key_enum)
                return ConfigDataEvent(
                    key=cmd.setting_key,
                    value=val,
                )
            except ValueError:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.SETTING_TYPE_ERROR,
                    reason='Invalid config key.',
                )

        if isinstance(cmd, SyncConfigCommand):
            try:
                self._pm.config.sync_with_global()
                return ConfigSyncedEvent(
                    action=cmd.action,
                    code=SystemCode.CONFIG_SYNCED,
                )
            except Exception as e:
                return ActionErrorEvent(
                    action=cmd.action,
                    code=SystemCode.CONFIG_UPDATE_FAILED,
                    reason=str(e),
                )

        return ActionErrorEvent(
            action=cmd.action,
            code=SystemCode.UNKNOWN_COMMAND,
        )
