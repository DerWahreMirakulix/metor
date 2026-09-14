"""Bounded microphone handoff to one Core-owned logical Voice recording."""

import base64
import threading
import time
from typing import Protocol

from metor.client import MetorClient, MetorRequestRejectedError
from metor.core.api import (
    Delivery,
    IpcEvent,
    MessageDirectionCode,
    RetainedMessageEntry,
    RetainedMessagesEvent,
    VoiceChunkAcceptedEvent,
    VoiceFinalizedEvent,
)
from metor.shared import Constants
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.state.mailbox import Mailbox, Update
from metor.ui.gui.state.media import MediaCache, PlaybackTarget

# Local Package Imports
from .press import CaptureBinding


class CapturePort(Protocol):
    """Input-only audio boundary; stopping input never stops duplex playback."""

    failed: bool

    def start_capture(self, *, headset_confirmed: bool) -> None: ...
    def stop_capture(self) -> None: ...
    def interrupt_capture(self) -> None: ...
    def take_frame(self) -> bytes | None: ...
    def discard_capture(self) -> None: ...


class CaptureWorker:
    """Owns one bounded native capture stream and serial SDK upload sequence."""

    def __init__(
        self,
        client: MetorClient,
        owner: str,
        binding: CaptureBinding,
        audio: CapturePort,
        mailbox: Mailbox,
        cache: MediaCache | None = None,
    ) -> None:
        """Captures immutable connection, profile and input ownership.

        Args:
            client: Exact authenticated SDK connection that owns the lease.
            owner: Core-issued disposable producer token.
            binding: Target and activation from the initiating press.
            audio: Explicitly configured supported headset capture port.
            mailbox: Bounded UI handoff queue.
            cache: Optional shared bounded cache for confirmed own LIVE source bytes.
        Returns:
            None
        """
        self.client = client
        self.owner = owner
        self.binding = binding
        self.audio = audio
        self.mailbox = mailbox
        self.cache = cache
        self.cache_target = PlaybackTarget(
            binding.generation,
            binding.profile_instance,
            binding.epoch,
            binding.peer,
            binding.delivery,
            MessageDirectionCode.OUT,
            binding.msg_id,
        )
        self.stop = threading.Event()
        self.purge = threading.Event()
        self.done = threading.Event()
        self.accepted_bytes = 0
        self.completion_confirmed = False
        self._thread = threading.Thread(
            target=self._run, name='metor-gui-capture', daemon=True
        )

    def start(self) -> None:
        """Starts one worker after the UI has admitted a fresh eligible press.

        Args:
            None
        Returns:
            None
        """
        self._thread.start()

    def request_stop(self, *, purge: bool = False) -> None:
        """Signals asynchronous stop without blocking the GUI event loop.

        Args:
            purge: Accepted purge preempts every normal finalize/recovery request.
        Returns:
            None
        """
        if purge:
            self.purge.set()
        self.stop.set()
        self.audio.interrupt_capture()

    def _emit(
        self, operation: str, event: IpcEvent | None = None, status: str = ''
    ) -> None:
        """Publishes only a bounded generation-qualified result.

        Args:
            operation: Recording operation phase.
            event: Actual public Core result, never a fabricated acknowledgement.
            status: Content-free interaction feedback.
        Returns:
            None
        """
        if operation in {'voice-finished', 'voice-empty', 'voice-rejected'}:
            self.completion_confirmed = True
        if operation == 'voice-finished' and self.cache is not None:
            self.cache.mark_complete(self.cache_target, self.accepted_bytes)
        if not self.mailbox.put(
            Update(
                self.binding.generation,
                operation + ':' + self.binding.msg_id,
                event,
                status,
            )
        ):
            self.stop.set()

    def _lookup(self) -> tuple[RetainedMessagesEvent, RetainedMessageEntry] | None:
        """Reconciles this exact retained identity without reading or consuming bytes.

        Args:
            None
        Returns:
            tuple[RetainedMessagesEvent, RetainedMessageEntry] | None: Canonical item, if retained.
        """
        page = self.client.list_retained_messages(
            target=self.binding.peer,
            direction=MessageDirectionCode.OUT,
            msg_id=self.binding.msg_id,
            owner_token=self.owner,
        )
        if page is None:
            return None
        for item in page.messages:
            if (
                item.onion == self.binding.peer
                and item.msg_id == self.binding.msg_id
                and item.direction is MessageDirectionCode.OUT
            ):
                return page, item
        return None

    def _finish(self, status: str) -> None:
        """Finalizes only canonical accepted bytes, reconciling automatic limit finalization.

        Args:
            status: Any preceding capture/refusal feedback.
        Returns:
            None
        """
        if self.purge.is_set():
            return
        retained = self._lookup()
        if retained is None:
            self._emit(
                'voice-error',
                status='Recording state is unconfirmed; accepted audio remains managed by Metor',
            )
            return
        page, item = retained
        self.accepted_bytes = item.size_bytes
        if self.purge.is_set():
            return
        if item.size_bytes == 0 and self.binding.delivery is Delivery.DROP:
            cancelled = self.client.cancel_voice(
                self.binding.peer, self.binding.msg_id, owner_token=self.owner
            )
            self._emit(
                'voice-empty' if cancelled is not None else 'voice-error',
                cancelled,
                status or 'No audio was captured',
            )
            return
        if item.finalized:
            self._emit('voice-finished', page, status)
            return
        if self.purge.is_set():
            return
        result = self.client.finalize_voice(
            self.binding.msg_id,
            PcmVoice.duration_ms(item.size_bytes),
            owner_token=self.owner,
        )
        if (
            isinstance(result, VoiceFinalizedEvent)
            and result.msg_id == self.binding.msg_id
            and result.onion == self.binding.peer
        ):
            self._emit('voice-finished', result, status)
        else:
            self._emit(
                'voice-error',
                status='Finalization is unconfirmed; accepted audio is preserved',
            )

    def _run(self) -> None:
        """Runs admission, capture, bounded drain and accepted-prefix finalization.

        Args:
            None
        Returns:
            None
        """
        admitted = False
        status = ''
        try:
            if self.purge.is_set():
                return
            result = self.client.begin_voice(
                self.binding.peer,
                self.binding.delivery,
                self.binding.msg_id,
                PcmVoice.CODEC,
                owner_token=self.owner,
                context_generation=self.binding.context_generation,
            )
            if (
                result is None
                or result.msg_id != self.binding.msg_id
                or result.onion != self.binding.peer
                or result.delivery is not self.binding.delivery
            ):
                self._emit(
                    'voice-error', status='Recording admission could not be confirmed'
                )
                return
            admitted = True
            self._emit('voice-start', result)
            if not self.stop.is_set():
                self.audio.start_capture(headset_confirmed=True)
            draining: float | None = None
            while not self.purge.is_set():
                if self.audio.failed:
                    status = 'Microphone interrupted; only accepted audio is preserved'
                    self.stop.set()
                if self.stop.is_set() and draining is None:
                    self.audio.stop_capture()
                    draining = time.monotonic() + GuiLimits.CAPTURE_DRAIN_SECONDS
                if draining is not None and time.monotonic() >= draining:
                    status = (
                        'Recording stopped before all captured audio could be accepted'
                    )
                    break
                frame = self.audio.take_frame()
                if frame is None:
                    if draining is not None:
                        break
                    self.stop.wait(PcmVoice.FRAME_SECONDS)
                    continue
                PcmVoice.validate(frame)
                batch = bytearray(frame)
                while (
                    len(batch) + PcmVoice.FRAME_BYTES <= Constants.VOICE_CHUNK_MAX_BYTES
                ):
                    frame = self.audio.take_frame()
                    if frame is None:
                        break
                    PcmVoice.validate(frame)
                    batch.extend(frame)
                outcome = self.client.append_voice(
                    self.binding.msg_id,
                    self.accepted_bytes,
                    base64.b64encode(batch).decode('ascii'),
                    owner_token=self.owner,
                )
                if (
                    not isinstance(outcome, VoiceChunkAcceptedEvent)
                    or outcome.msg_id != self.binding.msg_id
                    or outcome.next_offset != self.accepted_bytes + len(batch)
                ):
                    status = 'Recording stopped; checking the accepted audio'
                    break
                if self.cache is not None and self.binding.delivery is Delivery.LIVE:
                    self.cache.append(
                        self.cache_target,
                        self.accepted_bytes,
                        bytes(batch),
                        complete=False,
                    )
                self.accepted_bytes = outcome.next_offset
                self._emit('voice-progress', outcome)
        except MetorRequestRejectedError as exc:
            if not admitted:
                self._emit('voice-rejected', exc.event, 'Recording was not accepted')
            else:
                status = 'Recording interrupted; checking the accepted audio'
        except Exception:
            if not admitted:
                self._emit(
                    'voice-error', status='Recording admission could not be confirmed'
                )
            else:
                status = (
                    'Microphone or recording interrupted; accepted audio is preserved'
                )
        finally:
            try:
                try:
                    self.audio.stop_capture()
                except Exception:
                    status = 'Microphone cleanup failed; checking the accepted audio'
                self.audio.discard_capture()
                if admitted and not self.purge.is_set():
                    self._finish(status)
            except Exception:
                self._emit(
                    'voice-error',
                    status='Recording cleanup or finalization is unconfirmed; accepted audio is preserved',
                )
            finally:
                self.done.set()
                self._emit('voice-worker-done')
