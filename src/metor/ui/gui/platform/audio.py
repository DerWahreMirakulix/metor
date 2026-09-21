"""Bounded PortAudio headset ports and the explicitly named PCM Voice codec."""

from collections import deque
import threading
from typing import Protocol

from metor.client.platform import AudioCapabilities, AudioEndpoint
from metor.ui.gui.constants import GuiLimits


class PcmVoice:
    """Interoperable signed little-endian mono PCM with sample-aligned seeking."""

    CODEC: str = 'pcm_s16le_16000_mono'
    SAMPLE_RATE: int = 16000
    SAMPLE_BYTES: int = 2
    CHANNELS: int = 1
    FRAME_SAMPLES: int = 320
    FRAME_BYTES: int = FRAME_SAMPLES * SAMPLE_BYTES
    FRAME_SECONDS: float = FRAME_SAMPLES / SAMPLE_RATE
    MILLISECONDS: int = 1000

    @classmethod
    def validate(cls, payload: bytes, *, final: bool = False) -> None:
        """Rejects incomplete samples and non-final partial capture frames.

        Args:
            payload: Encoded PCM bytes.
            final: Whether this is the last complete sample range.
        Returns:
            None
        """
        alignment = cls.SAMPLE_BYTES if final else cls.FRAME_BYTES
        if not payload or len(payload) % alignment:
            raise ValueError('Incomplete PCM frame')

    @classmethod
    def duration_ms(cls, accepted_bytes: int) -> int:
        """Derives timing from accepted samples, never repaint or remote claims.

        Args:
            accepted_bytes: Accepted complete sample bytes.
        Returns:
            int: Encoded duration in milliseconds.
        """
        if accepted_bytes < 0 or accepted_bytes % cls.SAMPLE_BYTES:
            raise ValueError('Invalid PCM sample offset')
        return accepted_bytes * cls.MILLISECONDS // (cls.SAMPLE_RATE * cls.SAMPLE_BYTES)

    @classmethod
    def seek_offset(cls, milliseconds: int, available_bytes: int) -> int:
        """Computes a bounded independent decoder checkpoint without rereading.

        Args:
            milliseconds: Requested playback position.
            available_bytes: Current retained size.
        Returns:
            int: Complete sample boundary at or before the available edge.
        """
        if milliseconds < 0 or available_bytes < 0:
            raise ValueError('Invalid PCM seek range')
        requested = (
            milliseconds * cls.SAMPLE_RATE // cls.MILLISECONDS * cls.SAMPLE_BYTES
        )
        return min(requested, available_bytes - available_bytes % cls.SAMPLE_BYTES)


class AudioStream(Protocol):
    """Minimal native stream operations kept outside presentation state."""

    def start(self) -> None:
        """Starts the native stream.

        Args:
            None
        Returns:
            None
        """
        ...

    def stop(self) -> None:
        """Stops the native stream without disposing it.

        Args:
            None
        Returns:
            None
        """
        ...

    def close(self) -> None:
        """Releases the native stream.

        Args:
            None
        Returns:
            None
        """
        ...

    def write(self, data: bytes) -> bool:
        """Writes one bounded PCM segment.

        Args:
            data: PCM bytes to play.
        Returns:
            bool: Whether the stream accepted the segment.
        """
        ...


