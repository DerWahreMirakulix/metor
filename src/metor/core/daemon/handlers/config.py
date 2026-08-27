"""
Module defining the ConfigCommandHandler.
Encapsulates operations routing global settings and profile configurations.
Enforces the Zero-Text Policy by eliminating raw string errors from DTOs.
"""

from typing import Iterable

from metor.core.api import (
    EventType,
    IpcCommand,
    IpcEvent,
    JsonValue,
    create_event,
    SetSettingCommand,
    GetSettingCommand,
    GetSettingsListCommand,
    SetConfigCommand,
    GetConfigCommand,
    GetConfigListCommand,
    SyncConfigCommand,
)
from metor.data import (
    DAEMON_SETTING_KEYS,
    Settings,
    SettingKey,
    SettingSnapshotRow,
    SettingValidationError,
)
from metor.data.profile import (
    ProfileManager,
    ProfileConfigValidationError,
)


def _snapshot_rows_to_json(
    rows: Iterable[SettingSnapshotRow],
) -> list[JsonValue]:
    """
    Converts internal snapshot rows into strict JSON payload values.

    Args:
        rows (Iterable[SettingSnapshotRow]): The snapshot rows.

    Returns:
        list[JsonValue]: JSON-safe dictionaries for IPC event payloads.
    """
    json_rows: list[JsonValue] = []
    for row in rows:
        payload_row: dict[str, JsonValue] = {
            'key': row['key'],
            'value': row['value'],
            'source': row['source'],
            'category': row['category'],
        }
        json_rows.append(payload_row)

    return json_rows


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
            key_str = cmd.setting_key
            if not key_str.startswith('daemon.'):
                return create_event(
                    EventType.CLIENT_SCOPE_KEY_REJECTED,
                    {'key': key_str},
                )
            if key_str not in DAEMON_SETTING_KEYS:
                return create_event(EventType.INVALID_SETTING_KEY)

            setting_key = SettingKey(key_str)  # guaranteed valid

            try:
                Settings.set(setting_key, cmd.setting_value)
                return create_event(
                    EventType.SETTING_UPDATED,
                    {'key': cmd.setting_key},
                )
            except (TypeError, SettingValidationError) as exc:
                return create_event(
                    EventType.SETTING_TYPE_ERROR,
                    {'key': cmd.setting_key, 'reason': str(exc)},
                )
            except Exception:
                return create_event(EventType.SETTING_UPDATE_FAILED)

        if isinstance(cmd, GetSettingCommand):
            key_str = cmd.setting_key
            if not key_str.startswith('daemon.'):
                return create_event(
                    EventType.CLIENT_SCOPE_KEY_REJECTED,
                    {'key': key_str},
                )
            if key_str not in DAEMON_SETTING_KEYS:
                return create_event(EventType.INVALID_SETTING_KEY)

            setting_key = SettingKey(key_str)  # guaranteed valid

            try:
                val: str = Settings.get_str(setting_key)
                return create_event(
                    EventType.SETTING_DATA,
                    {'key': cmd.setting_key, 'value': val},
                )
            except ValueError:
                return create_event(EventType.INVALID_SETTING_KEY)

        if isinstance(cmd, GetSettingsListCommand):
            return create_event(
                EventType.SETTINGS_LIST_DATA,
                {
                    'scope': 'daemon',
                    'entries': _snapshot_rows_to_json(
                        Settings.get_snapshots(domain='daemon')
                    ),
                },
            )

        if isinstance(cmd, SetConfigCommand):
            key_str = cmd.setting_key
            if key_str.startswith('daemon.') and key_str in DAEMON_SETTING_KEYS:
                set_config_key: SettingKey = SettingKey(key_str)
            else:
                return create_event(
                    EventType.CLIENT_SCOPE_KEY_REJECTED,
                    {'key': key_str},
                )

            try:
                self._pm.config.set(set_config_key, cmd.setting_value)
                return create_event(
                    EventType.CONFIG_UPDATED,
                    {'key': cmd.setting_key},
                )
            except (
                TypeError,
                SettingValidationError,
                ProfileConfigValidationError,
            ) as exc:
                return create_event(
                    EventType.SETTING_TYPE_ERROR,
                    {'key': cmd.setting_key, 'reason': str(exc)},
                )
            except Exception:
                return create_event(EventType.CONFIG_UPDATE_FAILED)

        if isinstance(cmd, GetConfigCommand):
            key_str = cmd.setting_key
            if key_str.startswith('daemon.') and key_str in DAEMON_SETTING_KEYS:
                get_config_key: SettingKey = SettingKey(key_str)
            else:
                return create_event(
                    EventType.CLIENT_SCOPE_KEY_REJECTED,
                    {'key': key_str},
                )

            try:
                val = self._pm.config.get_str(get_config_key)
                return create_event(
                    EventType.CONFIG_DATA,
                    {'key': cmd.setting_key, 'value': val},
                )
            except ValueError:
                return create_event(EventType.INVALID_CONFIG_KEY)

        if isinstance(cmd, GetConfigListCommand):
            return create_event(
                EventType.CONFIG_LIST_DATA,
                {
                    'scope': 'daemon',
                    'profile': self._pm.profile_name,
                    'entries': _snapshot_rows_to_json(
                        self._pm.config.get_setting_snapshots(domain='daemon')
                    ),
                },
            )

        if isinstance(cmd, SyncConfigCommand):
            try:
                self._pm.config.sync_with_global(domain='daemon')
                return create_event(EventType.CONFIG_SYNCED)
            except Exception:
                return create_event(EventType.CONFIG_UPDATE_FAILED)

        return create_event(EventType.UNKNOWN_COMMAND)
