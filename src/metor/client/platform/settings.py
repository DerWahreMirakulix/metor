"""Bounded, frontend-neutral descriptors and results for local device settings."""

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Protocol, TypeAlias


DeviceSettingValue: TypeAlias = bool | int | float | str
MAX_DEVICE_SETTINGS = 24
MAX_SETTING_CHOICES = 16
MAX_SETTING_TEXT = 80
MAX_SETTING_ABSOLUTE_NUMBER = 1_000_000_000
_SETTING_ID = re.compile(r'[a-z][a-z0-9_]{0,63}')
_FORBIDDEN_ACTIONS = frozenset({'shutdown', 'poweroff', 'purge', 'erase', 'reset'})


class DeviceSettingKind(str, Enum):
    """Finite value shapes supported by standard frontend controls."""

    BOOLEAN = 'boolean'
    NUMBER = 'number'
    CHOICE = 'choice'


class DeviceSettingStatus(str, Enum):
    """Confirmed readback or an explicit local operation outcome."""

    APPLIED = 'applied'
    UNSUPPORTED = 'unsupported'
    DENIED = 'denied'
    UNAVAILABLE = 'unavailable'
    FAILED = 'failed'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class DeviceSettingDescriptor:
    """Finite metadata for one ordinary device value, never an action command."""

    key: str
    name: str
    kind: DeviceSettingKind
    writable: bool = True
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    unit: str | None = None

    def __post_init__(self) -> None:
        """Reject malformed metadata before it reaches a frontend."""
        if (
            type(self.key) is not str
            or _SETTING_ID.fullmatch(self.key) is None
            or self.key in _FORBIDDEN_ACTIONS
            or type(self.name) is not str
            or not self.name
            or len(self.name) > MAX_SETTING_TEXT
            or not self.name.isprintable()
            or type(self.writable) is not bool
            or not isinstance(self.kind, DeviceSettingKind)
        ):
            raise ValueError('Invalid device setting descriptor')
        if self.unit is not None and (
            type(self.unit) is not str
            or len(self.unit) > MAX_SETTING_TEXT
            or not self.unit.isprintable()
        ):
            raise ValueError('Invalid device setting unit')
        if self.kind is DeviceSettingKind.NUMBER:
            minimum, maximum = self.minimum, self.maximum
            if (
                not isinstance(minimum, (int, float))
                or isinstance(minimum, bool)
                or not isinstance(maximum, (int, float))
                or isinstance(maximum, bool)
                or abs(minimum) > MAX_SETTING_ABSOLUTE_NUMBER
                or abs(maximum) > MAX_SETTING_ABSOLUTE_NUMBER
                or not math.isfinite(minimum)
                or not math.isfinite(maximum)
                or minimum >= maximum
                or self.choices
            ):
                raise ValueError('Invalid device setting range')
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError('Unexpected device setting range')
        if self.kind is DeviceSettingKind.CHOICE:
            if (
                not isinstance(self.choices, tuple)
                or not 1 <= len(self.choices) <= MAX_SETTING_CHOICES
                or len(set(self.choices)) != len(self.choices)
                or any(
                    type(choice) is not str
                    or not choice
                    or len(choice) > MAX_SETTING_TEXT
                    or not choice.isprintable()
                    for choice in self.choices
                )
            ):
                raise ValueError('Invalid device setting choices')
        elif self.choices:
            raise ValueError('Unexpected device setting choices')

    def accepts(self, value: DeviceSettingValue) -> bool:
        """Check the public value shape; the executing adapter checks again."""
        if self.kind is DeviceSettingKind.BOOLEAN:
            return type(value) is bool
        if self.kind is DeviceSettingKind.CHOICE:
            return type(value) is str and value in self.choices
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and abs(value) <= MAX_SETTING_ABSOLUTE_NUMBER
            and math.isfinite(value)
            and self.minimum is not None
            and self.maximum is not None
            and self.minimum <= value <= self.maximum
        )


@dataclass(frozen=True)
class DeviceSettingResult:
    """An applied value is confirmed effective; other outcomes claim no value."""

    status: DeviceSettingStatus
    value: DeviceSettingValue | None = None

    def __post_init__(self) -> None:
        """Keep uncertain results from masquerading as confirmed readback."""
        if not isinstance(self.status, DeviceSettingStatus):
            raise ValueError('Invalid device setting outcome')
        if self.status is not DeviceSettingStatus.APPLIED and self.value is not None:
            raise ValueError('Unconfirmed device setting cannot carry a value')
        if self.status is DeviceSettingStatus.APPLIED and self.value is None:
            raise ValueError('Applied device setting needs an effective value')
        value = self.value
        if value is not None and (
            type(value) not in (bool, int, float, str)
            or (
                isinstance(value, (int, float))
                and abs(value) > MAX_SETTING_ABSOLUTE_NUMBER
            )
            or (isinstance(value, float) and not math.isfinite(value))
            or (
                type(value) is str
                and (len(value) > MAX_SETTING_TEXT or not value.isprintable())
            )
        ):
            raise ValueError('Invalid device setting value')


class HardwareSettingsPort(Protocol):
    """Device-wide values whose readback is the source of truth across frontends."""

    def describe(self) -> tuple[DeviceSettingDescriptor, ...]:
        """Return at most MAX_DEVICE_SETTINGS bounded ordinary descriptors."""
        ...

    def read(self, key: str) -> DeviceSettingResult:
        """Read the current effective value or an explicit failure outcome."""
        ...

    def write(self, key: str, value: DeviceSettingValue) -> DeviceSettingResult:
        """Validate and apply a value, returning confirmed effective readback."""
        ...


def validate_descriptors(
    descriptors: tuple[DeviceSettingDescriptor, ...],
) -> tuple[DeviceSettingDescriptor, ...]:
    """Reject unbounded or duplicate provider metadata before presentation."""
    if (
        not isinstance(descriptors, tuple)
        or len(descriptors) > MAX_DEVICE_SETTINGS
        or any(not isinstance(item, DeviceSettingDescriptor) for item in descriptors)
        or len({item.key for item in descriptors}) != len(descriptors)
    ):
        raise ValueError('Invalid device setting list')
    return descriptors
