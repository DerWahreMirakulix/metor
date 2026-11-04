"""Strict integrity validation for persisted profile configuration documents."""

from pathlib import Path
from typing import Dict, cast

from metor.data.settings import (
    SettingKey,
    SettingValue,
    SettingValidationError,
    Settings,
    split_namespace_key,
)
from metor.data.settings_registry import (
    get_ui_setting_spec,
    validate_ui_setting_value,
)

# Local Package Imports
from ..models import (
    ProfileConfigKey,
    ProfileConfigValidationError,
    ProfileConfigValue,
    validate_profile_config_value,
)


def validate_profile_config_values(
    config_file: Path,
    raw_data: Dict[str, ProfileConfigValue],
) -> None:
    """Validates profile-config keys and typed values.

    Args:
        config_file (Path): The persisted profile configuration path.
        raw_data (Dict[str, ProfileConfigValue]): Flattened document content.

    Raises:
        ValueError: If the document contains an unknown key or invalid value.

    Returns:
        None
    """
    for key_str, raw_value in raw_data.items():
        if key_str.startswith('ui.'):
            try:
                frontend_id, spec_key = split_namespace_key(key_str)
            except ValueError as exc:
                raise _unknown_key_error(config_file, key_str) from exc
            spec = get_ui_setting_spec(frontend_id, spec_key)
            if spec is None:
                raise _unknown_key_error(config_file, key_str)
            try:
                validate_ui_setting_value(spec, cast(SettingValue, raw_value))
            except (SettingValidationError, TypeError) as exc:
                raise _invalid_value_error(config_file, key_str, exc) from exc
            continue

        try:
            setting_key: SettingKey = SettingKey(key_str)
        except ValueError:
            try:
                profile_key: ProfileConfigKey = ProfileConfigKey(key_str)
            except ValueError as exc:
                raise _unknown_key_error(config_file, key_str) from exc
            try:
                validate_profile_config_value(profile_key, raw_value)
            except (ProfileConfigValidationError, TypeError) as exc:
                raise _invalid_value_error(config_file, key_str, exc) from exc
            continue

        try:
            Settings.validate_value(
                setting_key,
                cast(SettingValue, raw_value),
                for_profile_override=True,
            )
        except (SettingValidationError, TypeError) as exc:
            raise _invalid_value_error(config_file, key_str, exc) from exc


def _unknown_key_error(config_file: Path, key: str) -> ValueError:
    """Builds the canonical unknown-key integrity error.

    Args:
        config_file (Path): The profile configuration path.
        key (str): The unrecognized configuration key.

    Returns:
        ValueError: The formatted integrity error.
    """
    return ValueError(f"'{config_file.name}' contains an unknown config key '{key}'.")


def _invalid_value_error(
    config_file: Path, key: str, error: TypeError | ValueError
) -> ValueError:
    """Builds the canonical invalid-value integrity error.

    Args:
        config_file (Path): The profile configuration path.
        key (str): The invalid configuration key.
        error (TypeError | ValueError): The underlying validation error.

    Returns:
        ValueError: The formatted integrity error.
    """
    return ValueError(
        f"'{config_file.name}' contains an invalid value for '{key}': {error}"
    )
