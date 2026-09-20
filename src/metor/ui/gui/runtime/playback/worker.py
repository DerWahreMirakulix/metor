"""Independent bounded PCM output worker with conservative finalized inbound handoff."""

import base64
import threading

from metor.client import MetorClient
from metor.client.platform import OutputPort
from metor.core.api import MessageDirectionCode, VoiceReleasedEvent
from metor.shared import Constants
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.state.mailbox import Mailbox, Update
from metor.ui.gui.state.media import MediaCache, PlaybackProgress, PlaybackTarget


class PlaybackWorker:
    """Plays one exact source, with an explicit stop barrier before any next source."""

    def __init__(
        self,
        client: MetorClient,
        target: PlaybackTarget,
        serial: int,
        audio: OutputPort,
        mailbox: Mailbox,
        cache: MediaCache,
        *,
        offset: int = 0,
    ) -> None:
        """Captures immutable routing and creates an inert worker.

        Args:
            client: Already authorized SDK connection.
            target: Exact source and activation identity.
            serial: Output ownership generation within the GUI activation.
            audio: Explicit supported headset output route.
            mailbox: Bounded typed presentation handoff.
            cache: Shared bounded volatile source retention.
            offset: Safe PCM start offset; skipped content never counts as heard.
        Returns:
            None
        """
        self.client, self.target, self.serial = client, target, serial
        self.audio, self.mailbox, self.cache = audio, mailbox, cache
        self.position = offset
        self._start = offset
        self._stop = threading.Event()
        self.done = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name='metor-gui-playback', daemon=True
        )

    def start(self) -> None:
        """Starts output work without blocking the native event loop.

        Args:
            None
        Returns:
            None
        """
        self._thread.start()

    def stop(self) -> None:
        """Revokes further output without waiting for an in-flight SDK read.

        Args:
            None
        Returns:
            None
        """
        self._stop.set()

    def _publish(self, state: str, size: int = 0, finalized: bool = False) -> None:
        """Reports bounded local output facts without any encoded audio payload.

        Args:
            state: Truthful local phase.
            size: Canonically available source bytes.
            finalized: Whether the entire source is finalized.
        Returns:
            None
        """
        self.mailbox.put(
            Update(
                self.target.generation,
                'playback',
                playback=PlaybackProgress(
                    self.target,
                    self.serial,
                    self.position,
                    size,
                    finalized,
                    state,
                ),
            )
        )

    def _read(self) -> tuple[bytes, int, bool, bool]:
        """Reads a bounded cache or SDK range with strict identity and codec checks.

        Args:
            None
        Returns:
            tuple: Bytes, available total, finalized end, and whether read from Core.
        """
        cached = self.cache.read(
            self.target, self.position, Constants.VOICE_CHUNK_MAX_BYTES
        )
        if cached is not None:
            data, size = cached
            return data, size, self.position + len(data) == size, False
        if self.cache.released(self.target):
            raise ValueError('Released audio is no longer retained')
        target = self.target
        event = self.client.get_voice_chunk(
            target.peer,
            target.msg_id,
            target.direction,
            self.position,
            Constants.VOICE_CHUNK_MAX_BYTES,
            owner_token=target.owner_token,
        )
        if event is None or (
            event.onion != target.peer
            or event.msg_id != target.msg_id
            or event.direction is not target.direction
            or event.delivery is not target.delivery
            or event.codec != PcmVoice.CODEC
            or event.offset != self.position
            or event.size_bytes < self.position
            or len(event.data) > ((Constants.VOICE_CHUNK_MAX_BYTES + 2) // 3) * 4
        ):
            raise ValueError('Audio unavailable')
        data = base64.b64decode(event.data, validate=True)
        if (
            len(data) > Constants.VOICE_CHUNK_MAX_BYTES
            or event.next_offset != self.position + len(data)
            or event.next_offset > event.size_bytes
            or event.complete
            and event.next_offset != event.size_bytes
            or event.size_bytes % PcmVoice.SAMPLE_BYTES
        ):
            raise ValueError('Audio incomplete')
        if data:
            PcmVoice.validate(data, final=True)
        self.cache.append(target, self.position, data, complete=event.complete)
        return data, event.size_bytes, event.complete, True

    def _run(self) -> None:
        """Keeps a complete replay source leased until output stops or the profile revokes it.

        Args:
            None
        Returns:
            None
        """
        with self.cache.retain(self.target):
            self._play()

    def _play(self) -> None:
        """Writes complete PCM frames and releases inbound data only after full output drain.

        Args:
            None
        Returns:
            None
        """
        size = 0
        complete = False
        failed = False
        self._publish('buffering')
        try:
            while not self._stop.is_set():
                payload, size, complete, _core_range = self._read()
                if self._stop.is_set():
                    break
                for offset in range(0, len(payload), PcmVoice.FRAME_BYTES):
                    if self._stop.is_set():
                        break
                    frame = payload[offset : offset + PcmVoice.FRAME_BYTES]
                    self.audio.play_frame(frame, headset_confirmed=True)
                    self.position += len(frame)
                if self._stop.is_set():
                    break
                self._publish('playing' if payload else 'buffering', size, complete)
                if complete:
                    break
                if not payload:
                    self._stop.wait(GuiLimits.PLAYBACK_POLL_SECONDS)
            self.audio.stop_output()
            self.cache.coverage.add(self.target, self._start, self.position)
            if complete and self.position == size and not self._stop.is_set():
                covered = self.cache.coverage.complete(self.target, size)
                if (
                    covered
                    and self.target.direction is MessageDirectionCode.IN
                    and not self.cache.released(self.target)
                ):
                    event = self.client.release_voice(
                        self.target.peer, self.target.msg_id
                    )
                    if (
                        not isinstance(event, VoiceReleasedEvent)
                        or event.onion != self.target.peer
                        or event.msg_id != self.target.msg_id
                    ):
                        self._publish('played_unconfirmed', size, True)
                        return
                    self.cache.mark_released(self.target)
                self._publish(
                    'complete'
                    if covered or self.cache.released(self.target)
                    else 'partial',
                    size,
                    True,
                )
            else:
                self._publish('paused', size, complete)
        except Exception:
            failed = True
            self._publish('unavailable', size, False)
        finally:
            try:
                self.audio.stop_output()
            except Exception:
                if not failed:
                    self._publish('unavailable', size, False)
            self.done.set()
            self.mailbox.put(Update(self.target.generation, 'playback-done'))
