"""Telephone presentation and simulated duplex-port evidence without acoustic claims."""

import base64
from dataclasses import replace
import threading
import time
import unittest
from unittest.mock import Mock, patch

from metor.client import FrontendLaunchContext
from metor.core.api import (
    CallAudioEvent,
    CallAudioFrame,
    CallAudioSentEvent,
    CallInfo,
    CallState,
    CallStateEvent,
    CallsStateEvent,
)
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.platform.call_audio import CallHeadsetAudio
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.calls.media import CallMediaWorker
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Mailbox, Update


class PhonePresentationTests(unittest.TestCase):
    """Exact typed Call controls preserve DROP/LIVE routes and require explicit media consent."""

    def setUp(self) -> None:
        """Creates inert presentation and a captured public request boundary."""
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.gui.simulator = False
        self.gui.state.covered = False
        self.gui.state.route = Route('V08', 'bob')
        self.gui.state.capabilities = frozenset({'calls'})
        self.gui.client = Mock()
        self.gui.voice.headset_confirmed = True
        self.gui.voice.routes.input = 1
        self.gui.voice.routes.output = 2
        self.operations: list[tuple[str, object]] = []

        def submit(operation, work, **kwargs):
            self.operations.append((operation, work))
            return True

        self.gui.submit = submit
        self.calls = self.gui.calls

    def test_start_accept_and_hangup_never_navigate_or_open_chat(self) -> None:
        """Phone lifecycle has exact separate identities while the selected DROP stays fixed."""
        before = self.gui.state.route
        self.assertTrue(self.calls.start('bob'))
        operation, work = self.operations.pop()
        work()
        self.gui.client.start_call.assert_called_once()
        identity = self.gui.client.start_call.call_args.args[1]
        self.calls.install(
            Update(
                0,
                operation,
                CallStateEvent(
                    CallInfo(identity, 'bob', 'Bob', CallState.OUTGOING, owned=True)
                ),
            )
        )
        self.assertEqual(self.gui.state.route, before)
        self.calls.observe(
            CallStateEvent(
                CallInfo(identity, 'bob', 'Bob', CallState.ACTIVE, owned=True)
            )
        )
        self.assertTrue(self.calls.end())
        self.operations[-1][1]()
        self.gui.client.hangup_call.assert_called_once_with(identity)
        self.assertEqual(self.gui.state.route, before)
        self.gui.client.request.assert_not_called()

    def test_broadcast_does_not_grant_same_client_media(self) -> None:
        """Another client's accepted Call cannot open this client's microphone."""
        self.calls.observe(
            CallStateEvent(CallInfo('other', 'bob', 'Bob', CallState.ACTIVE))
        )
        self.assertFalse(self.calls.active)
        with patch('metor.ui.gui.runtime.calls.controller.CallMediaWorker') as worker:
            self.calls.poll()
        worker.assert_not_called()

    def test_other_client_acceptance_closes_stale_incoming_controls(self) -> None:
        """A Call accepted elsewhere revokes this client's incoming Accept affordance."""
        incoming = CallInfo('shared', 'bob', 'Bob', CallState.INCOMING)
        accepted_elsewhere = replace(incoming, state=CallState.ACTIVE)
        self.calls.observe(CallStateEvent(incoming))
        self.assertTrue(self.calls.visible)
        self.calls.observe(CallStateEvent(accepted_elsewhere))
        self.assertIsNone(self.calls.current)
        self.assertFalse(self.calls.visible)
        self.assertFalse(self.calls.accept('shared'))
        self.calls.install(
            Update(0, 'call-snapshot', CallsStateEvent([accepted_elsewhere]))
        )
        with patch('metor.ui.gui.runtime.calls.controller.CallMediaWorker') as worker:
            self.calls.poll()
        worker.assert_not_called()
        self.gui.client.accept_call.assert_not_called()
        self.assertIsNone(self.calls.current)

    def test_unowned_broadcast_does_not_revoke_confirmed_owned_call(self) -> None:
        """An unprojected broadcast requests reconciliation of existing owned authority."""
        owned = CallInfo('owned', 'bob', 'Bob', CallState.ACTIVE, owned=True)
        self.calls.observe(CallStateEvent(owned))
        self.calls.observe(CallStateEvent(replace(owned, owned=False)))
        self.assertTrue(self.calls.active)
        self.assertIs(self.calls.current, owned)
        self.assertEqual(self.calls._snapshot_at, 0.0)

    def test_locked_acceptance_requires_separate_call_permission(self) -> None:
        """App-Lock has no LIVE exception; Call-only permission is exact and explicit."""
        self.gui.state.covered = True
        self.calls.observe(
            CallStateEvent(CallInfo('incoming', 'bob', 'Bob', CallState.INCOMING))
        )
        self.assertFalse(self.calls.accept('incoming'))
        self.gui.client.accept_call.assert_not_called()
        self.assertFalse(self.calls.accept('replacement'))

    def test_mute_survives_locked_snapshot_and_system_suspend_stops(self) -> None:
        """App-Lock retains accepted Call state; actual suspend explicitly ends it."""
        current = CallInfo(
            'active', 'bob', 'Bob', CallState.ACTIVE, muted=True, owned=True
        )
        self.calls.observe(CallStateEvent(current))
        self.gui.state.covered = True
        self.calls.install(
            Update(0, 'call-snapshot', CallsStateEvent([replace(current)]))
        )
        self.assertTrue(self.calls.active)
        self.assertTrue(self.calls.current.muted)
        worker = Mock(done=Mock(is_set=lambda: False))
        self.calls.worker = worker
        self.calls.suspend()
        worker.stop.assert_called_once()
        self.assertIsNone(self.calls.current)

    def test_suspend_tombstone_blocks_late_active_state(self) -> None:
        """Unknown hangup cannot reconstruct microphone/output from a delayed snapshot."""
        active = CallInfo('suspended', 'bob', 'Bob', CallState.ACTIVE, owned=True)
        self.calls.observe(CallStateEvent(active))
        self.calls.suspend()
        self.calls.observe(CallStateEvent(replace(active)))
        self.calls.install(
            Update(0, 'call-snapshot', CallsStateEvent([replace(active)]))
        )
        with patch('metor.ui.gui.runtime.calls.controller.CallMediaWorker') as worker:
            self.calls.poll()
        worker.assert_not_called()
        self.assertIsNone(self.calls.current)
        self.assertFalse(self.calls.active)

    def test_snapshot_prefers_current_call_over_ended_history(self) -> None:
        """Old owned sessions neither reopen controls nor hide a fresh incoming request."""
        ended = CallInfo('old', 'bob', 'Bob', CallState.ENDED, owned=True)
        incoming = CallInfo('new', 'bob', 'Bob', CallState.INCOMING)
        self.calls.install(Update(0, 'call-snapshot', CallsStateEvent([ended])))
        self.assertIsNone(self.calls.current)
        self.assertFalse(self.calls.visible)
        self.calls.install(
            Update(0, 'call-snapshot', CallsStateEvent([ended, incoming]))
        )
        self.assertEqual(self.calls.current.call_id, 'new')
        self.assertTrue(self.calls.visible)

    def test_duplicate_call_metadata_does_not_reopen_dismissed_controls(self) -> None:
        """Repeated lifecycle events and refreshes preserve a deliberate dismissal."""
        for phase in (CallState.INCOMING, CallState.ACTIVE, CallState.ENDED):
            with self.subTest(phase=phase):
                current = CallInfo('same', 'bob', 'Bob', phase, owned=True)
                self.calls.observe(CallStateEvent(current))
                self.calls.visible = False
                revision = self.calls.revision
                self.calls.observe(CallStateEvent(replace(current)))
                self.calls.install(
                    Update(0, 'call-snapshot', CallsStateEvent([replace(current)]))
                )
                self.assertFalse(self.calls.visible)
                self.assertEqual(self.calls.revision, revision)

    def test_missing_audio_does_not_create_an_idle_call_overlay_or_request(
        self,
    ) -> None:
        """Audio setup remains an explicit view-level modal without a phantom phone call."""
        self.gui.voice.headset_confirmed = False
        before = self.gui.state.feedback.revision
        self.assertFalse(self.calls.start('bob'))
        self.assertIsNone(self.calls.current)
        self.assertFalse(self.calls.visible)
        self.assertFalse(self.calls.media_active)
        self.assertEqual(self.operations, [])
        self.assertEqual(self.gui.state.feedback.revision, before)
        self.gui.client.start_call.assert_not_called()

    def test_call_specific_failure_is_visible_without_duplicate_app_feedback(
        self,
    ) -> None:
        """An explicit unsupported phone action reports only in its own Call controls."""
        self.gui.state.capabilities = frozenset()
        before = self.gui.state.feedback.revision
        self.assertFalse(self.calls.start('bob'))
        self.assertTrue(self.calls.visible)
        self.assertEqual(self.calls.status, 'Calls are unavailable')
        self.assertEqual(self.gui.state.feedback.revision, before)
        self.assertEqual(self.operations, [])

    def test_unknown_send_does_not_repeat_or_open_audio(self) -> None:
        """A timeout leads to status reconciliation rather than automatic re-calling."""
        self.assertTrue(self.calls.start('bob'))
        operation = self.operations[0][0]
        self.calls.install(Update(0, operation))
        self.calls.poll()
        self.assertEqual(
            len([item for item in self.operations if item[0].startswith('call:start')]),
            1,
        )
        self.assertFalse(self.calls.media_active)


