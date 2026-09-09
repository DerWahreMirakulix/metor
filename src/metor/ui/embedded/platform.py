"""Injected platform ports for a future hardware-operated frontend."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping, Optional, Protocol, Tuple


class HardwareInputKind(str, Enum):
    """Normalized physical input events."""

    KEY = 'key'
    DPAD = 'dpad'
    CONFIRM = 'confirm'
    BACK = 'back'
    PTT_PRESS = 'ptt_press'
    PTT_RELEASE = 'ptt_release'
    POWER = 'power'
    LOCK = 'lock'


@dataclass(frozen=True)
class HardwareInputEvent:
    """One normalized hardware input event."""

    kind: HardwareInputKind
    value: Optional[str] = None


@dataclass(frozen=True)
class EncodedAudioResult:
    """Bounded encoded-audio result owned by the platform layer."""

    blob_reference: str
    codec: str
    duration_ms: int
    size_bytes: int


@dataclass(frozen=True)
class PlatformCapabilities:
    """Discoverable optional platform features."""

    audio_capture: bool = False
    audio_playback: bool = False
    qr_scanner: bool = False
    haptics: bool = False
    display_control: bool = False
    power_control: bool = False


@dataclass(frozen=True)
class BatteryState:
    """Current device power status."""

    percent: int
    charging: bool


class HardwareInputPort(Protocol):
    """Supplies normalized keyboard, navigation, PTT, and power input."""

    def subscribe(self, callback: Callable[[HardwareInputEvent], None]) -> None: ...


class AudioCapturePort(Protocol):
    """Captures bounded encoded audio without exposing device APIs to Core."""

    def start(self, max_duration_ms: int, max_size_bytes: int) -> None: ...
    def stop(self) -> EncodedAudioResult: ...
    def cancel(self) -> None: ...


class AudioPlaybackPort(Protocol):
    """Controls playback for a platform-resolved blob reference."""

    def play(self, blob_reference: str) -> None: ...
    def pause(self) -> None: ...
    def stop(self) -> None: ...
    def set_volume(self, volume_percent: int) -> None: ...


class QrScannerPort(Protocol):
    """Returns raw scan data; Metor remains responsible for validation."""

    @property
    def available(self) -> bool: ...
    def scan(self) -> bytes: ...
    def cancel(self) -> None: ...


class DisplayPort(Protocol):
    """Exposes display properties and optional power controls."""

    def dimensions(self) -> Tuple[int, int]: ...
    def density(self) -> float: ...
    def set_brightness(self, percent: int) -> None: ...
    def wake(self) -> None: ...
    def sleep(self) -> None: ...


class HapticsPort(Protocol):
    """Requests platform-defined feedback patterns."""

    def pulse(self, pattern: str) -> None: ...


class PowerPort(Protocol):
    """Reports battery state and requests platform lifecycle operations."""

    def battery_state(self) -> BatteryState: ...
    def suspend(self) -> None: ...
    def resume(self) -> None: ...
    def request_shutdown(self) -> None: ...


class LocalUiSettingsStore(Protocol):
    """Stores only device-local ``ui.embedded.*`` preferences."""

    def get(self, key: str) -> object: ...
    def set(self, key: str, value: object) -> None: ...
    def snapshot(self) -> Mapping[str, object]: ...


class ClockPort(Protocol):
    """Provides deterministic monotonic and wall-clock inputs."""

    def monotonic(self) -> float: ...
    def wall_time(self) -> float: ...


class LoggerPort(Protocol):
    """Records metadata-only diagnostics without message payloads."""

    def log(self, code: str, fields: Mapping[str, object]) -> None: ...


@dataclass(frozen=True)
class EmbeddedPlatform:
    """Capability-described collection of injected device ports."""

    capabilities: PlatformCapabilities
    input: HardwareInputPort
    clock: ClockPort
    logger: LoggerPort
    settings: LocalUiSettingsStore
    audio_capture: Optional[AudioCapturePort] = None
    audio_playback: Optional[AudioPlaybackPort] = None
    qr_scanner: Optional[QrScannerPort] = None
    display: Optional[DisplayPort] = None
    haptics: Optional[HapticsPort] = None
    power: Optional[PowerPort] = None
