"""
Module owning the registry for frontend-specific UI settings.

Frontend-owned settings are namespaced as `ui.<frontend>.<key>` and are
registered here by each frontend entry point. The registry lives inside the
data layer so that paradigm-neutral client settings (`client.*`) and daemon
settings (`daemon.*`) never depend on a concrete UI implementation, while no
data-layer module ever imports the UI layer.
"""

from dataclasses import dataclass
from typing import Dict, Literal, Optional, Sequence, Tuple

from metor.data.settings import SettingValue, SettingValidationError


@dataclass(frozen=True)
class UiSettingSpec:
    """Describes one frontend-owned UI setting and its documentation metadata."""

    key: str
    type: Literal['str', 'int', 'float', 'bool']
    default: SettingValue
    description: str
    constraints: str
    category: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None


_REGISTERED_UI_SETTINGS: Dict[str, Dict[str, UiSettingSpec]] = {}


def register_ui_settings(frontend_id: str, specs: Sequence[UiSettingSpec]) -> None:
    """
    Registers one frontend's UI setting specs under its unique namespace id.

    Args:
        frontend_id (str): The unique frontend namespace id (e.g. `terminal`).
        specs (Sequence[UiSettingSpec]): The setting specs to register.

    Raises:
        ValueError: If the frontend id is already registered, or a spec key is
            empty, contains a dot, or duplicates another spec.

    Returns:
        None
    """
    if not frontend_id:
        raise ValueError('frontend_id must not be empty.')
    if frontend_id in _REGISTERED_UI_SETTINGS:
        raise ValueError(
            f"UI settings for frontend '{frontend_id}' are already registered."
        )

    registered: Dict[str, UiSettingSpec] = {}
    for spec in specs:
        if not spec.key:
            raise ValueError(f'UI setting key must not be empty for frontend {frontend_id!r}.')
        if '.' in spec.key:
            raise ValueError(
                f"UI setting key '{spec.key}' must not contain '.' for frontend {frontend_id!r}."
            )
        if spec.key in registered:
            raise ValueError(
                f"Duplicate UI setting key '{spec.key}' for frontend '{frontend_id}'."
            )
        registered[spec.key] = spec

    _REGISTERED_UI_SETTINGS[frontend_id] = registered


def get_ui_setting_spec(frontend_id: str, key: str) -> Optional[UiSettingSpec]:
    """
    Looks up one registered UI setting spec.

    Args:
        frontend_id (str): The frontend namespace id.
        key (str): The unqualified setting key.

    Returns:
        Optional[UiSettingSpec]: The matching spec, or None if unregistered.
    """
    specs: Dict[str, UiSettingSpec] = _REGISTERED_UI_SETTINGS.get(frontend_id, {})
    return specs.get(key)


def get_registered_ui_settings() -> Dict[str, Dict[str, UiSettingSpec]]:
    """
    Returns a defensive snapshot of all registered frontend UI setting specs.

    Args:
        None

    Returns:
        Dict[str, Dict[str, UiSettingSpec]]: Frontend id to key-to-spec mapping.
    """
    return {
        frontend_id: dict(specs)
        for frontend_id, specs in _REGISTERED_UI_SETTINGS.items()
    }


def validate_ui_setting_value(spec: UiSettingSpec, value: SettingValue) -> SettingValue:
    """
    Validates and normalizes one value against a registered UI setting spec.

    Type checks mirror the global Settings validator: bool is strict, int is
    strict, float accepts int and float but never bool, and str is strict plus
    non-empty when the spec's constraints demand it.

    Args:
        spec (UiSettingSpec): The registered spec describing the expected type.
        value (SettingValue): The candidate value.

    Raises:
        TypeError: If the value type is invalid.
        SettingValidationError: If a non-empty string constraint is violated.

    Returns:
        SettingValue: The normalized value.
    """
    if spec.type == 'bool':
        if type(value) is not bool:
            raise TypeError(
                f"Invalid type for '{spec.key}'. Expected bool, got {type(value).__name__}."
            )
        return value

    normalized: SettingValue
    if spec.type == 'int':
        if type(value) is not int:
            raise TypeError(
                f"Invalid type for '{spec.key}'. Expected int, got {type(value).__name__}."
            )
        normalized = value
    elif spec.type == 'float':
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(
                f"Invalid type for '{spec.key}'. Expected float, got {type(value).__name__}."
            )
        normalized = float(value)
    elif spec.type == 'str':
        if type(value) is not str:
            raise TypeError(
                f"Invalid type for '{spec.key}'. Expected str, got {type(value).__name__}."
            )
        if 'non-empty' in spec.constraints.lower() and not value.strip():
            raise SettingValidationError(f"Setting '{spec.key}' must not be empty.")
        normalized = value
    else:
        normalized = value

    if isinstance(normalized, (int, float)) and not isinstance(normalized, bool):
        if spec.min_value is not None and float(normalized) < spec.min_value:
            raise SettingValidationError(
                f"Setting '{spec.key}' must be >= {spec.min_value:g}."
            )
        if spec.max_value is not None and float(normalized) > spec.max_value:
            raise SettingValidationError(
                f"Setting '{spec.key}' must be <= {spec.max_value:g}."
            )

    return normalized


TERMINAL_UI_SETTINGS: Tuple[UiSettingSpec, ...] = (
    UiSettingSpec(
        key='prompt_sign',
        type='str',
        default='$',
        description='Sets the prompt prefix shown in the interactive chat UI.',
        constraints='Non-empty string.',
        category='Terminal UI',
    ),
    UiSettingSpec(
        key='chat_limit',
        type='int',
        default=50,
        description='Limits the number of rendered chat lines kept in volatile UI memory.',
        constraints='Integer >= 1.',
        category='Terminal UI',
        min_value=1,
    ),
    UiSettingSpec(
        key='chat_buffer_padding',
        type='int',
        default=20,
        description='Keeps extra renderer lines around the viewport to reduce redraw churn.',
        constraints='Integer >= 0.',
        category='Terminal UI',
        min_value=0,
    ),
    UiSettingSpec(
        key='inbox_notification_delay',
        type='float',
        default=10.0,
        description='Delays and aggregates unread-message notifications while the peer is unfocused. `0` disables buffering.',
        constraints='Float >= 0 seconds.',
        category='Terminal UI',
        min_value=0,
    ),
    UiSettingSpec(
        key='show_transport_status',
        type='bool',
        default=False,
        description='Shows the current peer transport state in the chat status line.',
        constraints='Boolean.',
        category='Terminal UI',
    ),
)
