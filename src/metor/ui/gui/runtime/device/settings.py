"""Profile-independent device setting reads and writes outside the UI loop."""

import threading

from metor.client.platform import (
    DeviceSettingDescriptor,
    DeviceSettingResult,
    DeviceSettingStatus,
    DeviceSettingValue,
    HardwareSettingsPort,
    validate_descriptors,
)


class DeviceSettings:
    """Keep confirmed device readback separate from profile setting snapshots."""

    def __init__(self, port: HardwareSettingsPort | None) -> None:
        """Construct an inert local settings owner until explicit refresh."""
        self._port = port
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._ready: (
            tuple[
                tuple[DeviceSettingDescriptor, ...],
                dict[str, DeviceSettingResult],
                str,
            ]
            | None
        ) = None
        self._closed = False
        self.descriptors: tuple[DeviceSettingDescriptor, ...] = ()
        self.values: dict[str, DeviceSettingResult] = {}
        self.pending = False
        self.loaded = False
        self.feedback = ''

    @property
    def available(self) -> bool:
        """Report whether the selected local adapter offers ordinary settings."""
        return self._port is not None

    def refresh(self) -> bool:
        """Queue one bounded metadata/readback pass on a background worker."""
        return self._start(None)

    def write(self, key: str, value: DeviceSettingValue) -> bool:
        """Validate UI input before asking the executing adapter to validate it."""
        descriptor = next((row for row in self.descriptors if row.key == key), None)
        if (
            descriptor is None
            or not descriptor.writable
            or not descriptor.accepts(value)
        ):
            self.feedback = 'Device setting value is unsupported'
            return False
        return self._start((key, value))

    def _start(self, request: tuple[str, DeviceSettingValue] | None) -> bool:
        """Serialize reads and writes without blocking the toolkit event loop."""
        if self._port is None or self.pending or self._closed:
            return False
        self.pending = True
        self.feedback = (
            'Reading device settings…'
            if request is None
            else 'Applying device setting…'
        )
        self._worker = threading.Thread(
            target=self._run,
            args=(request,),
            name='metor-device-settings',
            daemon=True,
        )
        self._worker.start()
        return True

    def _run(self, request: tuple[str, DeviceSettingValue] | None) -> None:
        """Read device truth, never accepting admission as confirmed application."""
        port = self._port
        assert port is not None
        feedback = ''
        try:
            write_result: DeviceSettingResult | None = None
            if request is not None:
                write_result = port.write(*request)
                if not isinstance(write_result, DeviceSettingResult):
                    raise ValueError('Invalid device setting outcome')
                feedback = {
                    DeviceSettingStatus.APPLIED: 'Device setting applied',
                    DeviceSettingStatus.UNSUPPORTED: 'Device setting unsupported',
                    DeviceSettingStatus.DENIED: 'Device setting denied',
                    DeviceSettingStatus.UNAVAILABLE: 'Device unavailable',
                    DeviceSettingStatus.FAILED: 'Device setting failed',
                    DeviceSettingStatus.UNKNOWN: 'Device setting outcome unknown; reload to verify',
                }[write_result.status]
            descriptors = validate_descriptors(port.describe())
            values: dict[str, DeviceSettingResult] = {}
            for descriptor in descriptors:
                result = port.read(descriptor.key)
                if not isinstance(result, DeviceSettingResult) or (
                    result.status is DeviceSettingStatus.APPLIED
                    and (result.value is None or not descriptor.accepts(result.value))
                ):
                    raise ValueError('Invalid device setting readback')
                values[descriptor.key] = result
            if request is not None and write_result is not None:
                current = values.get(request[0])
                if write_result.status is DeviceSettingStatus.APPLIED and (
                    current is None
                    or current.status is not DeviceSettingStatus.APPLIED
                    or current.value != write_result.value
                ):
                    feedback = 'Device setting outcome unknown; reload to verify'
            ready = (descriptors, values, feedback)
        except Exception:
            ready = (
                self.descriptors,
                {
                    descriptor.key: DeviceSettingResult(DeviceSettingStatus.UNKNOWN)
                    for descriptor in self.descriptors
                },
                'Device settings unavailable; retry',
            )
        with self._lock:
            if not self._closed:
                self._ready = ready

    def poll(self) -> bool:
        """Install completed device observations on the GUI event loop."""
        with self._lock:
            ready, self._ready = self._ready, None
        if ready is None:
            return False
        self.descriptors, self.values, self.feedback = ready
        self.loaded = True
        self.pending = False
        self._worker = None
        return True

    def close(self) -> None:
        """Drop late observations when this frontend ends."""
        with self._lock:
            self._closed = True
            self._ready = None
