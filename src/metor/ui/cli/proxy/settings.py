"""Settings and config helpers for the CLI proxy facade."""

from typing import Callable, Union

from metor.core.api import (
    EventType,
    GetConfigCommand,
    GetSettingCommand,
    SetConfigCommand,
    SetSettingCommand,
    SyncConfigCommand,
)
from metor.data.profile import ProfileConfigKey, ProfileManager
from metor.data.settings import Settings, SettingKey
from metor.ui import Theme
from metor.utils import TypeCaster


class CliProxySettingsActions:
    """Owns settings and config flows for the CLI proxy."""

    _settings_cls = Settings

    def __init__(
        self,
        pm: ProfileManager,
        *,
        is_remote: bool,
        request_ipc: Callable[..., str],
        translate_event: Callable[..., str],
    ) -> None:
        """
        Initializes the settings helper.

        Args:
            pm (ProfileManager): The active profile configuration.
            is_remote (bool): Whether the active profile is remote.
            request_ipc (Callable[..., str]): IPC request callback.
            translate_event (Callable[[EventType, Optional[Dict[str, JsonValue]]], str]): Event translator callback.

        Returns:
            None
        """
        self._pm = pm
        self._is_remote = is_remote
        self._request_ipc = request_ipc
        self._translate_event = translate_event

    def handle_settings_set(self, key: str, value: str) -> str:
        """
        Sets one global setting.

        Args:
            key (str): The setting key.
            value (str): The new value.

        Returns:
            str: The formatted status message.
        """
        try:
            key_enum: SettingKey = SettingKey(key)
        except ValueError:
            return self._translate_event(EventType.INVALID_SETTING_KEY)

        parsed_value: Union[str, int, float, bool] = TypeCaster.infer_from_string(value)

        if key_enum.is_ui:
            try:
                self._pm.config.set(key_enum, parsed_value)
                return (
                    f"Global setting '{Theme.YELLOW}{key}{Theme.RESET}' updated "
                    'successfully.'
                )
            except (TypeError, ValueError) as exc:
                return self._translate_event(
                    EventType.SETTING_TYPE_ERROR,
                    {'key': key, 'reason': str(exc)},
                )

        return self._request_ipc(
            SetSettingCommand(setting_key=key, setting_value=parsed_value)
        )

    def handle_settings_get(self, key: str) -> str:
        """
        Retrieves one setting value.

        Args:
            key (str): The setting key.

        Returns:
            str: The formatted setting output.
        """
        try:
            key_enum: SettingKey = SettingKey(key)
        except ValueError:
            return self._translate_event(EventType.INVALID_SETTING_KEY)

        if key_enum.is_ui:
            val: str = self._pm.config.get_str(key_enum)
            return (
                f"Effective UI Setting '{Theme.YELLOW}{key}{Theme.RESET}': "
                f'{Theme.CYAN}{val}{Theme.RESET}'
            )

        return self._request_ipc(GetSettingCommand(setting_key=key))

    def handle_config_set(self, key: str, value: str) -> str:
        """
        Sets one profile-specific configuration override.

        Args:
            key (str): The config key.
            value (str): The new value.

        Returns:
            str: The formatted status message.
        """
        if key == ProfileConfigKey.IS_REMOTE.value:
            return (
                f"The '{Theme.YELLOW}is_remote{Theme.RESET}' flag is immutable and "
                'cannot be changed after profile creation.'
            )

        try:
            key_enum: Union[SettingKey, ProfileConfigKey] = SettingKey(key)
        except ValueError:
            try:
                key_enum = ProfileConfigKey(key)
            except ValueError:
                return self._translate_event(EventType.INVALID_CONFIG_KEY)

        parsed_value: Union[str, int, float, bool] = TypeCaster.infer_from_string(value)

        if isinstance(key_enum, ProfileConfigKey) or key_enum.is_ui:
            try:
                self._pm.config.set(key_enum, parsed_value)
                return (
                    f"Profile configuration override for '{Theme.YELLOW}{key}{Theme.RESET}' "
                    'updated successfully.'
                )
            except (TypeError, ValueError) as exc:
                return self._translate_event(
                    EventType.SETTING_TYPE_ERROR,
                    {'key': key, 'reason': str(exc)},
                )

        return self._request_ipc(
            SetConfigCommand(setting_key=key, setting_value=parsed_value)
        )

    def handle_config_get(self, key: str) -> str:
        """
        Retrieves the effective profile-specific configuration value.

        Args:
            key (str): The config key.

        Returns:
            str: The formatted config output.
        """
        try:
            key_enum: Union[SettingKey, ProfileConfigKey] = SettingKey(key)
        except ValueError:
            try:
                key_enum = ProfileConfigKey(key)
            except ValueError:
                return self._translate_event(EventType.INVALID_CONFIG_KEY)

        if isinstance(key_enum, ProfileConfigKey) or key_enum.is_ui:
            val: str = self._pm.config.get_str(key_enum)
            return (
                f"Profile Config '{Theme.YELLOW}{key}{Theme.RESET}': "
                f'{Theme.CYAN}{val}{Theme.RESET}'
            )

        return self._request_ipc(GetConfigCommand(setting_key=key))

    def handle_config_sync(self) -> str:
        """
        Clears profile overrides and syncs with global defaults.

        Args:
            None

        Returns:
            str: The formatted status message.
        """
        try:
            self._pm.config.sync_with_global()
            local_msg: str = (
                'Profile overrides cleared. Config is now synced with global settings.'
            )
        except Exception:
            return 'Failed to update profile config.'

        if self._is_remote or self._pm.is_daemon_running():
            daemon_msg: str = self._request_ipc(SyncConfigCommand())
            if self._is_remote:
                return f'{local_msg}\n{daemon_msg}'
            return daemon_msg

        return local_msg
