"""Deterministic in-memory platform fakes for embedded frontend tests."""

from typing import Callable, Mapping, Optional

from metor.ui.embedded.platform import (
    AudioPlaybackState,
    BatteryState,
    EncodedAudioResult,
    HardwareInputEvent,
    QrScannerStatus,
)

DEFAULT_DISPLAY_WIDTH = 320
DEFAULT_DISPLAY_HEIGHT = 240
DEFAULT_PERCENT = 100
DEFAULT_DISPLAY_DENSITY = 1.0


class FakeHardwareInput:
    """Push-driven input fake."""

    def __init__(self) -> None:
        """Initializes an input source without a subscriber.

        Args:
            None

        Returns:
            None
        """
        self._callback: Optional[Callable[[HardwareInputEvent], None]] = None

    def subscribe(self, callback: Callable[[HardwareInputEvent], None]) -> None:
        """Registers the active event consumer.

        Args:
            callback (Callable): Input event receiver.

        Returns:
            None
        """
        self._callback = callback

    def emit(self, event: HardwareInputEvent) -> None:
        """Emits one deterministic input event.

        Args:
            event (HardwareInputEvent): Event to emit.

        Returns:
            None
        """
        if self._callback is not None:
            self._callback(event)


class FakeClock:
    """Manually advanced deterministic clock."""

    def __init__(self, wall_time: float = 0.0) -> None:
        """Initializes both clocks.

        Args:
            wall_time (float): Initial wall-clock value.

        Returns:
            None
        """
        self._monotonic: float = 0.0
        self._wall_time: float = wall_time

    def monotonic(self) -> float:
        """Returns monotonic time.

        Args:
            None

        Returns:
            float: Current monotonic value.
        """
        return self._monotonic

    def wall_time(self) -> float:
        """Returns wall-clock time.

        Args:
            None

        Returns:
            float: Current wall-clock value.
        """
        return self._wall_time

    def advance(self, seconds: float) -> None:
        """Advances both clocks.

        Args:
            seconds (float): Non-negative increment.

        Returns:
            None
        """
        if seconds < 0:
            raise ValueError('Clock cannot move backwards.')
        self._monotonic += seconds
        self._wall_time += seconds


class FakeLocalUiSettingsStore:
    """Namespace-enforcing device-local settings fake."""

    def __init__(self, values: Optional[Mapping[str, object]] = None) -> None:
        """Initializes the store from optional values.

        Args:
            values (Optional[Mapping]): Initial embedded settings.

        Returns:
            None
        """
        self._values: dict[str, object] = dict(values or {})
        for key in self._values:
            self._validate_key(key)

    @staticmethod
    def _validate_key(key: str) -> None:
        """Rejects settings outside the embedded UI namespace.

        Args:
            key (str): Setting key.

        Returns:
            None
        """
        if not key.startswith('ui.embedded.'):
            raise ValueError('Embedded settings must use the ui.embedded namespace.')

    def get(self, key: str) -> object:
        """Returns one stored setting.

        Args:
            key (str): Setting key.

        Returns:
            object: Stored value.
        """
        self._validate_key(key)
        return self._values[key]

    def set(self, key: str, value: object) -> None:
        """Stores one namespaced setting.

        Args:
            key (str): Setting key.
            value (object): Setting value.

        Returns:
            None
        """
        self._validate_key(key)
        self._values[key] = value

    def snapshot(self) -> Mapping[str, object]:
        """Returns a detached settings snapshot.

        Args:
            None

        Returns:
            Mapping[str, object]: Copied setting values.
        """
        return dict(self._values)


class FakePrivacyLogger:
    """Metadata logger that rejects likely content-bearing fields."""

    _SENSITIVE_FIELDS = frozenset({'content', 'payload', 'text', 'audio'})

    def __init__(self) -> None:
        """Initializes an empty record list.

        Args:
            None

        Returns:
            None
        """
        self.records: list[tuple[str, Mapping[str, object]]] = []

    def log(self, code: str, fields: Mapping[str, object]) -> None:
        """Records safe metadata and rejects message content.

        Args:
            code (str): Stable diagnostic code.
            fields (Mapping[str, object]): Structured metadata.

        Returns:
            None
        """
        if self._SENSITIVE_FIELDS.intersection(fields):
            raise ValueError('Message payloads must not be written to UI logs.')
        self.records.append((code, dict(fields)))


