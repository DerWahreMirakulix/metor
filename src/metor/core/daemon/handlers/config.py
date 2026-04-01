"""
Module defining the ConfigCommandHandler.
Encapsulates operations routing global settings and profile configurations.
Enforces the Zero-Text Policy by eliminating raw string errors from DTOs.
"""

from typing import Union

from metor.core.api import (
    EventType,
    IpcCommand,
    IpcEvent,
    create_event,
    SetSettingCommand,
    GetSettingCommand,
    SetConfigCommand,
    GetConfigCommand,
    SyncConfigCommand,
)
from metor.data import Settings, SettingKey
from metor.data.profile import ProfileManager, ProfileConfigKey


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
                setting_key = SettingKey(cmd.setting_key)
            except ValueError:
                return create_event(EventType.INVALID_SETTING_KEY)

            if setting_key.is_ui:
                return create_event(EventType.DAEMON_CANNOT_MANAGE_UI)

            try:
                Settings.set(setting_key, cmd.setting_value)
                return create_event(
                    EventType.SETTING_UPDATED,
                    {'key': cmd.setting_key},
                )
            except TypeError:
                return create_event(EventType.SETTING_TYPE_ERROR)
            except Exception:
                return create_event(EventType.SETTING_UPDATE_FAILED)

        if isinstance(cmd, GetSettingCommand):
            try:
                setting_key = SettingKey(cmd.setting_key)
            except ValueError:
                return create_event(EventType.INVALID_SETTING_KEY)

            if setting_key.is_ui:
                return create_event(EventType.DAEMON_CANNOT_MANAGE_UI)

            try:
                val: str = Settings.get_str(setting_key)
                return create_event(
                    EventType.SETTING_DATA,
                    {'key': cmd.setting_key, 'value': val},
                )
            except ValueError:
                return create_event(EventType.INVALID_SETTING_KEY)

        if isinstance(cmd, SetConfigCommand):
            set_config_key: Union[SettingKey, ProfileConfigKey]
            try:
                set_config_key = SettingKey(cmd.setting_key)
            except ValueError:
                try:
                    set_config_key = ProfileConfigKey(cmd.setting_key)
                except ValueError:
                    return create_event(EventType.INVALID_CONFIG_KEY)

            if getattr(set_config_key, 'is_ui', False):
                return create_event(EventType.DAEMON_CANNOT_MANAGE_UI)

            try:
                self._pm.config.set(set_config_key, cmd.setting_value)
                return create_event(
                    EventType.CONFIG_UPDATED,
                    {'key': cmd.setting_key},
                )
            except TypeError:
                return create_event(EventType.SETTING_TYPE_ERROR)
            except Exception:
                return create_event(EventType.CONFIG_UPDATE_FAILED)

        if isinstance(cmd, GetConfigCommand):
            get_config_key: Union[SettingKey, ProfileConfigKey]
            try:
                get_config_key = SettingKey(cmd.setting_key)
            except ValueError:
                try:
                    get_config_key = ProfileConfigKey(cmd.setting_key)
                except ValueError:
                    return create_event(EventType.INVALID_CONFIG_KEY)

            if getattr(get_config_key, 'is_ui', False):
                return create_event(EventType.DAEMON_CANNOT_MANAGE_UI)

            try:
                val = self._pm.config.get_str(get_config_key)
                return create_event(
                    EventType.CONFIG_DATA,
                    {'key': cmd.setting_key, 'value': val},
                )
            except ValueError:
                return create_event(EventType.INVALID_CONFIG_KEY)

        if isinstance(cmd, SyncConfigCommand):
            try:
                self._pm.config.sync_with_global()
                return create_event(EventType.CONFIG_SYNCED)
            except Exception:
                return create_event(EventType.CONFIG_UPDATE_FAILED)

        return create_event(EventType.UNKNOWN_COMMAND)