class SimulatedDuplexPort:
    """Named test port proving concurrent adapter direction ownership only."""

    def __init__(self) -> None:
        """Creates fixed bounded synthetic PCM, with no physical input device."""
        self.failed = False
        self.capture = threading.Event()
        self.frame = b'\0' * PcmVoice.FRAME_BYTES
        self.input_frames = 3
        self.played = 0
        self.duplex_observed = False

    def start_capture(self, *, headset_confirmed: bool) -> None:
        """Opens synthetic capture after explicit controller admission."""
        assert headset_confirmed
        self.capture.set()

    def take_frame(self) -> bytes | None:
        """Produces a finite count of synthetic complete frames."""
        if self.input_frames:
            self.input_frames -= 1
            return self.frame
        return None

    def interrupt_capture(self) -> None:
        """Revokes synthetic capture immediately."""
        self.capture.clear()

    def stop_capture(self) -> None:
        """Stops only the input direction."""
        self.capture.clear()

    def discard_capture(self) -> None:
        """Has no retained input to release."""

    def play_frame(self, frame: bytes, *, headset_confirmed: bool) -> None:
        """Checks independent playback while capture remains active."""
        assert headset_confirmed and frame == self.frame
        self.duplex_observed |= self.capture.is_set()
        self.played += 1
        time.sleep(PcmVoice.FRAME_SECONDS)

    def stop_output(self) -> None:
        """Has no physical output resource to release."""


