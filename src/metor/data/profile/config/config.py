"""
Module managing the profile-specific JSON configuration file.
Provides thread-safe read/write operations and cascading lookups
falling back to global application settings. Enforces strict typing
and automatically handles nested dictionary conversions for dot-notation keys.
Prevents silent overwrites of corrupted JSON configurations.
"""

import json
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, cast

from metor.data.settings import (
    SettingKey,
    SettingSnapshotRow,
    Settings,
    SettingValue,
    SettingValidationError,
    build_snapshot_row,
    matches_setting_domain,
    split_namespace_key,
)
from metor.data.settings_registry import (
    get_registered_ui_settings,
    get_ui_setting_spec,
    validate_ui_setting_value,
)
from metor.utils import FileLock, TypeCaster, validate_json_file

# Local Package Imports
from ..paths import Paths
from ..models import (
    ProfileConfigKey,
    ProfileConfigValue,
    NestedConfigDict,
    PROFILE_CONFIG_SPECS,
    ProfileConfigSpec,
    ProfileSecurityMode,
    ProfileConfigValidationError,
    validate_profile_config_value,
)
from .validation import validate_profile_config_values


class Config:
    """Manages reading and writing to the profile's configuration JSON."""

    _PLAINTEXT_DISABLED_SETTING_KEYS: tuple[SettingKey, ...] = (
        SettingKey.ENABLE_RUNTIME_DB_MIRROR,
    )

    def __init__(self, paths: Paths) -> None:
        """
        Initializes the configuration manager.

        Args:
            paths (Paths): The path resolver.

        Returns:
            None
        """
        self._paths: Paths = paths

    def validate_integrity(self) -> None:
        """
        Validates the JSON syntax of the profile configuration file
        using the generic parser utility.

        Args:
            None

        Raises:
            ValueError: If the file exists but contains a syntax error.

        Returns:
            None
        """
        config_file: Path = self._paths.get_config_file()
        validate_json_file(config_file)
        if not config_file.exists():
            return
        validate_profile_config_values(config_file, self._load_raw_data())

    @staticmethod
    def _flatten_nested_data(
        raw_data: NestedConfigDict,
    ) -> Dict[str, ProfileConfigValue]:
        """
        Flattens one nested config payload to dot-notation keys.

        Args:
            raw_data (NestedConfigDict): The nested JSON-compatible payload.

        Returns:
            Dict[str, ProfileConfigValue]: The flattened key-value mapping.
        """
        flat_data: Dict[str, ProfileConfigValue] = {}
        for k, v in raw_data.items():
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    flat_data[f'{k}.{sub_k}'] = sub_v
            else:
                flat_data[k] = v
        return flat_data

    def _load_raw_data(self) -> Dict[str, ProfileConfigValue]:
        """
        Loads the raw on-disk config payload without applying defaults.

        Args:
            None

        Returns:
            Dict[str, ProfileConfigValue]: The flattened raw config mapping.
        """
        config_file: Path = self._paths.get_config_file()
        if not config_file.exists():
            return {}

        with config_file.open('r', encoding='utf-8') as f:
            raw_data: object = json.load(f)

        if not isinstance(raw_data, dict):
            raise ValueError(
                f"'{config_file.name}' must contain a top-level JSON object."
            )

        return self._flatten_nested_data(cast(NestedConfigDict, raw_data))

    def get_setting_snapshots(
        self,
        *,
        domain: Optional[str] = None,
    ) -> Tuple[SettingSnapshotRow, ...]:
        """
        Returns structured snapshots for effective cascading settings.

        Args:
            domain (Optional[str]): Optional `ui` or `daemon` domain filter. The
                `ui` domain covers paradigm-neutral `client.*` keys and all
                registered frontend namespace keys.

        Returns:
            Tuple[SettingSnapshotRow, ...]: Ordered snapshot rows for CLI presentation.
        """
        raw_data: Dict[str, ProfileConfigValue] = self._load_raw_data()
        security_mode: ProfileSecurityMode = self._get_profile_security_mode(raw_data)
        snapshots: list[SettingSnapshotRow] = []

        for spec in Settings.get_specs():
            key_domain: str
            _sub_key: str
            key_domain, _sub_key = spec.key.value.split('.', 1)
            if not matches_setting_domain(key_domain, domain):
                continue

            source: str = 'global'
            if spec.key.value in raw_data:
                normalized_value = Settings.validate_value(
                    spec.key,
                    cast(SettingValue, raw_data[spec.key.value]),
                    for_profile_override=True,
                )
                source = 'profile_override'
            else:
                normalized_value = cast(SettingValue, Settings.get(spec.key))
                if normalized_value is None:
                    normalized_value = spec.default

            effective_value: SettingValue = self._apply_profile_security_mode(
                spec.key,
                normalized_value,
                security_mode,
            )
            if (
                security_mode is ProfileSecurityMode.PLAINTEXT
                and spec.key in self._PLAINTEXT_DISABLED_SETTING_KEYS
            ):
                source = 'plaintext_forced'

            category: str = 'client' if key_domain == 'client' else spec.category
            snapshots.append(
                build_snapshot_row(
                    key=spec.key.value,
                    value=effective_value,
                    source=source,
                    category=category,
                )
            )

        if domain in (None, 'ui'):
            for frontend_id, registered_specs in get_registered_ui_settings().items():
                for ui_spec in registered_specs.values():
                    full_key: str = f'ui.{frontend_id}.{ui_spec.key}'
                    source = 'global'
                    if full_key in raw_data:
                        normalized_value = validate_ui_setting_value(
                            ui_spec,
                            cast(SettingValue, raw_data[full_key]),
                        )
                        source = 'profile_override'
                    else:
                        normalized_value = Settings.get_namespace_value(full_key)

                    snapshots.append(
                        build_snapshot_row(
                            key=full_key,
                            value=normalized_value,
                            source=source,
                            category=f'ui.{frontend_id}',
                        )
                    )

        return tuple(snapshots)

    def get_profile_snapshots(self) -> Tuple[SettingSnapshotRow, ...]:
        """
        Returns structured snapshots for structural profile config keys.

        Args:
            None

        Returns:
            Tuple[SettingSnapshotRow, ...]: Ordered structural config snapshot rows.
        """
        raw_data: Dict[str, ProfileConfigValue] = self._load_raw_data()
        snapshots: list[SettingSnapshotRow] = []

        for spec in PROFILE_CONFIG_SPECS.values():
            if spec.key.value in raw_data:
                value: ProfileConfigValue = validate_profile_config_value(
                    spec.key,
                    raw_data[spec.key.value],
                )
                source: str = 'profile'
            else:
                value = spec.default
                source = 'default'

            snapshots.append(
                build_snapshot_row(
                    key=spec.key.value,
                    value=value,
                    source=source,
                    category='Structural Profile Config',
                )
            )

        return tuple(snapshots)

    def _write_nested(self, data: Dict[str, ProfileConfigValue]) -> None:
        """
        Internal helper to convert flat dot-notation dictionaries into nested
        structures and write them to disk. Assumes the caller has acquired a lock.

        Args:
            data (Dict[str, ProfileConfigValue]): The flat dictionary.

        Returns:
            None
        """
        nested_data: NestedConfigDict = {}
        for k, v in data.items():
            if '.' in k:
                domain, subkey = k.split('.', 1)
                if domain not in nested_data:
                    nested_data[domain] = {}

                domain_dict = nested_data[domain]
                if isinstance(domain_dict, dict):
                    domain_dict[subkey] = v
            else:
                nested_data[k] = v

        config_file: Path = self._paths.get_config_file()
        with config_file.open('w', encoding='utf-8') as f:
            json.dump(nested_data, f, indent=4)

    def _load(
        self,
        *,
        persist_defaults: bool = True,
    ) -> Dict[str, ProfileConfigValue]:
        """
        Loads the JSON configuration from disk safely. Generates default config if missing.
        Flattens nested dictionary structures into dot-notation keys.
        Prevents overwriting the file if a JSONDecodeError occurs on an existing file.

        Args:
            None

        Returns:
            Dict[str, ProfileConfigValue]: The loaded configuration data as a flat dictionary.
        """
        config_file: Path = self._paths.get_config_file()
        if config_file.exists():
            try:
                return self._load_raw_data()
            except (json.JSONDecodeError, IOError):
                pass

        default_data: Dict[str, ProfileConfigValue] = {
            spec.key.value: spec.default for spec in PROFILE_CONFIG_SPECS.values()
        }

        if persist_defaults and self._paths.exists() and not config_file.exists():
            try:
                with FileLock(config_file):
                    self._write_nested(default_data)
            except IOError:
                pass

        return default_data

    def _get_profile_security_mode(
        self,
        data: Dict[str, ProfileConfigValue],
    ) -> ProfileSecurityMode:
        """
        Resolves the effective structural profile security mode from raw config data.

        Args:
            data (Dict[str, ProfileConfigValue]): The raw flat config dictionary.

        Returns:
            ProfileSecurityMode: The normalized profile security mode.
        """
        spec: ProfileConfigSpec = PROFILE_CONFIG_SPECS[ProfileConfigKey.SECURITY_MODE]
        raw_value: ProfileConfigValue = data.get(spec.key.value, spec.default)

        try:
            normalized = validate_profile_config_value(
                ProfileConfigKey.SECURITY_MODE,
                raw_value,
            )
            return ProfileSecurityMode(str(normalized))
        except (ProfileConfigValidationError, TypeError, ValueError):
            return ProfileSecurityMode.ENCRYPTED

    def get_profile_security_mode(self) -> ProfileSecurityMode:
        """
        Returns the effective structural storage security mode for this profile.

        Args:
            None

        Returns:
            ProfileSecurityMode: The resolved storage security mode.
        """
        return self._get_profile_security_mode(self._load())

    def _apply_profile_security_mode(
        self,
        key: SettingKey,
        value: SettingValue,
        security_mode: ProfileSecurityMode,
    ) -> SettingValue:
        """
        Applies profile-mode-specific behavior to one resolved setting value.

        Args:
            key (SettingKey): The setting key.
            value (SettingValue): The resolved setting value.
            security_mode (ProfileSecurityMode): The effective profile security mode.

        Returns:
            SettingValue: The effective value for this profile.
        """
        if (
            security_mode is ProfileSecurityMode.PLAINTEXT
            and key in self._PLAINTEXT_DISABLED_SETTING_KEYS
        ):
            return False

        return value

    def get(
        self,
        key: Union[ProfileConfigKey, SettingKey, str],
        default: ProfileConfigValue = None,
    ) -> Union[ProfileConfigValue, SettingValue]:
        """
        Retrieves a setting, cascading from local config to global defaults.

        Args:
            key (Union[ProfileConfigKey, SettingKey, str]): The setting to retrieve.
            default (ProfileConfigValue): Fallback value.

        Returns:
            Union[ProfileConfigValue, SettingValue]: The resolved configuration value.
        """
        key_str: str = key.value if isinstance(key, Enum) else key
        data: Dict[str, ProfileConfigValue] = self._load()
        security_mode: ProfileSecurityMode = self._get_profile_security_mode(data)

        if key_str in data:
            local_value: ProfileConfigValue = data[key_str]

            try:
                setting_key: SettingKey = SettingKey(key_str)
                normalized_setting = Settings.validate_value(
                    setting_key,
                    cast(SettingValue, local_value),
                    for_profile_override=True,
                )
                return self._apply_profile_security_mode(
                    setting_key,
                    normalized_setting,
                    security_mode,
                )
            except ValueError:
                pass
            except TypeError:
                return default

            try:
                profile_key: ProfileConfigKey = ProfileConfigKey(key_str)
                return validate_profile_config_value(profile_key, local_value)
            except ValueError:
                return local_value
            except (ProfileConfigValidationError, TypeError):
                return default

        try:
            global_key: SettingKey = SettingKey(key_str)
            global_value = Settings.get(global_key)
            if global_value is None:
                return default
            return self._apply_profile_security_mode(
                global_key,
                global_value,
                security_mode,
            )
        except ValueError:
            pass

        return default

    def get_str(
        self,
        key: Union[ProfileConfigKey, SettingKey, str],
        default: str = '',
    ) -> str:
        """
        Retrieves a setting and guarantees a string return type.

        Args:
            key (Union[ProfileConfigKey, SettingKey, str]): The setting to retrieve.
            default (str): Fallback string value.

        Returns:
            str: The resolved configuration value as a string.
        """
        value: Union[ProfileConfigValue, SettingValue] = self.get(key, default)
        return TypeCaster.to_str(value)

    def get_int(
        self,
        key: Union[ProfileConfigKey, SettingKey, str],
        default: int = 0,
    ) -> int:
        """
        Retrieves a setting and safely coerces it into an integer.

        Args:
            key (Union[ProfileConfigKey, SettingKey, str]): The setting to retrieve.
            default (int): Fallback integer value.

        Returns:
            int: The resolved configuration value as an integer.
        """
        value: Union[ProfileConfigValue, SettingValue] = self.get(key, default)
        return TypeCaster.to_int(value)

    def get_float(
        self,
        key: Union[ProfileConfigKey, SettingKey, str],
        default: float = 0.0,
    ) -> float:
        """
        Retrieves a setting and safely coerces it into a float.

        Args:
            key (Union[ProfileConfigKey, SettingKey, str]): The setting to retrieve.
            default (float): Fallback float value.

        Returns:
            float: The resolved configuration value as a float.
        """
        value: Union[ProfileConfigValue, SettingValue] = self.get(key, default)
        return TypeCaster.to_float(value)

    def get_bool(
        self,
        key: Union[ProfileConfigKey, SettingKey, str],
        default: bool = False,
    ) -> bool:
        """
        Retrieves a setting and safely coerces it into a boolean.

        Args:
            key (Union[ProfileConfigKey, SettingKey, str]): The setting to retrieve.
            default (bool): Fallback boolean value.

        Returns:
            bool: The resolved configuration value as a boolean.
        """
        value: Union[ProfileConfigValue, SettingValue] = self.get(key, default)
        return TypeCaster.to_bool(value)

    def set(
        self,
        key: Union[ProfileConfigKey, SettingKey, str],
        value: ProfileConfigValue,
        *,
        allow_mutating_structural_keys: bool = False,
    ) -> None:
        """
        Writes a setting safely using a file lock, applying nested formatting.
        Implies directory creation if a setting is deliberately saved.

        Args:
            key (Union[ProfileConfigKey, SettingKey, str]): The setting to save.
            value (ProfileConfigValue): The value to persist.

        Returns:
            None
        """
        if not self._paths.exists():
            self._paths.create_directories()

        key_str: str = key.value if isinstance(key, Enum) else key
        normalized_value: ProfileConfigValue
        data: Dict[str, ProfileConfigValue] = self._load()
        security_mode: ProfileSecurityMode = self._get_profile_security_mode(data)

        try:
            setting_key: SettingKey = SettingKey(key_str)
        except ValueError:
            try:
                profile_key: ProfileConfigKey = ProfileConfigKey(key_str)
                normalized_value = validate_profile_config_value(profile_key, value)
                spec: ProfileConfigSpec = PROFILE_CONFIG_SPECS[profile_key]
                if (
                    not spec.mutable_after_creation
                    and not allow_mutating_structural_keys
                ):
                    current_value: ProfileConfigValue = data.get(key_str, spec.default)
                    try:
                        normalized_current = validate_profile_config_value(
                            profile_key,
                            current_value,
                        )
                    except (ProfileConfigValidationError, TypeError):
                        normalized_current = spec.default

                    if normalized_current != normalized_value:
                        raise ProfileConfigValidationError(
                            f"Setting '{key_str}' is immutable after profile creation. Use the dedicated profile migration workflow instead."
                        )
            except ValueError as exc:
                raise ValueError(f"Invalid configuration key '{key_str}'.") from exc
        else:
            normalized_value = Settings.validate_value(
                setting_key,
                cast(SettingValue, value),
                for_profile_override=True,
            )
            if (
                security_mode is ProfileSecurityMode.PLAINTEXT
                and setting_key in self._PLAINTEXT_DISABLED_SETTING_KEYS
                and normalized_value is True
            ):
                raise SettingValidationError(
                    f"Setting '{key_str}' is not supported for plaintext profiles."
                )

        config_file: Path = self._paths.get_config_file()

        with FileLock(config_file):
            data = self._load(persist_defaults=False)
            data[key_str] = normalized_value
            self._write_nested(data)

    def set_namespace(self, key: str, value: SettingValue) -> None:
        """
        Validates and persists one registered frontend namespace override.

        Namespace keys follow the `ui.<frontend>.<key>` shape and are validated
        against the registry owned by the data layer.

        Args:
            key (str): The `ui.<frontend>.<key>` namespace key.
            value (SettingValue): The new value for the override.

        Raises:
            ValueError: If the key is not a registered namespace key.

        Returns:
            None
        """
        frontend_id: str
        setting_key: str
        frontend_id, setting_key = split_namespace_key(key)
        spec = get_ui_setting_spec(frontend_id, setting_key)
        if spec is None:
            raise ValueError(f"Unknown namespace setting '{key}'.")

        normalized_value: SettingValue = validate_ui_setting_value(spec, value)

        if not self._paths.exists():
            self._paths.create_directories()

        config_file: Path = self._paths.get_config_file()

        with FileLock(config_file):
            data = self._load(persist_defaults=False)
            data[key] = normalized_value
            self._write_nested(data)

    def get_namespace_value(self, key: str) -> SettingValue:
        """
        Retrieves a registered frontend namespace override with global fallback.

        Args:
            key (str): The `ui.<frontend>.<key>` namespace key.

        Raises:
            ValueError: If the key is not a registered namespace key.

        Returns:
            SettingValue: The effective cascading value.
        """
        frontend_id: str
        setting_key: str
        frontend_id, setting_key = split_namespace_key(key)
        spec = get_ui_setting_spec(frontend_id, setting_key)
        if spec is None:
            raise ValueError(f"Unknown namespace setting '{key}'.")

        data: Dict[str, ProfileConfigValue] = self._load()
        if key in data:
            local_value: ProfileConfigValue = data[key]
            try:
                return validate_ui_setting_value(
                    spec,
                    cast(SettingValue, local_value),
                )
            except (TypeError, SettingValidationError):
                return spec.default

        return Settings.get_namespace_value(key)

    def get_namespace_str(self, key: str) -> str:
        """
        Retrieves a namespace override and guarantees a string return type.

        Args:
            key (str): The `ui.<frontend>.<key>` namespace key.

        Returns:
            str: The resolved namespace value as a string.
        """
        return TypeCaster.to_str(self.get_namespace_value(key))

    def get_namespace_int(self, key: str) -> int:
        """
        Retrieves a namespace override and safely coerces it into an integer.

        Args:
            key (str): The `ui.<frontend>.<key>` namespace key.

        Returns:
            int: The resolved namespace value as an integer.
        """
        return TypeCaster.to_int(self.get_namespace_value(key))

    def get_namespace_float(self, key: str) -> float:
        """
        Retrieves a namespace override and safely coerces it into a float.

        Args:
            key (str): The `ui.<frontend>.<key>` namespace key.

        Returns:
            float: The resolved namespace value as a float.
        """
        return TypeCaster.to_float(self.get_namespace_value(key))

    def get_namespace_bool(self, key: str) -> bool:
        """
        Retrieves a namespace override and safely coerces it into a boolean.

        Args:
            key (str): The `ui.<frontend>.<key>` namespace key.

        Returns:
            bool: The resolved namespace value as a boolean.
        """
        return TypeCaster.to_bool(self.get_namespace_value(key))

    def sync_with_global(self, *, domain: Optional[str] = None) -> None:
        """
        Wipes all SettingKey overrides from the local config, forcing a fallback to global Settings.
        Retains pure ProfileConfigKey data (like DAEMON_PORT).

        Args:
            domain (Optional[str]): Optional `ui` or `daemon` domain filter. The
                `ui` domain wipes `client.`- and `ui.`-prefixed keys.

        Returns:
            None
        """
        if domain not in (None, 'ui', 'daemon'):
            raise ValueError("domain must be None, 'ui', or 'daemon'.")

        if not self._paths.exists():
            return

        config_file: Path = self._paths.get_config_file()
        if not config_file.exists():
            return

        with FileLock(config_file):
            data: Dict[str, ProfileConfigValue] = self._load()
            keys_to_remove: List[str] = []

            for k in data.keys():
                key_domain: str = k.split('.', 1)[0]
                if domain == 'ui':
                    if key_domain not in ('client', 'ui'):
                        continue
                elif domain == 'daemon':
                    if key_domain != 'daemon':
                        continue
                else:
                    if key_domain not in ('client', 'ui', 'daemon'):
                        continue
                keys_to_remove.append(k)

            for k in keys_to_remove:
                del data[k]

            self._write_nested(data)
