"""GUI capture workers over real Core IPC with explicitly synthetic microphone frames."""

from collections import deque
from dataclasses import replace
from typing import Callable
import base64
import json
import socket
import threading
import time
import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from metor.client import FrontendProfileState
from metor.core.api import (
    Delivery,
    GuiPreferencesEvent,
    IpcEvent,
    MessageDirectionCode,
    SetGuiPreferencesCommand,
    VoiceFinalizedEvent,
)
from metor.client import FrontendLaunchContext, MetorClient, build_session_auth_proof
from metor.core.daemon.managed.network.router.admission import FrameAdmission
from metor.data import MessageDirection
from metor.ui.gui.platform.audio import PcmVoice
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
from metor.utils import Constants


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
        # A capture may perform more than one real IPC exchange before cleanup.
        self.assertTrue(worker.done.wait(2 * Constants.DEFAULT_IPC_TIMEOUT))
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
        """Incoming LIVE autoplay and local capture overlap through SDK/Core IO."""
        payload = b'\x00\x01' * 320
        foreign_payload = b'\x02\x03' * 320
        local, peer = socket.socketpair()
        foreign_local, foreign_peer = socket.socketpair()
        for connection in (local, peer, foreign_local, foreign_peer):
            self.addCleanup(connection.close)
        self.h.daemon._transport_state.add_active_connection(self.h.onion, local)

        controller = GuiController(
            FrontendLaunchContext(
                'voice-owned',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'voice-owned', True, False, False
                    )
                ),
            )
        )
        self.addCleanup(controller.close)
        provider = Mock()
        provider.get_session_auth_proof.side_effect = lambda challenge, salt: (
            build_session_auth_proof('test-password', challenge, salt)
        )
        generation = controller.state.generation

        def on_event(event: IpcEvent) -> None:
            controller.mailbox.put(Update(generation, 'event', event))

        gui_client = MetorClient(
            self.h.daemon._ipc.port,
            auth_provider=provider,
            on_event=on_event,
        )
        self.addCleanup(gui_client.disconnect)
        initialized = gui_client.bootstrap()
        self.assertIsNotNone(initialized)
        assert initialized is not None
        activation = controller.activation.hydrate(gui_client, initialized)
        self.assertTrue(
            controller.adopt_client(gui_client, controller.state.generation)
        )
        self.assertIsNotNone(activation.owner)
        self.assertIsNotNone(activation.preferences)
        assert activation.owner is not None and activation.preferences is not None
        preferences = gui_client.request(
            SetGuiPreferencesCommand(
                activation.preferences.preferences_revision,
                replace(activation.preferences.preferences, auto_play=True),
            ),
            GuiPreferencesEvent,
        )
        controller.state.snapshot = activation.snapshot
        controller.state.capabilities = frozenset(initialized.capabilities)
        controller.state.preferences = preferences
        controller.voice_owner.token = activation.owner.owner_token
        controller.state.covered = False
        controller.state.route = Route('V09', self.h.onion, Delivery.LIVE)

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
        controller.playback.auto.reconcile()
        self.assertTrue(controller.playback.auto.enabled(self.h.onion))

        router = self.h.daemon._network._router
        voice = router._voice
        self.assertIsNotNone(voice)
        assert voice is not None
        self.assertIs(
            voice.receive_begin(
                local,
                self.h.onion,
                {'id': 'inbound-live', 'codec': PcmVoice.CODEC},
                Delivery.LIVE,
            ),
            FrameAdmission.ACCEPTED,
        )
        foreign_onion = 'c' * len(self.h.onion)
        self.h.contacts.ensure_alias_for_onion(foreign_onion)
        self.assertIs(
            voice.receive_begin(
                foreign_local,
                foreign_onion,
                {'id': 'foreign-live', 'codec': PcmVoice.CODEC},
                Delivery.LIVE,
            ),
            FrameAdmission.ACCEPTED,
        )
        text_envelope = base64.b64encode(
            json.dumps(
                {'id': 'parallel-text', 'text': 'Incoming while talking'}
            ).encode()
        ).decode()
        self.assertIs(
            router.process_incoming_msg(
                local, self.h.onion, 'parallel-text', text_envelope
            ),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            voice.receive_chunk(
                foreign_local,
                foreign_onion,
                {
                    'id': 'foreign-live',
                    'offset': 0,
                    'data': base64.b64encode(foreign_payload).decode(),
                },
            ),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            voice.receive_chunk(
                local,
                self.h.onion,
                {
                    'id': 'inbound-live',
                    'offset': 0,
                    'data': base64.b64encode(payload).decode(),
                },
            ),
            FrameAdmission.ACCEPTED,
        )

        deadline = time.monotonic() + 5
        while not output.entered.is_set() and time.monotonic() < deadline:
            controller.poll()
            time.sleep(0.01)
        self.assertTrue(output.entered.is_set())
        self.assertTrue(output.capture_was_running)
        capture_worker = controller.voice.worker
        self.assertIsNotNone(capture_worker)
        assert capture_worker is not None
        self.assertEqual(capture_worker.accepted_bytes, len(payload))
        self.assertEqual(output.frames, [payload])

        controller.state.set_draft(
            self.h.onion, Delivery.LIVE, 'Typing remains responsive'
        )
        controller.poll()
        self.assertEqual(
            controller.state.drafts[(self.h.onion, Delivery.LIVE)],
            'Typing remains responsive',
        )

        transcript = controller.transcript.items
        voice_key = (
            self.h.onion,
            Delivery.LIVE,
            MessageDirectionCode.IN,
            'inbound-live',
        )
        text_key = (
            self.h.onion,
            Delivery.LIVE,
            MessageDirectionCode.IN,
            'parallel-text',
        )
        self.assertIn(voice_key, transcript)
        self.assertIn(text_key, transcript)
        self.assertLess(transcript[voice_key].order, transcript[text_key].order)
        self.assertTrue(controller.voice.running)
        self.assertTrue(controller.playback.running)

        self.assertIs(
            voice.receive_end(
                foreign_local,
                foreign_onion,
                {'id': 'foreign-live', 'size': len(foreign_payload), 'duration_ms': 20},
            ),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            voice.receive_end(
                local,
                self.h.onion,
                {'id': 'inbound-live', 'size': len(payload), 'duration_ms': 20},
            ),
            FrameAdmission.ACCEPTED,
        )
        output.release.set()
        assert controller.playback.worker is not None
        self.assertTrue(controller.playback.worker.done.wait(5))
        controller.poll()
        self.assertEqual(b''.join(output.frames), payload)
        self.assertTrue(output.stopped)
        self.assertTrue(controller.voice.running)
        self.assertIsNone(
            self.h.messages.get_inbound_voice(self.h.onion, 'inbound-live')
        )
        self.assertIsNotNone(
            self.h.messages.get_inbound_voice(foreign_onion, 'foreign-live')
        )

        controller.voice.up(PressSource.PHYSICAL)
        assert controller.voice.worker is not None
        self.assertTrue(controller.voice.worker.done.wait(10))
        controller.poll()
        recorded = self.h.messages.get_voice_payload(
            self.h.onion, capture_binding.msg_id, MessageDirection.OUT
        )
        self.assertEqual(recorded.delivery, Delivery.LIVE.value)
        self.assertTrue(json.loads(recorded.payload)['finalized'])
        self.assertEqual(
            controller.state.drafts[(self.h.onion, Delivery.LIVE)],
            'Typing remains responsive',
        )

        self.assertIs(
            voice.receive_begin(
                local,
                self.h.onion,
                {'id': 'after-lock', 'codec': PcmVoice.CODEC},
                Delivery.LIVE,
            ),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            voice.receive_chunk(
                local,
                self.h.onion,
                {
                    'id': 'after-lock',
                    'offset': 0,
                    'data': base64.b64encode(foreign_payload).decode(),
                },
            ),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            voice.receive_end(
                local,
                self.h.onion,
                {'id': 'after-lock', 'size': len(foreign_payload), 'duration_ms': 20},
            ),
            FrameAdmission.ACCEPTED,
        )
        controller.suspend()
        self.assertTrue(controller.state.covered)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            controller.poll()
            time.sleep(0.01)
        self.assertFalse(controller.playback.running)
        self.assertFalse(controller.playback.auto.queue)
        self.assertEqual(output.frames, [payload])
        self.assertIsNotNone(
            self.h.messages.get_inbound_voice(self.h.onion, 'after-lock')
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

    def test_microphone_failure_finalizes_only_the_real_accepted_prefix(self) -> None:
        """Input loss closes the port and preserves only bytes confirmed by Core."""
        audio = FiniteMicrophone([b'\x00\x01' * 320])
        worker = CaptureWorker(
            self.h.client,
            self.h.owner,
            self.binding,
            audio,
            self.mailbox,
            self.cache,
        )
        audio.on_empty = lambda: setattr(audio, 'failed', True)

        worker.start()

        self.assertTrue(worker.done.wait(10))
        self.assertEqual(worker.accepted_bytes, 640)
        self.assertTrue(audio.stopped)
        record = self.h.messages.get_voice_payload(
            self.h.onion, self.binding.msg_id, MessageDirection.OUT
        )
        metadata = json.loads(record.payload)
        self.assertTrue(metadata['finalized'])
        self.assertEqual(metadata['size_bytes'], 640)

    def test_gui_departure_keeps_exact_review_and_requires_release(self) -> None:
        """Navigation finalizes Alice's draft while blocking text and target theft."""
        controller = GuiController(
            FrontendLaunchContext(
                'voice-owned',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'voice-owned', True, False, False
                    )
                ),
            )
        )
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
        controller = GuiController(
            FrontendLaunchContext(
                'voice-owned',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'voice-owned', True, False, False
                    )
                ),
            )
        )
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
        controller = GuiController(
            FrontendLaunchContext(
                'voice-owned',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'voice-owned', True, False, False
                    )
                ),
            )
        )
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
