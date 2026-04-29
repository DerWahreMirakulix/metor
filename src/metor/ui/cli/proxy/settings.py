"""Settings and config helpers for the CLI proxy facade."""

from typing import Callable, Iterable, Union

from metor.core.api import (
    ConfigListDataEvent,
    EventType,
    GetConfigCommand,
    GetConfigListCommand,
    GetSettingCommand,
    GetSettingsListCommand,
    IpcEvent,
    JsonValue,
    SettingsListDataEvent,
    SetConfigCommand,
    SetSettingCommand,
    SettingSnapshotEntry,
    SyncConfigCommand,
)
from metor.data import (
    ProfileConfigKey,
    ProfileManager,
    Settings,
    SettingKey,
    SettingSnapshotRow,
)
from metor.ui import Theme, UIPresenter
from metor.ui.cli.ipc.request.models import IpcRequestResult
from metor.utils import TypeCaster


def _build_snapshot_entries(
    rows: Iterable[SettingSnapshotRow],
) -> list[SettingSnapshotEntry]:
    """
    Converts internal snapshot rows into strict UI DTO entries.

    Args:
        rows (Iterable[SettingSnapshotRow]): The internal snapshot rows.

    Returns:
        list[SettingSnapshotEntry]: The typed DTO entries for local rendering.
    """
    return [
        SettingSnapshotEntry(
            key=row['key'],
            value=row['value'],
            source=row['source'],
            category=row['category'],
        )
        for row in rows
    ]


