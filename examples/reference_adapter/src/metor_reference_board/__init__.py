"""Harmless installed adapter example with a shared simulated brightness value."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
from pathlib import Path
import threading
import time

from metor.client.platform import (
    AdapterParameter,
    ButtonSample,
    DeviceSettingDescriptor,
    DeviceSettingKind,
    DeviceSettingResult,
    DeviceSettingStatus,
    DeviceSettingValue,
    PlatformBindings,
)
from metor.utils import (
    FileLock,
    create_private_directory_tree,
    open_private_binary_file,
)


ADAPTER_ID = 'reference-board'
STATE_FILE = 'brightness.txt'
DEFAULT_BRIGHTNESS = 50
MIN_BRIGHTNESS = 0
MAX_BRIGHTNESS = 100
STATE_MAX_BYTES = 32
BRIGHTNESS = DeviceSettingDescriptor(
    'brightness',
    'Simulated brightness',
    DeviceSettingKind.NUMBER,
    minimum=MIN_BRIGHTNESS,
    maximum=MAX_BRIGHTNESS,
    unit='%',
)


class _Subscription:
    """Owns one inert input subscription with no device callbacks."""

    def close(self) -> None:
        """No physical resource exists to release."""


class _Inputs:
    """Emits an initial released sample and never synthesizes button presses."""

    def subscribe(self, receive: Callable[[ButtonSample], None]) -> _Subscription:
        """Initialize released controls without activating input hardware."""
        receive(ButtonSample(0, time.monotonic(), ptt=False, power=False))
        return _Subscription()


@dataclass(frozen=True)
class _Plan:
    """Validated initial simulated value; no resource is held yet."""

    initial_brightness: int

    @property
    def resource_id(self) -> str:
        """Name the shared simulated board independently of a profile."""
        return 'reference_board'

    @property
    def exclusive(self) -> bool:
        """Allow concurrent frontends to read one shared simulated value."""
        return False

    @property
    def capabilities(self) -> frozenset[str]:
        """Declare only inert input and ordinary shared settings."""
        return frozenset({'input', 'settings'})

    def open(self) -> '_Session':
        """Create private simulated state, preserving a value from another GUI."""
        root = Path.home() / '.metor-reference-board'
        create_private_directory_tree(root, ())
        session = _Session(root / STATE_FILE)
        session._initialize(self.initial_brightness)
        return session


class _Session:
    """Shares one nonsecret simulated value across local frontend processes."""

    def __init__(self, state_path: Path) -> None:
        """Retain the device-wide state path, independent of a Metor profile."""
        self._state_path = state_path
        self._guard = threading.Lock()
        self._closed = False
        self._bindings = PlatformBindings(ADAPTER_ID, _Inputs(), settings=self)

    @property
    def bindings(self) -> PlatformBindings:
        """Expose only the no-op input and simulated settings ports."""
        return self._bindings

    def _initialize(self, initial: int) -> None:
        """Seed a missing state file once under the cross-process lock."""
        with FileLock(self._state_path):
            if not self._state_path.exists():
                self._save(initial)
            else:
                self._load()

    def _load(self) -> float:
        """Read a finite bounded decimal value from the shared simulation."""
        with self._state_path.open('rb') as source:
            payload = source.read(STATE_MAX_BYTES + 1)
        if len(payload) > STATE_MAX_BYTES or not payload.endswith(b'\n'):
            raise ValueError('Invalid simulated brightness state')
        value = float(payload[:-1].decode('ascii'))
        if not math.isfinite(value) or not MIN_BRIGHTNESS <= value <= MAX_BRIGHTNESS:
            raise ValueError('Invalid simulated brightness state')
        return value

    def _save(self, value: int | float) -> None:
        """Replace the private bounded value while a cross-process lock is held."""
        with open_private_binary_file(self._state_path) as target:
            target.write(f'{value}\n'.encode('ascii'))

    def describe(self) -> tuple[DeviceSettingDescriptor, ...]:
        """Return one finite ordinary setting with no power or purge controls."""
        return (BRIGHTNESS,)

    def read(self, key: str) -> DeviceSettingResult:
        """Read the shared effective value, reporting unavailable or failed state."""
        if key != BRIGHTNESS.key:
            return DeviceSettingResult(DeviceSettingStatus.UNSUPPORTED)
        with self._guard:
            if self._closed:
                return DeviceSettingResult(DeviceSettingStatus.UNAVAILABLE)
            try:
                with FileLock(self._state_path):
                    value = self._load()
            except (OSError, TimeoutError, ValueError):
                return DeviceSettingResult(DeviceSettingStatus.FAILED)
        return DeviceSettingResult(DeviceSettingStatus.APPLIED, value)

    def write(self, key: str, value: DeviceSettingValue) -> DeviceSettingResult:
        """Validate independently and confirm the effective shared value."""
        if key != BRIGHTNESS.key:
            return DeviceSettingResult(DeviceSettingStatus.UNSUPPORTED)
        if not BRIGHTNESS.accepts(value) or not isinstance(value, (int, float)):
            return DeviceSettingResult(DeviceSettingStatus.DENIED)
        with self._guard:
            if self._closed:
                return DeviceSettingResult(DeviceSettingStatus.UNAVAILABLE)
            try:
                with FileLock(self._state_path):
                    self._save(value)
                    effective = self._load()
            except (OSError, TimeoutError, ValueError):
                return DeviceSettingResult(DeviceSettingStatus.UNKNOWN)
        return DeviceSettingResult(DeviceSettingStatus.APPLIED, effective)

    def close(self) -> None:
        """Revoke this session without deleting other frontends' shared state."""
        with self._guard:
            self._closed = True


class _Factory:
    """Trusted example factory imported only after explicit ID selection."""

    adapter_id = ADAPTER_ID
    contract_version = 1

    def prepare(self, parameters: Mapping[str, AdapterParameter]) -> _Plan:
        """Validate exact deployment fields before opening simulation state."""
        if set(parameters) - {'initial_brightness'}:
            raise ValueError('Unknown reference adapter parameter')
        value = parameters.get('initial_brightness', DEFAULT_BRIGHTNESS)
        if type(value) is not int or not MIN_BRIGHTNESS <= value <= MAX_BRIGHTNESS:
            raise ValueError('Invalid initial simulated brightness')
        return _Plan(value)


provider = _Factory()
