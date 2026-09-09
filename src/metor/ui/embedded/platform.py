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
class AudioPlaybackState:
    """Current playback progress and output route."""

    position_ms: int
    duration_ms: int
    route: str
    volume_percent: int


class QrScannerStatus(str, Enum):
    """Permission-aware QR scanner states."""

    UNAVAILABLE = 'unavailable'
    PERMISSION_REQUIRED = 'permission_required'
    READY = 'ready'
    SCANNING = 'scanning'


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

    def subscribe(self, callback: Callable[[HardwareInputEvent], None]) -> None:
        """Registers a normalized hardware-event consumer.

        Args:
            callback (Callable): Event receiver.

        Returns:
            None
        """
        ...


class AudioCapturePort(Protocol):
    """Captures bounded encoded audio without exposing device APIs to Core."""

    def start(self, max_duration_ms: int, max_size_bytes: int) -> None:
        """Starts a bounded encoded-audio capture.

        Args:
            max_duration_ms (int): Maximum capture duration.
            max_size_bytes (int): Maximum encoded result size.

        Returns:
            None
        """
        ...

    def stop(self) -> EncodedAudioResult:
        """Stops capture and returns the encoded result.

        Args:
            None

        Returns:
            EncodedAudioResult: Captured blob metadata.
        """
        ...

    def cancel(self) -> None:
        """Cancels capture without producing content.

        Args:
            None

        Returns:
            None
        """
        ...


class AudioPlaybackPort(Protocol):
    """Controls playback for a platform-resolved blob reference."""

    def play(self, blob_reference: str) -> None:
        """Starts playback of a platform-resolved blob.

        Args:
            blob_reference (str): Opaque authenticated blob reference.

        Returns:
            None
        """
        ...

    def pause(self) -> None:
        """Pauses active playback.

        Args:
            None

        Returns:
            None
        """
        ...

    def stop(self) -> None:
        """Stops playback and clears its transient state.

        Args:
            None

        Returns:
            None
        """
        ...

    def state(self) -> AudioPlaybackState:
        """Returns current playback progress and routing.

        Args:
            None

        Returns:
            AudioPlaybackState: Current playback state.
        """
        ...

    def set_route(self, route: str) -> None:
        """Selects a platform-defined output route.

        Args:
            route (str): Stable platform route identifier.

        Returns:
            None
        """
        ...

    def set_volume(self, volume_percent: int) -> None:
        """Sets playback volume as a percentage.

        Args:
            volume_percent (int): Volume from zero through one hundred.

        Returns:
            None
        """
        ...


class QrScannerPort(Protocol):
    """Returns raw scan data; Metor remains responsible for validation."""

    @property
    def available(self) -> bool:
        """Reports whether scanner hardware is available.

        Args:
            None

        Returns:
            bool: True when scanning can be supported.
        """
        ...

    def status(self) -> QrScannerStatus:
        """Returns availability and permission state.

        Args:
            None

        Returns:
            QrScannerStatus: Current scanner state.
        """
        ...

    def request_permission(self) -> bool:
        """Requests any platform camera permission.

        Args:
            None

        Returns:
            bool: True when permission is available afterward.
        """
        ...

    def scan(self) -> bytes:
        """Scans one untrusted raw payload.

        Args:
            None

        Returns:
            bytes: Raw data for Metor-side validation.
        """
        ...

    def cancel(self) -> None:
        """Cancels an active scan.

        Args:
            None

        Returns:
            None
        """
        ...


class DisplayPort(Protocol):
    """Exposes display properties and optional power controls."""

    def dimensions(self) -> Tuple[int, int]:
        """Returns the physical display dimensions in pixels.

        Args:
            None

        Returns:
            Tuple[int, int]: Width and height.
        """
        ...

    def density(self) -> float:
        """Returns the display density scale.

        Args:
            None

        Returns:
            float: Platform density multiplier.
        """
        ...

    def set_brightness(self, percent: int) -> None:
        """Sets display brightness as a percentage.

        Args:
            percent (int): Brightness from zero through one hundred.

        Returns:
            None
        """
        ...

    def wake(self) -> None:
        """Requests that the display wake.

        Args:
            None

        Returns:
            None
        """
        ...

    def sleep(self) -> None:
        """Requests that the display sleep.

        Args:
            None

        Returns:
            None
        """
        ...


class HapticsPort(Protocol):
    """Requests platform-defined feedback patterns."""

    def pulse(self, pattern: str) -> None:
        """Requests one platform-defined haptic pattern.

        Args:
            pattern (str): Stable feedback pattern identifier.

        Returns:
            None
        """
        ...


class PowerPort(Protocol):
    """Reports battery state and requests platform lifecycle operations."""

    def battery_state(self) -> BatteryState:
        """Returns current battery and charging state.

        Args:
            None

        Returns:
            BatteryState: Current power status.
        """
        ...

    def suspend(self) -> None:
        """Requests platform suspension.

        Args:
            None

        Returns:
            None
        """
        ...

    def resume(self) -> None:
        """Requests platform resumption.

        Args:
            None

        Returns:
            None
        """
        ...

    def request_shutdown(self) -> None:
        """Requests an orderly platform shutdown.

        Args:
            None

        Returns:
            None
        """
        ...


class LocalUiSettingsStore(Protocol):
    """Stores only device-local ``ui.embedded.*`` preferences."""

    def get(self, key: str) -> object:
        """Returns a device-local embedded setting.

        Args:
            key (str): Namespaced setting key.

        Returns:
            object: Stored setting value.
        """
        ...

    def set(self, key: str, value: object) -> None:
        """Stores a device-local embedded setting.

        Args:
            key (str): Namespaced setting key.
            value (object): Setting value.

        Returns:
            None
        """
        ...

    def snapshot(self) -> Mapping[str, object]:
        """Returns a detached local settings snapshot.

        Args:
            None

        Returns:
            Mapping[str, object]: Current local settings.
        """
        ...


class ClockPort(Protocol):
    """Provides deterministic monotonic and wall-clock inputs."""

    def monotonic(self) -> float:
        """Returns monotonic time for durations.

        Args:
            None

        Returns:
            float: Monotonic seconds.
        """
        ...

    def wall_time(self) -> float:
        """Returns wall-clock time for display formatting.

        Args:
            None

        Returns:
            float: Wall-clock timestamp.
        """
        ...


class LoggerPort(Protocol):
    """Records metadata-only diagnostics without message payloads."""

    def log(self, code: str, fields: Mapping[str, object]) -> None:
        """Records payload-free structured diagnostics.

        Args:
            code (str): Stable diagnostic code.
            fields (Mapping[str, object]): Non-content metadata.

        Returns:
            None
        """
        ...


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

    def __post_init__(self) -> None:
        """Validates declared capabilities against injected optional ports.

        Args:
            None

        Raises:
            ValueError: If a capability and its corresponding port disagree.

        Returns:
            None
        """
        capability_ports: tuple[tuple[str, object], ...] = (
            ('audio_capture', self.audio_capture),
            ('audio_playback', self.audio_playback),
            ('qr_scanner', self.qr_scanner),
            ('haptics', self.haptics),
            ('display_control', self.display),
            ('power_control', self.power),
        )
        for capability_name, port in capability_ports:
            declared: bool = bool(getattr(self.capabilities, capability_name))
            if declared != (port is not None):
                raise ValueError(
                    f"Capability '{capability_name}' does not match its injected port."
                )
