"""GUI capture workers over real Core IPC with explicitly synthetic microphone frames."""

from collections import deque
from dataclasses import replace
from typing import Callable
import json
import threading
import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from metor.core.api import Delivery, MessageDirectionCode, VoiceFinalizedEvent
from metor.client import FrontendLaunchContext
from metor.data import MessageDirection
from metor.ui.gui.runtime.voice.capture import CaptureWorker
from metor.ui.gui.runtime.voice.press import CaptureBinding
from metor.ui.gui.runtime.voice import PressSource
from metor.ui.gui.runtime.voice.controller import VoiceReview
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Mailbox, Update
from metor.ui.gui.state.media import MediaCache, PlaybackTarget
from metor.ui.gui.runtime.playback.worker import PlaybackWorker
from metor.core.daemon.managed.notify import NotificationPayload, NotificationService


class FiniteMicrophone:
    """Test-only complete PCM source; this does not represent native audio evidence."""

    def __init__(self, frames: list[bytes]) -> None:
        """Keeps a finite deterministic sequence of encoded microphone callbacks."""
        self.frames = deque(frames)
        self.failed = False
        self.opened = False
        self.stopped = False
        self.opened_event = threading.Event()
        self.frame_event = threading.Event()
        self.on_empty: Callable[[], None] = lambda: None

    def start_capture(self, *, headset_confirmed: bool) -> None:
        """Records explicit simulated route admission."""
        if not headset_confirmed:
            raise RuntimeError('Unconfirmed route')
        self.opened = True
        self.opened_event.set()

    def stop_capture(self) -> None:
        """Stops only this test input."""
        self.stopped = True

    def interrupt_capture(self) -> None:
        """Cancels future synthetic callbacks without consuming queued frames."""
        self.stopped = True

    def take_frame(self) -> bytes | None:
        """Returns each complete frame once, then releases the initiating press."""
        if self.frames:
            frame = self.frames.popleft()
            self.frame_event.set()
            return frame
        self.on_empty()
        return None

    def discard_capture(self) -> None:
        """Clears any unaccepted synthetic microphone bytes."""
        self.frames.clear()


class ConcurrentOutput:
    """Controlled complete output that observes, but never replaces, capture work."""

    def __init__(self, capture_running: Callable[[], bool]) -> None:
        """Create a blocked output boundary for deterministic overlap assertions."""
        self.capture_running = capture_running
        self.entered = threading.Event()
        self.release = threading.Event()
        self.frames: list[bytes] = []
        self.capture_was_running = False
        self.stopped = False

    def play_frame(self, frame: bytes, *, headset_confirmed: bool) -> None:
        """Retain one complete frame while the GUI thread remains usable."""
        if not headset_confirmed:
            raise RuntimeError('Unconfirmed route')
        self.capture_was_running = self.capture_running()
        self.frames.append(frame)
        self.entered.set()
        if not self.release.wait(3):
            raise RuntimeError('Controlled output release timed out')

    def stop_output(self) -> None:
        """Record independent output cleanup without touching capture."""
        self.stopped = True