class PhoneAudioAdapterTests(unittest.TestCase):
    """Bounded expiring native handoff and simultaneous public-SDK adapter requests."""

    def test_expired_capture_dropped_and_native_queue_bounded(self) -> None:
        """A delayed consumer never receives a long microphone recording backlog."""
        adapter = CallHeadsetAudio(1, 2)
        frame = b'\0' * PcmVoice.FRAME_BYTES
        with patch('metor.ui.gui.platform.call_audio.time.monotonic', return_value=0):
            for _ in range(50):
                adapter._received(frame, PcmVoice.FRAME_SAMPLES, None, None)
        self.assertEqual(len(adapter._realtime_frames), 10)
        with patch('metor.ui.gui.platform.call_audio.time.monotonic', return_value=1):
            self.assertIsNone(adapter.take_frame())
        self.assertFalse(adapter._realtime_frames)

    def test_full_duplex_workers_send_and_receive_without_voice_messages(self) -> None:
        """Separate workers process both directions without publication or persistent staging."""
        audio, client = SimulatedDuplexPort(), Mock()
        count = 0

        def send(call_id, sequence, data):
            self.assertEqual(base64.b64decode(data), audio.frame)
            return CallAudioSentEvent(call_id, sequence + 1)

        def read(call_id, max_frames):
            nonlocal count
            count += 1
            return CallAudioEvent(
                call_id, [CallAudioFrame(count, base64.b64encode(audio.frame).decode())]
            )

        client.send_call_audio = Mock(side_effect=send)
        client.read_call_audio = Mock(side_effect=read)
        worker = CallMediaWorker(client, 'phone', audio, Mailbox(), 0)
        worker.start()
        deadline = time.monotonic() + 2
        while (
            audio.played < 3 or client.send_call_audio.call_count < 3
        ) and time.monotonic() < deadline:
            time.sleep(PcmVoice.FRAME_SECONDS)
        worker.stop()
        self.assertTrue(worker.done.wait(2))
        self.assertEqual(client.send_call_audio.call_count, 3)
        self.assertGreaterEqual(audio.played, 3)
        self.assertTrue(audio.duplex_observed)
        client.start_voice.assert_not_called()
        client.hangup_call.assert_not_called()

    def test_pulled_audio_expires_during_blocked_output(self) -> None:
        """A stalled physical write cannot turn its remaining fetched batch into backlog."""
        audio, client = SimulatedDuplexPort(), Mock()
        completed = threading.Event()
        original = audio.play_frame

        def slow(frame, *, headset_confirmed):
            original(frame, headset_confirmed=headset_confirmed)
            time.sleep(0.25)
            completed.set()

        audio.play_frame = slow
        payload = base64.b64encode(audio.frame).decode()
        client.send_call_audio.side_effect = lambda call_id, sequence, data: (
            CallAudioSentEvent(call_id, sequence + 1)
        )
        client.read_call_audio.side_effect = [
            CallAudioEvent(
                'phone', [CallAudioFrame(index, payload) for index in range(4)]
            ),
            *[CallAudioEvent('phone') for _ in range(100)],
        ]
        worker = CallMediaWorker(client, 'phone', audio, Mailbox(), 0)
        worker.start()
        self.assertTrue(completed.wait(2))
        time.sleep(PcmVoice.FRAME_SECONDS)
        worker.stop()
        self.assertTrue(worker.done.wait(2))
        self.assertEqual(audio.played, 1)

    def test_initial_mute_prevents_capture_and_still_receives_audio(self) -> None:
        """A persisted microphone mute never blocks the separate output direction."""
        audio, client = SimulatedDuplexPort(), Mock()
        client.read_call_audio.return_value = CallAudioEvent(
            'phone', [CallAudioFrame(1, base64.b64encode(audio.frame).decode())]
        )
        worker = CallMediaWorker(client, 'phone', audio, Mailbox(), 0, muted=True)
        worker.start()
        deadline = time.monotonic() + 2
        while audio.played < 1 and time.monotonic() < deadline:
            time.sleep(PcmVoice.FRAME_SECONDS)
        worker.stop()
        self.assertTrue(worker.done.wait(2))
        self.assertEqual(audio.played, 1)
        self.assertFalse(audio.capture.is_set())
        client.send_call_audio.assert_not_called()