class HeadsetAudio:
    """One explicit native capture and output route with bounded capture handoff."""

    def __init__(
        self,
        input_device: int | str | None = None,
        output_device: int | str | None = None,
    ) -> None:
        """Creates an inert adapter without opening any microphone or output.

        Args:
            input_device: Explicit validated native capture endpoint, or native default.
            output_device: Explicit validated native output endpoint, or native default.
        Returns:
            None
        """
        self._capture: AudioStream | None = None
        self._output: AudioStream | None = None
        self._frames: deque[bytes] = deque()
        self._bytes: int = 0
        self._lock = threading.Lock()
        self._capture_cancel = threading.Event()
        self.failed: bool = False
        self.input_device = input_device
        self.output_device = output_device

    @staticmethod
    def endpoints() -> tuple[AudioEndpoint, ...]:
        """Enumerates bounded native route choices without activating a microphone.

        Args:
            None
        Returns:
            tuple[AudioEndpoint, ...]: Native input/output choices; empty means unavailable.
        """
        import sounddevice

        devices = sounddevice.query_devices()
        hosts = sounddevice.query_hostapis()
        endpoints = []
        for index, device in enumerate(devices[: GuiLimits.AUDIO_ENDPOINTS]):
            host = hosts[device['hostapi']]['name']
            name = f'{device["name"]} · {host}'[: GuiLimits.DEVICE_STRING]
            endpoints.append(
                AudioEndpoint(
                    index,
                    name,
                    device['max_input_channels'] > 0,
                    device['max_output_channels'] > 0,
                )
            )
        return tuple(endpoints)

    @staticmethod
    def capabilities() -> AudioCapabilities:
        """Probes optional devices without opening an active stream.

        Args:
            None
        Returns:
            AudioCapabilities: Available directions; never a successful AEC claim.
        """
        import sounddevice

        try:
            devices = sounddevice.query_devices()
            return AudioCapabilities(
                any(item['max_input_channels'] > 0 for item in devices),
                any(item['max_output_channels'] > 0 for item in devices),
            )
        except (sounddevice.PortAudioError, OSError):
            return AudioCapabilities(False, False)

    def start_capture(self, *, headset_confirmed: bool) -> None:
        """Opens capture only after explicit admission and route confirmation.

        Args:
            headset_confirmed: Explicitly selected supported headset route.
        Returns:
            None
        """
        import sounddevice

        if not headset_confirmed or self._capture is not None:
            raise RuntimeError(
                'A confirmed headset route and idle capture are required'
            )
        self.failed = False
        self._capture_cancel.clear()
        stream = sounddevice.RawInputStream(
            device=self.input_device,
            samplerate=PcmVoice.SAMPLE_RATE,
            channels=PcmVoice.CHANNELS,
            dtype='int16',
            blocksize=PcmVoice.FRAME_SAMPLES,
            callback=self._received,
        )
        self._capture = stream
        try:
            stream.start()
        except Exception:
            try:
                stream.close()
            finally:
                self._capture = None
            raise

    def _received(
        self, data: bytes, _frames: int, _time: object, status: object
    ) -> None:
        """Accepts complete callback frames without touching SDK or GUI widgets.

        Args:
            data: Native frame buffer.
            _frames: Native frame count.
            _time: Native timing information.
            status: Overflow/device status.
        Returns:
            None
        """
        payload = bytes(data)
        if self._capture_cancel.is_set():
            import sounddevice

            raise sounddevice.CallbackAbort
        with self._lock:
            if (
                status
                or len(payload) != PcmVoice.FRAME_BYTES
                or self._bytes + len(payload) > GuiLimits.CAPTURE_BYTES
            ):
                self.failed = True
            if self.failed:
                import sounddevice

                raise sounddevice.CallbackAbort
            self._frames.append(payload)
            self._bytes += len(payload)

    def take_frame(self) -> bytes | None:
        """Hands off a bounded encoded frame to the media worker.

        Args:
            None
        Returns:
            bytes | None: Next complete frame; ownership transfers to caller.
        """
        with self._lock:
            if not self._frames:
                return None
            frame = self._frames.popleft()
            self._bytes -= len(frame)
            return frame

    def play_frame(self, frame: bytes, *, headset_confirmed: bool) -> None:
        """Writes one bounded frame on an independent output worker.

        Args:
            frame: Valid complete PCM samples.
            headset_confirmed: Explicit headset route confirmation.
        Returns:
            None
        """
        import sounddevice

        if not headset_confirmed or len(frame) > GuiLimits.DECODE_BYTES:
            raise RuntimeError('Unsupported output route or frame size')
        PcmVoice.validate(frame, final=True)
        if self._output is None:
            stream = sounddevice.RawOutputStream(
                device=self.output_device,
                samplerate=PcmVoice.SAMPLE_RATE,
                channels=PcmVoice.CHANNELS,
                dtype='int16',
            )
            self._output = stream
            try:
                stream.start()
            except Exception:
                try:
                    stream.close()
                finally:
                    self._output = None
                raise
        if self._output.write(frame):
            raise RuntimeError(
                'Audio output underflow; playback coverage is unconfirmed'
            )

    def stop(self) -> None:
        """Stops both directions and releases local buffers without any Core consume.

        Args:
            None
        Returns:
            None
        """
        failure: Exception | None = None
        for operation in (self.stop_capture, self.stop_output):
            try:
                operation()
            except Exception as exc:
                failure = failure or exc
        self.discard_capture()
        if failure is not None:
            raise RuntimeError('Audio device cleanup failed') from failure

    def stop_capture(self) -> None:
        """Stops input independently, retaining complete frames for final admission.

        Args:
            None
        Returns:
            None
        """
        self._capture_cancel.set()
        stream, self._capture = self._capture, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

    def interrupt_capture(self) -> None:
        """Stops new microphone callbacks without waiting on a blocked SDK request.

        Args:
            None
        Returns:
            None
        """
        self._capture_cancel.set()

    def stop_output(self) -> None:
        """Stops playback without interrupting a simultaneous microphone stream.

        Args:
            None
        Returns:
            None
        """
        stream, self._output = self._output, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

    def discard_capture(self) -> None:
        """Releases volatile input frames after handoff or an explicit abort.

        Args:
            None
        Returns:
            None
        """
        with self._lock:
            self._frames.clear()
            self._bytes = 0