class CaptureIntegrationTests(unittest.TestCase):
    """Uses actual authenticated SDK/Core/persistence and a finite test microphone."""

    def setUp(self) -> None:
        """Creates the encrypted producer fixture without inheriting its tests."""
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        snapshot = self.h.client.runtime_snapshot()
        self.binding = CaptureBinding(
            snapshot.profile_instance_id,
            snapshot.epoch,
            1,
            self.h.onion,
            Delivery.DROP,
            'capture',
        )
        self.mailbox = Mailbox()
        self.cache = MediaCache()

    def run_capture(
        self, frames: list[bytes]
    ) -> tuple[CaptureWorker, FiniteMicrophone, list[Update]]:
        """Runs one finite upload and drains its bounded UI mailbox."""
        audio = FiniteMicrophone(frames)
        worker = CaptureWorker(
            self.h.client, self.h.owner, self.binding, audio, self.mailbox, self.cache
        )
        audio.on_empty = worker.request_stop
        worker.start()
        self.assertTrue(worker.done.wait(10))
        updates = []
        while update := self.mailbox.take():
            updates.append(update)
        return worker, audio, updates

    def test_drop_release_finalizes_one_review_without_committing(self) -> None:
        """Frames share one stable identity and release leaves a protected unsent draft."""
        worker, audio, updates = self.run_capture([b'\x00\x01' * 320] * 3)
        self.assertTrue(audio.opened)
        self.assertTrue(audio.stopped)
        self.assertEqual(worker.accepted_bytes, 1920)
        finished = next(
            update for update in updates if update.operation == 'voice-finished:capture'
        )
        self.assertIsInstance(finished.event, VoiceFinalizedEvent)
        self.assertEqual(finished.event.duration_ms, 60)
        self.assertTrue(all(update.generation == 1 for update in updates))
        record = self.h.messages.get_voice_payload(
            self.h.onion, 'capture', MessageDirection.OUT
        )
        self.assertEqual(record.status, 'draft')
        self.assertEqual(self.h.messages.get_pending_outbox(), [])

    def test_blocked_optional_notification_does_not_delay_media_progress(self) -> None:
        """Sink I/O cannot retain the caller while actual SDK capture advances."""
        entered, release = threading.Event(), threading.Event()
        sink = Mock()
        sink.deliver.side_effect = lambda _payload: (entered.set(), release.wait(10))
        with patch(
            'metor.core.daemon.managed.notify.notification.build_sink',
            return_value=sink,
        ):
            service = NotificationService(
                lambda: json.dumps({'type': 'controlled'}), stop_timeout=0.05
            )
            try:
                service.dispatch(NotificationPayload('inbox_notification'))
                self.assertTrue(entered.wait(1))
                worker, _audio, updates = self.run_capture([b'\x00\x01' * 320])
                self.assertEqual(worker.accepted_bytes, 640)
                self.assertTrue(
                    any(
                        update.operation == 'voice-finished:capture'
                        for update in updates
                    )
                )
                self.assertFalse(release.is_set())
            finally:
                release.set()
                service.close()

    def test_own_live_cache_requires_every_confirmed_source_range(self) -> None:
        """Actual finalization cannot turn a lost append acknowledgement into cached source bytes.

        Args:
            None
        Returns:
            None
        """
        self.binding = replace(self.binding, delivery=Delivery.LIVE)
        payload = b'\x00\x01' * 320
        worker, _audio, _updates = self.run_capture([payload])
        self.assertTrue(worker.completion_confirmed)
        self.assertEqual(self.cache.read(worker.cache_target, 0, 640), (payload, 640))
        self.binding = replace(self.binding, msg_id='lost-live-source')
        original = self.h.client.append_voice

        def lost(*args: object, **kwargs: object) -> None:
            """Drops only the acknowledgement after real Core append acceptance.

            Args:
                args: Exact original append request.
                kwargs: Original producer qualification.
            Returns:
                None
            """
            original(*args, **kwargs)

        with patch.object(self.h.client, 'append_voice', side_effect=lost):
            uncertain, _audio, _updates = self.run_capture([payload])
        self.assertTrue(uncertain.completion_confirmed)
        self.assertEqual(uncertain.accepted_bytes, 640)
        self.assertIsNone(self.cache.complete_size(uncertain.cache_target))

    def test_empty_capture_is_cancelled_without_a_playable_review(self) -> None:
        """Zero accepted audio never produces a finalized review or Send action."""
        _worker, _audio, updates = self.run_capture([])
        self.assertTrue(
            any(update.operation == 'voice-empty:capture' for update in updates)
        )
        self.assertFalse(
            any(update.operation == 'voice-finished:capture' for update in updates)
        )
        self.assertIsNone(self.h.repository.get('capture'))
        self.assertIsNone(
            self.h.messages.get_voice_payload(
                self.h.onion, 'capture', MessageDirection.OUT
            )
        )

    def test_owned_review_playback_uses_real_sdk_without_commit_or_consume(
        self,
    ) -> None:
        """Exact lease-qualified Core preview feeds complete PCM to a synthetic output."""
        self.run_capture([b'\x00\x01' * 320] * 3)
        target = PlaybackTarget(
            self.binding.generation,
            self.binding.profile_instance,
            self.binding.epoch,
            self.h.onion,
            Delivery.DROP,
            MessageDirectionCode.OUT,
            'capture',
            self.h.owner,
        )
        output = Mock()
        worker = PlaybackWorker(
            self.h.client, target, 1, output, self.mailbox, MediaCache()
        )
        worker.start()
        self.assertTrue(worker.done.wait(10))
        self.assertEqual(worker.position, 1920)
        self.assertEqual(output.play_frame.call_count, 3)
        record = self.h.messages.get_voice_payload(
            self.h.onion, 'capture', MessageDirection.OUT
        )
        self.assertEqual(record.status, 'draft')
        self.assertEqual(self.h.messages.get_pending_outbox(), [])

    def test_full_gui_capture_and_sent_playback_overlap_over_real_sdk(self) -> None:
        """Production controllers/workers remain full-duplex through SDK/Core IO."""
        payload = b'\x00\x01' * 320
        self.h.capture('duplex-source')
        self.h.client.finalize_voice('duplex-source', 20, owner_token=self.h.owner)
        self.h.client.commit_voice(
            self.h.onion, 'duplex-source', owner_token=self.h.owner
        )
        controller = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(controller.close)
        controller.client = self.h.client
        controller.state.snapshot = self.h.client.runtime_snapshot()
        controller.state.capabilities = frozenset(self.h.client.init_event.capabilities)
        controller.voice_owner.token = self.h.owner
        controller.state.covered = False
        controller.state.route = Route('V08', self.h.onion, Delivery.DROP)

        microphone = FiniteMicrophone([payload])
        self.assertTrue(controller.voice.configure(microphone, headset_confirmed=True))
        self.assertTrue(controller.voice.down(PressSource.PHYSICAL))
        capture_binding = controller.voice.press.binding
        self.assertIsNotNone(capture_binding)
        assert capture_binding is not None
        self.assertTrue(microphone.opened_event.wait(3))
        self.assertTrue(microphone.frame_event.wait(3))

        output = ConcurrentOutput(lambda: controller.voice.running)
        controller.playback.audio = output
        target = controller.playback.target(
            self.h.onion,
            Delivery.DROP,
            MessageDirectionCode.OUT,
            'duplex-source',
        )
        self.assertIsNotNone(target)
        assert target is not None
        self.assertTrue(controller.playback.play(target))
        self.assertTrue(output.entered.wait(3))
        self.assertTrue(output.capture_was_running)

        controller.state.set_draft(
            self.h.onion, Delivery.DROP, 'Typing remains responsive'
        )
        controller.poll()
        self.assertEqual(
            controller.state.drafts[(self.h.onion, Delivery.DROP)],
            'Typing remains responsive',
        )
        self.assertTrue(controller.voice.running)
        self.assertTrue(controller.playback.running)

        output.release.set()
        assert controller.playback.worker is not None
        self.assertTrue(controller.playback.worker.done.wait(5))
        controller.poll()
        self.assertEqual(b''.join(output.frames), payload)
        self.assertTrue(output.stopped)

        controller.voice.up(PressSource.PHYSICAL)
        assert controller.voice.worker is not None
        self.assertTrue(controller.voice.worker.done.wait(10))
        controller.poll()
        recorded = self.h.messages.get_voice_payload(
            self.h.onion, capture_binding.msg_id, MessageDirection.OUT
        )
        source = self.h.messages.get_voice_payload(
            self.h.onion, 'duplex-source', MessageDirection.OUT
        )
        self.assertEqual(recorded.status, 'draft')
        self.assertEqual(source.status, 'pending')
        self.assertEqual(
            [row[4] for row in self.h.messages.get_pending_outbox()],
            ['duplex-source'],
        )

    def test_lost_append_response_reconciles_without_repeating_the_frame(self) -> None:
        """A committed append with lost response is finalized from exact retained state."""
        original = self.h.client.append_voice
        calls = []

        def lost(*args: object, **kwargs: object) -> None:
            calls.append(args)
            original(*args, **kwargs)
            return None

        with patch.object(self.h.client, 'append_voice', side_effect=lost):
            worker, _audio, updates = self.run_capture([b'\x00\x01' * 320])
        self.assertEqual(len(calls), 1)
        self.assertEqual(worker.accepted_bytes, 640)
        self.assertTrue(
            any(update.operation == 'voice-finished:capture' for update in updates)
        )

    def test_gui_departure_keeps_exact_review_and_requires_release(self) -> None:
        """Navigation finalizes Alice's draft while blocking text and target theft."""
        controller = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(controller.close)
        controller.client = self.h.client
        controller.state.snapshot = self.h.client.runtime_snapshot()
        controller.state.capabilities = frozenset(self.h.client.init_event.capabilities)
        controller.voice_owner.token = self.h.owner
        controller.state.covered = False
        controller.state.route = Route('V08', self.h.onion, Delivery.DROP)
        drained = threading.Event()
        audio = FiniteMicrophone([b'\x00\x01' * 320])
        audio.on_empty = drained.set
        self.assertTrue(controller.voice.configure(audio, headset_confirmed=True))
        self.assertTrue(controller.voice.down(PressSource.PHYSICAL))
        binding = controller.voice.press.binding
        controller.state.set_draft(self.h.onion, Delivery.DROP, 'keep this text')
        controller.send_text(self.h.onion, Delivery.DROP)
        self.assertEqual(controller.text.operations, {})
        self.assertTrue(drained.wait(5))
        controller.navigate(Route('V17'))
        self.assertTrue(controller.voice.worker.done.wait(10))
        controller.poll()
        review = controller.voice.reviews[self.h.onion]
        self.assertEqual(review.binding, binding)
        self.assertEqual(review.size_bytes, 640)
        self.assertEqual(controller.voice.press.phase.value, 'release_required')
        self.assertFalse(controller.voice.down(PressSource.POINTER))
        controller.voice.up(PressSource.PHYSICAL)
        controller.voice.up(PressSource.POINTER)
        self.assertEqual(controller.voice.press.phase.value, 'idle')
        self.assertEqual(self.h.messages.get_pending_outbox(), [])

    def test_unknown_review_commit_reconciles_once_without_resending(self) -> None:
        """A lost commit success cannot enable a duplicate Send or draft cancellation."""
        self.run_capture([b'\x00\x01' * 320])
        controller = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(controller.close)
        controller.client = self.h.client
        controller.state.snapshot = self.h.client.runtime_snapshot()
        controller.state.generation = self.binding.generation
        controller.state.covered = False
        controller.voice_owner.token = self.h.owner
        controller.voice.reviews[self.h.onion] = VoiceReview(self.binding, 640, 20)
        original = self.h.client.commit_voice
        calls = []

        def lost(*args: object, **kwargs: object) -> None:
            calls.append(args)
            original(*args, **kwargs)
            return None

        with patch.object(self.h.client, 'commit_voice', side_effect=lost):
            self.assertTrue(
                controller.voice.review_actions.act(self.h.onion, send=True)
            )
            for _ in range(8):
                worker = controller._worker
                if worker is not None:
                    worker.join(5)
                    self.assertFalse(worker.is_alive())
                controller.poll()
                if not controller.state.busy:
                    break
        self.assertEqual(len(calls), 1)
        self.assertEqual(controller.voice.reviews, {})
        record = self.h.messages.get_voice_payload(
            self.h.onion, 'capture', MessageDirection.OUT
        )
        self.assertEqual(record.status, 'pending')

    def test_finalization_recovery_preserves_owner_and_never_repeats_commit(
        self,
    ) -> None:
        """A lost finalize response is read back without another mutation or target theft.

        Args:
            None
        Returns:
            None
        """
        original = self.h.client.finalize_voice

        def lost(*args: object, **kwargs: object) -> None:
            """Commits through actual Core while hiding only its response.

            Args:
                args: Original request arguments.
                kwargs: Captured owner qualification.
            Returns:
                None
            """
            original(*args, **kwargs)

        with patch.object(
            self.h.client, 'finalize_voice', side_effect=lost
        ) as finalize:
            worker, _audio, updates = self.run_capture([b'\x00\x01' * 320])
            controller = self.failed_controller(worker, updates)
            controller.navigate(Route('V17'))
            self.assertTrue(controller.voice.recovery.retry(self.binding))
            self.assertFalse(controller.voice.recovery.retry(self.binding))
            controller._worker.join(5)
            controller.poll()
        self.assertEqual(finalize.call_count, 1)
        self.assertEqual(controller.voice.reviews[self.h.onion].size_bytes, 640)
        self.assertEqual(controller.state.route.view, 'V17')
        self.assertEqual(controller.voice.press.phase.value, 'release_required')
        self.assertIsNone(controller.voice.press.binding)
        self.assertEqual(self.h.messages.get_pending_outbox(), [])

    def test_explicit_retry_finalizes_only_the_canonical_accepted_prefix(self) -> None:
        """A retry after failed finalization uses retained size and only reads after loss.

        Args:
            None
        Returns:
            None
        """
        with patch.object(self.h.client, 'finalize_voice', return_value=None):
            worker, _audio, updates = self.run_capture([b'\x00\x01' * 320] * 2)
        controller = self.failed_controller(worker, updates)
        original = self.h.client.finalize_voice

        def lost(*args: object, **kwargs: object) -> None:
            """Loses the explicit retry response after Core accepts finalization.

            Args:
                args: Exact message and canonical duration.
                kwargs: Original owner lease.
            Returns:
                None
            """
            original(*args, **kwargs)

        with patch.object(
            self.h.client, 'finalize_voice', side_effect=lost
        ) as finalize:
            self.assertTrue(controller.voice.recovery.retry(self.binding))
            controller._worker.join(5)
            controller.poll()
        finalize.assert_called_once_with('capture', 40, owner_token=self.h.owner)
        self.assertEqual(controller.voice.reviews[self.h.onion].size_bytes, 1280)
        self.assertEqual(self.h.messages.get_pending_outbox(), [])

    def failed_controller(
        self, worker: CaptureWorker, updates: list[Update]
    ) -> GuiController:
        """Installs genuine failed worker results into the original held interaction.

        Args:
            worker: Finished capture with an uncertain finalization result.
            updates: Its actual generation-qualified completions.
        Returns:
            GuiController: Real coordinator retaining the failed binding.
        """
        controller = GuiController(FrontendLaunchContext('voice-owned', Mock()))
        self.addCleanup(controller.close)
        controller.client = self.h.client
        controller.state.snapshot = self.h.client.runtime_snapshot()
        controller.state.generation = self.binding.generation
        controller.state.covered = False
        controller.voice_owner.token = self.h.owner
        controller.voice.worker = worker
        self.assertTrue(
            controller.voice.press.down(PressSource.PHYSICAL, self.binding, True)
        )
        for update in updates:
            controller.voice.install(update)
        self.assertEqual(controller.voice.press.phase.value, 'failed')
        return controller


if __name__ == '__main__':
    unittest.main()