class FakeAudioCapture:
    """Bounded audio-capture fake returning a preconfigured blob reference."""

    def __init__(self, result: EncodedAudioResult) -> None:
        """Initializes capture with its deterministic result.

        Args:
            result (EncodedAudioResult): Result returned after capture.

        Returns:
            None
        """
        self.result = result
        self.started = False
        self.cancelled = False

    def start(self, max_duration_ms: int, max_size_bytes: int) -> None:
        """Starts capture when both bounds are positive.

        Args:
            max_duration_ms (int): Maximum capture duration.
            max_size_bytes (int): Maximum encoded result size.

        Returns:
            None
        """
        if max_duration_ms <= 0 or max_size_bytes <= 0:
            raise ValueError('Audio limits must be positive.')
        self.started = True

    def stop(self) -> EncodedAudioResult:
        """Stops capture and returns the configured result.

        Args:
            None

        Returns:
            EncodedAudioResult: Configured capture result.
        """
        if not self.started:
            raise RuntimeError('Capture has not started.')
        self.started = False
        return self.result

    def cancel(self) -> None:
        """Cancels active capture.

        Args:
            None

        Returns:
            None
        """
        self.started = False
        self.cancelled = True


class FakeAudioPlayback:
    """State-recording playback fake."""

    def __init__(self) -> None:
        """Initializes idle playback state.

        Args:
            None

        Returns:
            None
        """
        self.blob_reference: Optional[str] = None
        self.paused = False
        self.volume_percent = DEFAULT_PERCENT
        self.route = 'speaker'
        self.position_ms = 0
        self.duration_ms = 0

    def play(self, blob_reference: str) -> None:
        """Records playback of a blob reference.

        Args:
            blob_reference (str): Opaque blob reference.

        Returns:
            None
        """
        self.blob_reference = blob_reference
        self.paused = False

    def pause(self) -> None:
        """Marks playback as paused.

        Args:
            None

        Returns:
            None
        """
        self.paused = True

    def stop(self) -> None:
        """Clears active playback state.

        Args:
            None

        Returns:
            None
        """
        self.blob_reference = None
        self.paused = False

    def state(self) -> AudioPlaybackState:
        """Returns the current deterministic playback state.

        Args:
            None

        Returns:
            AudioPlaybackState: Current fake state.
        """
        return AudioPlaybackState(
            position_ms=self.position_ms,
            duration_ms=self.duration_ms,
            route=self.route,
            volume_percent=self.volume_percent,
        )

    def set_route(self, route: str) -> None:
        """Records the selected output route.

        Args:
            route (str): Platform route identifier.

        Returns:
            None
        """
        self.route = route

    def set_volume(self, volume_percent: int) -> None:
        """Records a validated playback volume.

        Args:
            volume_percent (int): Volume percentage.

        Returns:
            None
        """
        if not 0 <= volume_percent <= DEFAULT_PERCENT:
            raise ValueError('Volume must be between zero and one hundred.')
        self.volume_percent = volume_percent


