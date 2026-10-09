"""Independent bounded Call input/output workers over exact-client public SDK grants."""

import base64
import threading
import time
from typing import Protocol

from metor.client import MetorClient
from metor.client.platform import CapturePort, OutputPort
from metor.core.api import CallAudioEvent, CallAudioSentEvent
from metor.shared import Constants
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.state.mailbox import Mailbox, Update


class CallAudioPort(CapturePort, OutputPort, Protocol):
    """Two independently owned native directions on an explicitly selected headset."""


class CallMediaWorker:
    """Streams recent PCM without message identities, retention, recording or DROP."""

    def __init__(
        self,
        client: MetorClient,
        call_id: str,
        audio: CallAudioPort,
        mailbox: Mailbox,
        generation: int,
        *,
        muted: bool = False,
    ) -> None:
        """Binds accepted Call authority before opening either native direction.

        Args:
            client: Exact client that explicitly started or accepted the Call.
            call_id: Immutable Core Call identity.
            audio: Confirmed inert headset ports with bounded expiring capture.
            mailbox: Content-free worker result handoff.
            generation: GUI activation fence.
            muted: Initial authoritative microphone mute state.
        """
        self.client, self.call_id, self.audio = client, call_id, audio
        self.mailbox, self.generation = mailbox, generation
        self.done = threading.Event()
        self._stop = threading.Event()
        self._muted = threading.Event()
        self._capture_revoked = threading.Event()
        self._guard = threading.Lock()
        self._remaining = 2
        self._failed = False
        if muted:
            self._muted.set()
        self._threads = (
            threading.Thread(
                target=self._capture, name='metor-call-input', daemon=True
            ),
            threading.Thread(target=self._play, name='metor-call-output', daemon=True),
        )

    def start(self) -> None:
        """Starts both directions independently after explicit accepted authorization."""
        for thread in self._threads:
            thread.start()

    def mute(self, muted: bool) -> None:
        """Changes native capture admission while leaving receive audio independent."""
        if muted:
            self._muted.set()
            self._capture_revoked.set()
            self.audio.interrupt_capture()
            self.audio.discard_capture()
        else:
            self._muted.clear()

    def stop(self) -> None:
        """Revokes fresh audio immediately without blocking the native event loop."""
        self._stop.set()
        self.audio.interrupt_capture()
        self.audio.discard_capture()

    def _failure(self) -> None:
        """Ends the exact Call on native/IPC failure; no delayed audio is replayed."""
        self.stop()
        with self._guard:
            if self._failed:
                return
            self._failed = True
        self.mailbox.put(
            Update(
                self.generation,
                'call-media-error:' + self.call_id,
                status='Call audio stopped. Check the audio devices and call again.',
            )
        )
        try:
            self.client.hangup_call(self.call_id)
        except Exception:
            # Core independently fences transport/client loss; never retry a new identity.
            return

    def _finished(self) -> None:
        """Publishes release only when both native directions have finished cleanup."""
        with self._guard:
            self._remaining -= 1
            if self._remaining:
                return
        self.done.set()
        self.mailbox.put(Update(self.generation, 'call-media-done:' + self.call_id))

    def _capture(self) -> None:
        """Sends only complete recent frames, stopping the microphone while muted."""
        sequence = 0
        capturing = False
        try:
            while not self._stop.is_set():
                if capturing and self._capture_revoked.is_set():
                    self.audio.stop_capture()
                    self.audio.discard_capture()
                    capturing = False
                    self._capture_revoked.clear()
                if self._muted.is_set():
                    if capturing:
                        self.audio.stop_capture()
                        self.audio.discard_capture()
                        capturing = False
                    self._stop.wait(PcmVoice.FRAME_SECONDS)
                    continue
                if not capturing:
                    self.audio.start_capture(headset_confirmed=True)
                    capturing = True
                if self.audio.failed:
                    raise RuntimeError('Call microphone unavailable')
                frame = self.audio.take_frame()
                if frame is None:
                    self._stop.wait(PcmVoice.FRAME_SECONDS)
                    continue
                if self._stop.is_set() or self._muted.is_set():
                    continue
                if len(frame) != PcmVoice.FRAME_BYTES:
                    raise ValueError('Invalid Call microphone frame')
                event = self.client.send_call_audio(
                    self.call_id, sequence, base64.b64encode(frame).decode('ascii')
                )
                if (
                    not isinstance(event, CallAudioSentEvent)
                    or event.call_id != self.call_id
                    or event.next_sequence != sequence + 1
                ):
                    raise ValueError('Call microphone admission ended')
                sequence += 1
        except Exception:
            if not self._stop.is_set():
                self._failure()
        finally:
            try:
                self.audio.stop_capture()
                self.audio.discard_capture()
            except Exception:
                self._failure()
            self._finished()

    def _play(self) -> None:
        """Reads recent bounded PCM independently of a simultaneous microphone request."""
        sequence = -1
        try:
            while not self._stop.is_set():
                event = self.client.read_call_audio(
                    self.call_id, max_frames=Constants.CALL_AUDIO_READ_FRAMES
                )
                if (
                    not isinstance(event, CallAudioEvent)
                    or event.call_id != self.call_id
                    or len(event.frames) > Constants.CALL_AUDIO_READ_FRAMES
                ):
                    raise ValueError('Call output admission ended')
                deadline = time.monotonic() + Constants.CALL_AUDIO_EXPIRY_SEC
                for source in event.frames:
                    if self._stop.is_set() or time.monotonic() >= deadline:
                        break
                    if source.sequence <= sequence:
                        continue
                    frame = base64.b64decode(source.data, validate=True)
                    if len(frame) != PcmVoice.FRAME_BYTES:
                        raise ValueError('Invalid Call output frame')
                    self.audio.play_frame(frame, headset_confirmed=True)
                    sequence = source.sequence
                if not event.frames:
                    self._stop.wait(PcmVoice.FRAME_SECONDS)
        except Exception:
            if not self._stop.is_set():
                self._failure()
        finally:
            try:
                self.audio.stop_output()
            except Exception:
                self._failure()
            self._finished()