class CliProxySettingsActions:
    """Owns settings and config flows for the CLI proxy."""

    _settings_cls = Settings

    def __init__(
        self,
        pm: ProfileManager,
        *,
        is_remote: bool,
        prefix_remote: Callable[[str], str],
        request_ipc: Callable[..., str],
        request_ipc_result: Callable[..., IpcRequestResult],
        translate_event: Callable[..., str],
    ) -> None:
        """
        Initializes the settings helper.

        Args:
            pm (ProfileManager): The active profile configuration.
            is_remote (bool): Whether the active profile is remote.
            prefix_remote (Callable[[str], str]): Remote-prefix renderer callback.
            request_ipc (Callable[..., str]): IPC request callback.
            request_ipc_result (Callable[..., IpcRequestResult]): Raw IPC request callback.
            translate_event (Callable[[EventType, Optional[Dict[str, JsonValue]]], str]): Event translator callback.

        Returns:
            None
        """
        self._pm = pm
        self._is_remote = is_remote
        self._prefix_remote = prefix_remote
        self._request_ipc = request_ipc
        self._request_ipc_result = request_ipc_result
        self._translate_event = translate_event

    @staticmethod
    def _merge_snapshot_sections(
        local_sections: list[str],
        daemon_section: str,
        *,
        insert_leading_blank_line: bool = False,
    ) -> str:
        """
        Combines local and daemon snapshot sections with stable spacing.

        Args:
            local_sections (list[str]): Locally rendered sections.
            daemon_section (str): The daemon-rendered section.
            insert_leading_blank_line (bool): Whether one auth prompt should separate the output from the terminal prompt.

        Returns:
            str: The normalized combined output.
        """
        sections: list[str] = [
            *(section.rstrip('\n') for section in local_sections if section),
            daemon_section.rstrip('\n'),
        ]
        rendered: str = '\n\n'.join(section for section in sections if section)
        if not rendered:
            return rendered

        if insert_leading_blank_line:
            return f'\n{rendered}\n'
        return f'{rendered}\n'

    @staticmethod
    def _extract_event_params(event: IpcEvent) -> dict[str, JsonValue]:
        """
        Extracts JSON-safe event fields for local UI translation.

        Args:
            event (IpcEvent): The source IPC event.

        Returns:
            dict[str, JsonValue]: The JSON-safe event parameters.
        """
        params_raw: dict[str, object] = vars(event)
        return {
            key: value
            for key, value in params_raw.items()
            if key not in ('event_type', 'request_id')
            and isinstance(value, (str, int, float, bool, type(None), list, dict))
        }

    def _render_daemon_snapshot_result(
        self,
        result: IpcRequestResult,
        *,
        expected_data_event: EventType,
        unavailable_subject: str,
    ) -> str:
        """
        Formats one daemon snapshot result or a contextual omission notice.

        Args:
            result (IpcRequestResult): The raw daemon request result.
            expected_data_event (EventType): The expected successful snapshot event type.
            unavailable_subject (str): Human-readable label for the omitted daemon section.

        Returns:
            str: The rendered daemon section or omission message.
        """
        if result.event is not None and result.event.event_type is expected_data_event:
            section: str = UIPresenter.format_response(result.event)
            if self._is_remote:
                return self._prefix_remote(section)
            return section

        if result.auth_incomplete:
            section = (
                f'{unavailable_subject} were not shown because local daemon '
                'authentication did not complete.'
            )
            if self._is_remote:
                return self._prefix_remote(section)
            return section

        detail: str = ''
        reason: str = 'because the daemon request failed.'
        if result.event is not None:
            detail = self._translate_event(
                result.event.event_type,
                self._extract_event_params(result.event),
            )
            if result.event.event_type in (
                EventType.INVALID_PASSWORD,
                EventType.LOCAL_AUTH_RATE_LIMITED,
            ):
                reason = 'because local daemon authentication failed.'
        else:
            detail = result.message or ''
            if result.insert_leading_blank_line:
                reason = 'because local daemon authentication did not complete.'

        if not detail:
            return ''

        if '\n' in detail:
            section = f'{unavailable_subject} were not shown {reason}\n{detail}'
        else:
            section = f'{unavailable_subject} were not shown {reason} {detail}'
        if self._is_remote:
            return self._prefix_remote(section)
        return section

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
                self._settings_cls.set(key_enum, parsed_value)
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
            val: str = self._settings_cls.get_str(key_enum)
            return self._translate_event(
                EventType.SETTING_DATA,
                {'key': key, 'value': val},
            )

        return self._request_ipc(GetSettingCommand(setting_key=key))

    def handle_settings_list(self) -> str:
        """
        Lists global settings across local UI scope and daemon scope.

        Args:
            None

        Returns:
            str: The formatted snapshot output.
        """
        local_sections: list[str] = [
            UIPresenter.format_response(
                SettingsListDataEvent(
                    scope='ui',
                    entries=_build_snapshot_entries(
                        self._settings_cls.get_snapshots(domain='ui')
                    ),
                )
            )
        ]
        daemon_result: IpcRequestResult = self._request_ipc_result(
            GetSettingsListCommand()
        )
        daemon_section: str = self._render_daemon_snapshot_result(
            daemon_result,
            expected_data_event=EventType.SETTINGS_LIST_DATA,
            unavailable_subject='Daemon settings',
        )
        return self._merge_snapshot_sections(
            local_sections,
            daemon_section,
            insert_leading_blank_line=daemon_result.insert_leading_blank_line,
        )

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
            return self._translate_event(
                EventType.CONFIG_DATA,
                {'key': key, 'value': val},
            )

        return self._request_ipc(GetConfigCommand(setting_key=key))

    def handle_config_list(self) -> str:
        """
        Lists effective config values for the active profile.

        Args:
            None

        Returns:
            str: The formatted snapshot output.
        """
        local_sections: list[str] = [
            UIPresenter.format_response(
                ConfigListDataEvent(
                    scope='ui',
                    profile=self._pm.profile_name,
                    entries=_build_snapshot_entries(
                        self._pm.config.get_setting_snapshots(domain='ui')
                    ),
                )
            ),
            UIPresenter.format_response(
                ConfigListDataEvent(
                    scope='profile',
                    profile=self._pm.profile_name,
                    entries=_build_snapshot_entries(
                        self._pm.config.get_profile_snapshots()
                    ),
                )
            ),
        ]
        daemon_result: IpcRequestResult = self._request_ipc_result(
            GetConfigListCommand()
        )
        daemon_section: str = self._render_daemon_snapshot_result(
            daemon_result,
            expected_data_event=EventType.CONFIG_LIST_DATA,
            unavailable_subject='Daemon config values',
        )
        return self._merge_snapshot_sections(
            local_sections,
            daemon_section,
            insert_leading_blank_line=daemon_result.insert_leading_blank_line,
        )

    def handle_config_sync(self) -> str:
        """
        Clears profile overrides and syncs with global defaults.

        Args:
            None

        Returns:
            str: The formatted status message.
        """
        daemon_msg: str = self._request_ipc(SyncConfigCommand())
        success_msg: str = self._translate_event(EventType.CONFIG_SYNCED)

        if not daemon_msg.endswith(success_msg):
            return daemon_msg

        try:
            self._pm.config.sync_with_global(domain='ui')
            local_msg: str = (
                'Profile overrides cleared. Config is now synced with global settings.'
            )
        except Exception:
            return 'Failed to update profile config.'

        if self._is_remote:
            return f'{local_msg}\n{daemon_msg}'

        return daemon_msg
