"""Headset PCM ports that discard expired conversation audio instead of recording it."""

from collections import deque
import time

from metor.shared import Constants

# Local Package Imports
from .audio import HeadsetAudio, PcmVoice


class CallHeadsetAudio(HeadsetAudio):
    """Reuses explicit native streams with a bounded expiring capture jitter queue."""

    def __init__(self, input_device: int, output_device: int) -> None:
        """Creates inert ports without opening either direction.

        Args:
            input_device: Explicit enumerated headset microphone endpoint.
            output_device: Explicit enumerated headset playback endpoint.
        """
        super().__init__(input_device, output_device)
        self._realtime_frames: deque[tuple[float, bytes]] = deque(
            maxlen=Constants.CALL_AUDIO_MAX_FRAMES
        )

    def _received(
        self, data: bytes, _frames: int, _time: object, status: object
    ) -> None:
        """Accepts only recent complete frames; native failure stops the call cleanly."""
        if self._capture_cancel.is_set():
            import sounddevice

            raise sounddevice.CallbackAbort
        payload = bytes(data)
        with self._lock:
            if status or len(payload) != PcmVoice.FRAME_BYTES:
                self.failed = True
                import sounddevice

                raise sounddevice.CallbackAbort
            self._realtime_frames.append((time.monotonic(), payload))

    def take_frame(self) -> bytes | None:
        """Transfers a recent frame, discarding any microphone backlog after a stall."""
        now = time.monotonic()
        with self._lock:
            while self._realtime_frames:
                captured, frame = self._realtime_frames.popleft()
                if now - captured <= Constants.CALL_AUDIO_EXPIRY_SEC:
                    return frame
        return None

    def discard_capture(self) -> None:
        """Releases every local frame on mute, teardown or lifecycle interruption."""
        with self._lock:
            self._realtime_frames.clear()
