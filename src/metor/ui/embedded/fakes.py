"""Deterministic in-memory platform fakes for embedded frontend tests."""

from typing import Callable, Mapping, Optional

from metor.ui.embedded.platform import BatteryState, EncodedAudioResult, HardwareInputEvent


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
        self.result = result
        self.started = False
        self.cancelled = False

    def start(self, max_duration_ms: int, max_size_bytes: int) -> None:
        if max_duration_ms <= 0 or max_size_bytes <= 0:
            raise ValueError('Audio limits must be positive.')
        self.started = True

    def stop(self) -> EncodedAudioResult:
        if not self.started:
            raise RuntimeError('Capture has not started.')
        self.started = False
        return self.result

    def cancel(self) -> None:
        self.started = False
        self.cancelled = True


class FakeAudioPlayback:
    """State-recording playback fake."""

    def __init__(self) -> None:
        self.blob_reference: Optional[str] = None
        self.paused = False
        self.volume_percent = 100

    def play(self, blob_reference: str) -> None:
        self.blob_reference = blob_reference
        self.paused = False

    def pause(self) -> None:
        self.paused = True

    def stop(self) -> None:
        self.blob_reference = None
        self.paused = False

    def set_volume(self, volume_percent: int) -> None:
        if not 0 <= volume_percent <= 100:
            raise ValueError('Volume must be between zero and one hundred.')
        self.volume_percent = volume_percent


class FakeQrScanner:
    """Deterministic optional QR scanner fake."""

    def __init__(self, payload: bytes = b'', available: bool = True) -> None:
        self._payload = payload
        self._available = available
        self.cancelled = False

    @property
    def available(self) -> bool:
        return self._available

    def scan(self) -> bytes:
        if not self.available:
            raise RuntimeError('QR scanner is unavailable.')
        return self._payload

    def cancel(self) -> None:
        self.cancelled = True


class FakeDisplay:
    """State-recording display fake."""

    def __init__(self, width: int = 320, height: int = 240) -> None:
        self._dimensions = (width, height)
        self.brightness = 100
        self.awake = True

    def dimensions(self) -> tuple[int, int]:
        return self._dimensions

    def density(self) -> float:
        return 1.0

    def set_brightness(self, percent: int) -> None:
        if not 0 <= percent <= 100:
            raise ValueError('Brightness must be between zero and one hundred.')
        self.brightness = percent

    def wake(self) -> None:
        self.awake = True

    def sleep(self) -> None:
        self.awake = False


class FakeHaptics:
    """Feedback-pattern recording fake."""

    def __init__(self) -> None:
        self.patterns: list[str] = []

    def pulse(self, pattern: str) -> None:
        self.patterns.append(pattern)


class FakePower:
    """Battery and lifecycle request fake."""

    def __init__(self, battery: BatteryState = BatteryState(100, False)) -> None:
        self.battery = battery
        self.suspended = False
        self.shutdown_requested = False

    def battery_state(self) -> BatteryState:
        return self.battery

    def suspend(self) -> None:
        self.suspended = True

    def resume(self) -> None:
        self.suspended = False

    def request_shutdown(self) -> None:
        self.shutdown_requested = True