class FakeQrScanner:
    """Deterministic optional QR scanner fake."""

    def __init__(
        self,
        payload: bytes = b'',
        available: bool = True,
        permission_granted: bool = True,
    ) -> None:
        """Initializes scanner availability, permission, and payload.

        Args:
            payload (bytes): Raw payload returned by a scan.
            available (bool): Whether scanner hardware exists.
            permission_granted (bool): Initial camera permission state.

        Returns:
            None
        """
        self._payload = payload
        self._available = available
        self.cancelled = False
        self.permission_granted = available and permission_granted

    @property
    def available(self) -> bool:
        """Reports configured hardware availability.

        Args:
            None

        Returns:
            bool: True when scanner hardware is available.
        """
        return self._available

    def status(self) -> QrScannerStatus:
        """Returns the configured availability and permission state.

        Args:
            None

        Returns:
            QrScannerStatus: Current scanner status.
        """
        if not self.available:
            return QrScannerStatus.UNAVAILABLE
        if not self.permission_granted:
            return QrScannerStatus.PERMISSION_REQUIRED
        return QrScannerStatus.READY

    def request_permission(self) -> bool:
        """Grants permission when scanner hardware is available.

        Args:
            None

        Returns:
            bool: True when permission is granted.
        """
        if not self.available:
            return False
        self.permission_granted = True
        return True

    def scan(self) -> bytes:
        """Returns the configured raw scanner payload.

        Args:
            None

        Returns:
            bytes: Configured scan payload.
        """
        if not self.available:
            raise RuntimeError('QR scanner is unavailable.')
        if not self.permission_granted:
            raise PermissionError('QR scanner permission is required.')
        return self._payload

    def cancel(self) -> None:
        """Records scan cancellation.

        Args:
            None

        Returns:
            None
        """
        self.cancelled = True


class FakeDisplay:
    """State-recording display fake."""

    def __init__(
        self,
        width: int = DEFAULT_DISPLAY_WIDTH,
        height: int = DEFAULT_DISPLAY_HEIGHT,
    ) -> None:
        """Initializes display geometry and active state.

        Args:
            width (int): Display width in pixels.
            height (int): Display height in pixels.

        Returns:
            None
        """
        self._dimensions = (width, height)
        self.brightness = DEFAULT_PERCENT
        self.awake = True

    def dimensions(self) -> tuple[int, int]:
        """Returns configured display dimensions.

        Args:
            None

        Returns:
            tuple[int, int]: Width and height in pixels.
        """
        return self._dimensions

    def density(self) -> float:
        """Returns the deterministic display density.

        Args:
            None

        Returns:
            float: Display density multiplier.
        """
        return DEFAULT_DISPLAY_DENSITY

    def set_brightness(self, percent: int) -> None:
        """Records a validated brightness percentage.

        Args:
            percent (int): Brightness percentage.

        Returns:
            None
        """
        if not 0 <= percent <= DEFAULT_PERCENT:
            raise ValueError('Brightness must be between zero and one hundred.')
        self.brightness = percent

    def wake(self) -> None:
        """Records that the display is awake.

        Args:
            None

        Returns:
            None
        """
        self.awake = True

    def sleep(self) -> None:
        """Records that the display is asleep.

        Args:
            None

        Returns:
            None
        """
        self.awake = False


class FakeHaptics:
    """Feedback-pattern recording fake."""

    def __init__(self) -> None:
        """Initializes an empty feedback record.

        Args:
            None

        Returns:
            None
        """
        self.patterns: list[str] = []

    def pulse(self, pattern: str) -> None:
        """Records one requested feedback pattern.

        Args:
            pattern (str): Stable pattern identifier.

        Returns:
            None
        """
        self.patterns.append(pattern)


class FakePower:
    """Battery and lifecycle request fake."""

    def __init__(
        self,
        battery: BatteryState = BatteryState(DEFAULT_PERCENT, False),
    ) -> None:
        """Initializes battery state and lifecycle flags.

        Args:
            battery (BatteryState): Initial battery state.

        Returns:
            None
        """
        self.battery = battery
        self.suspended = False
        self.shutdown_requested = False

    def battery_state(self) -> BatteryState:
        """Returns the configured battery state.

        Args:
            None

        Returns:
            BatteryState: Current fake battery state.
        """
        return self.battery

    def suspend(self) -> None:
        """Records platform suspension.

        Args:
            None

        Returns:
            None
        """
        self.suspended = True

    def resume(self) -> None:
        """Records platform resumption.

        Args:
            None

        Returns:
            None
        """
        self.suspended = False

    def request_shutdown(self) -> None:
        """Records an orderly shutdown request.

        Args:
            None

        Returns:
            None
        """
        self.shutdown_requested = True
