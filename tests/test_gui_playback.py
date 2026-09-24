"""Playback safety tests with deterministic encoded sources and explicit synthetic output."""

import base64
import threading
import struct
import unittest
from unittest.mock import Mock

from metor.client import FrontendProfileState
from metor.core.api import (
    Delivery,
    MessageDirectionCode,
    VoiceDataEvent,
    VoiceReleasedEvent,
    GuiPreferences,
    GuiPreferencesEvent,
    LiveContextEntry,
    RuntimeSnapshotEvent,
    VoiceIncomingStartedEvent,
)
from metor.client import FrontendLaunchContext
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.runtime.playback.worker import PlaybackWorker
from metor.ui.gui.state.mailbox import Mailbox
from metor.ui.gui.state.media import MediaCache, PlaybackTarget
from metor.ui.gui.state.media.envelope import PcmEnvelope


class PlaybackTests(unittest.TestCase):
    """Checks consumption, byte bounds, stopped requests and incomplete sources."""

    def setUp(self) -> None:
        """Creates a private synthetic exact source and a bounded test output collector."""
        self.target = PlaybackTarget(
            1,
            'instance',
            'epoch',
            'peer',
            Delivery.LIVE,
            MessageDirectionCode.IN,
            'voice',
        )
        self.client = Mock()
        self.audio = Mock()
        self.mailbox = Mailbox()
        self.cache = MediaCache()
        self.payload = b'\x01\x00' * 960
        self.client.release_voice.return_value = VoiceReleasedEvent(
            'Peer', 'voice', 'peer'
        )

    def event(
        self, *, complete: bool = True, codec: str = PcmVoice.CODEC
    ) -> VoiceDataEvent:
        """Builds one explicit canonical range for a test-only SDK response."""
        return VoiceDataEvent(
            'Peer',
            'voice',
            MessageDirectionCode.IN,
            Delivery.LIVE,
            codec,
            0,
            len(self.payload),
            len(self.payload),
            base64.b64encode(self.payload).decode('ascii'),
            complete,
            onion='peer',
        )

    def run_worker(self, *, offset: int = 0) -> PlaybackWorker:
        """Runs a finite output operation and requires timely completion."""
        worker = PlaybackWorker(
            self.client,
            self.target,
            1,
            self.audio,
            self.mailbox,
            self.cache,
            offset=offset,
        )
        worker.start()
        self.assertTrue(worker.done.wait(3))
        return worker

    def test_complete_output_drains_before_exact_release_and_cached_replay(
        self,
    ) -> None:
        """Only finalized full output can consume; cached replay does not release twice."""
        order = []
        self.client.get_voice_chunk.return_value = self.event()
        self.audio.stop_output.side_effect = lambda: order.append('drain')
        self.client.release_voice.side_effect = lambda *args: (
            order.append('release') or VoiceReleasedEvent('Peer', 'voice', 'peer')
        )
        worker = self.run_worker()
        self.assertEqual(worker.position, len(self.payload))
        self.assertEqual(order[:2], ['drain', 'release'])
        self.client.release_voice.assert_called_once_with('peer', 'voice')
        self.assertEqual(
            b''.join(call.args[0] for call in self.audio.play_frame.call_args_list),
            self.payload,
        )
        self.run_worker()
        self.assertEqual(self.client.get_voice_chunk.call_count, 1)
        self.assertEqual(self.client.release_voice.call_count, 1)

    def test_output_failure_and_unsupported_codec_never_consume(self) -> None:
        """Neither a fetched source nor a failed speaker write counts as playback."""
        self.client.get_voice_chunk.return_value = self.event()
        self.audio.play_frame.side_effect = RuntimeError('Output unplugged')
        self.run_worker()
        self.client.release_voice.assert_not_called()
        self.cache = MediaCache()
        self.client.get_voice_chunk.return_value = self.event(codec='unsupported')
        self.audio.reset_mock()
        self.run_worker()
        self.audio.play_frame.assert_not_called()
        self.client.release_voice.assert_not_called()

    def test_departure_during_sdk_read_cannot_start_output(self) -> None:
        """An in-flight read returning after navigation cannot make old audio audible."""
        entered, release = threading.Event(), threading.Event()

        def read(*args: object, **kwargs: object) -> VoiceDataEvent:
            entered.set()
            self.assertTrue(release.wait(3))
            return self.event()

        self.client.get_voice_chunk.side_effect = read
        worker = PlaybackWorker(
            self.client, self.target, 1, self.audio, self.mailbox, self.cache
        )
        worker.start()
        self.assertTrue(entered.wait(3))
        worker.stop()
        release.set()
        self.assertTrue(worker.done.wait(3))
        self.audio.play_frame.assert_not_called()
        self.client.release_voice.assert_not_called()

    def test_jump_does_not_fabricate_full_listening_coverage(self) -> None:
        """Playing a finalized tail from cache leaves the unheard prefix unresolved."""
        self.cache.append(self.target, 0, self.payload, complete=True)
        self.run_worker(offset=PcmVoice.FRAME_BYTES)
        self.client.release_voice.assert_not_called()
        self.assertEqual(
            b''.join(call.args[0] for call in self.audio.play_frame.call_args_list),
            self.payload[PcmVoice.FRAME_BYTES :],
        )

    def test_paused_prefix_and_later_tail_union_release_once(self) -> None:
        """A drained prefix survives pause; a later complete tail fills the actual coverage gap."""
        self.cache.append(self.target, 0, self.payload, complete=True)
        worker = PlaybackWorker(
            self.client, self.target, 1, self.audio, self.mailbox, self.cache
        )
        self.audio.play_frame.side_effect = lambda *_args, **_kwargs: worker.stop()
        worker.start()
        self.assertTrue(worker.done.wait(3))
        self.assertEqual(worker.position, PcmVoice.FRAME_BYTES)
        self.client.release_voice.assert_not_called()
        self.audio.play_frame.side_effect = None
        self.run_worker(offset=PcmVoice.FRAME_BYTES)
        self.client.release_voice.assert_called_once_with('peer', 'voice')

    def test_failed_drain_does_not_add_prefix_coverage(self) -> None:
        """Native drain failure cannot count previously submitted frames toward consumption."""
        self.cache.append(self.target, 0, self.payload, complete=True)
        self.audio.stop_output.side_effect = RuntimeError('Driver loss')
        self.run_worker()
        self.audio.stop_output.side_effect = None
        self.run_worker(offset=PcmVoice.FRAME_BYTES)
        self.client.release_voice.assert_not_called()

    def test_evicted_released_source_is_not_refetched(self) -> None:
        """A bounded release receipt prevents replay from reconstructing erased Core bytes."""
        self.cache.append(self.target, 0, self.payload, complete=True)
        self.run_worker()
        self.cache.discard(self.target)
        self.client.get_voice_chunk.reset_mock()
        self.audio.play_frame.reset_mock()
        self.run_worker()
        self.client.get_voice_chunk.assert_not_called()
        self.audio.play_frame.assert_not_called()

    def test_sparse_coverage_pressure_forgets_ranges_without_filling_gaps(self) -> None:
        """Fragment limits remain finite and never turn gaps into heard audio."""
        coverage = self.cache.coverage
        for index in range(GuiLimits.PLAYBACK_COVERAGE_PER_ITEM + 1):
            coverage.add(self.target, index * 4, index * 4 + 2)
        self.assertFalse(coverage.complete(self.target, 514))
        self.assertLessEqual(
            len(coverage._items[self.target]), GuiLimits.PLAYBACK_COVERAGE_PER_ITEM
        )
        coverage.add(self.target, 0, 514)
        self.assertTrue(coverage.complete(self.target, 514))
        self.cache.clear()
        coverage.add(self.target, 0, 514)
        self.assertFalse(coverage.complete(self.target, 514))

    def test_incomplete_edge_waits_without_consuming_and_cache_is_bounded(self) -> None:
        """An arriving edge stays unconsumed and closed caches reject late workers."""
        worker = PlaybackWorker(
            self.client, self.target, 1, self.audio, self.mailbox, self.cache
        )
        event = self.event(complete=False)
        edge = VoiceDataEvent(
            'Peer',
            'voice',
            MessageDirectionCode.IN,
            Delivery.LIVE,
            PcmVoice.CODEC,
            len(self.payload),
            len(self.payload),
            len(self.payload),
            '',
            False,
            onion='peer',
        )

        def read(*args: object, **kwargs: object) -> VoiceDataEvent:
            if args[3]:
                worker.stop()
                return edge
            return event

        self.client.get_voice_chunk.side_effect = read
        worker.start()
        self.assertTrue(worker.done.wait(3))
        self.client.release_voice.assert_not_called()
        self.assertFalse(
            self.cache.append(
                self.target,
                len(self.payload),
                b'x' * GuiLimits.MEDIA_CACHE_BYTES,
                complete=True,
            )
        )
        self.assertIsNone(self.cache.read(self.target, 0, 640))
        self.cache.clear()
        self.assertFalse(self.cache.append(self.target, 0, self.payload, complete=True))

    def test_envelope_coarsens_real_peaks_and_indexed_seek_preserves_bytes(
        self,
    ) -> None:
        """Long bounded sources retain actual amplitudes and exact random-access PCM slices."""
        envelope = PcmEnvelope()
        payload = struct.pack('<h', -32768) * PcmVoice.FRAME_SAMPLES
        envelope.append(0, payload)
        far = PcmVoice.FRAME_BYTES * GuiLimits.WAVEFORM_BINS * 4
        envelope.append(far, struct.pack('<h', 16384))
        stride, peaks = envelope.snapshot()
        self.assertEqual(len(peaks), GuiLimits.WAVEFORM_BINS)
        self.assertEqual(peaks[0], 32768)
        self.assertEqual(peaks[far // stride], 16384)
        self.assertIsNone(peaks[1])
        for index in range(160):
            self.cache.append(
                self.target, index * len(payload), payload, complete=index == 159
            )
        for position in (0, 2, 639 * 2, 159 * len(payload) + 2):
            data, size = self.cache.read(self.target, position, 16)
            self.assertEqual(size, 160 * len(payload))
            self.assertEqual(data, (payload * 160)[position : position + len(data)])
        self.client.release_voice.assert_not_called()
        self.cache.discard(self.target)
        self.assertEqual(self.cache.envelope(self.target), (0, ()))

    def test_tiny_source_fragments_have_bounded_index_and_exact_immutable_reads(
        self,
    ) -> None:
        """One-sample fragments cannot amplify the replay cache into millions of objects.

        Args:
            None
        Returns:
            None
        """
        extent = GuiLimits.MEDIA_CACHE_BLOCK_BYTES + PcmVoice.SAMPLE_BYTES
        for offset in range(0, extent, PcmVoice.SAMPLE_BYTES):
            self.assertTrue(
                self.cache.append(
                    self.target, offset, b'\x01\x7f', complete=offset + 2 == extent
                )
            )
        self.assertEqual(len(self.cache._items[self.target]), 2)
        self.assertEqual(
            self.cache._offsets[self.target], [0, GuiLimits.MEDIA_CACHE_BLOCK_BYTES]
        )
        for offset in (
            0,
            GuiLimits.MEDIA_CACHE_BLOCK_BYTES - 2,
            GuiLimits.MEDIA_CACHE_BLOCK_BYTES,
        ):
            data, size = self.cache.read(
                self.target, offset, GuiLimits.MEDIA_CACHE_BLOCK_BYTES
            )
            self.assertIs(type(data), bytes)
            self.assertEqual(size, extent)
            self.assertEqual(data, b'\x01\x7f' * (len(data) // 2))
        self.client.release_voice.assert_not_called()


class AutoPlaybackTests(unittest.TestCase):
    """Checks foreground boundaries and one-time logical-context preference inheritance."""

    def setUp(self) -> None:
        """Creates an inert GUI with synthetic public context descriptors."""
        self.gui = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture', True, False, False
                    )
                ),
            )
        )
        self.gui.state.covered = False
        self.gui.state.route = Route('V09', 'peer', Delivery.LIVE)
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            '',
            epoch='epoch',
            profile_instance_id='instance',
            live_contexts=[
                LiveContextEntry(
                    'Peer', 'peer', True, 'connected', context_generation=1
                )
            ],
        )
        self.gui.state.preferences = GuiPreferencesEvent(
            'instance', preferences=GuiPreferences(auto_play=True)
        )
        self.gui.playback.audio = Mock()
        self.auto = self.gui.playback.auto
        self.auto.reconcile()

    def start(self, identity: str) -> None:
        """Publishes an explicitly new incoming turn for the foreground fixture peer."""
        self.auto.incoming(
            VoiceIncomingStartedEvent(
                'Peer', identity, Delivery.LIVE, PcmVoice.CODEC, 0, 'peer'
            )
        )

    def test_default_copied_once_recovery_keeps_override_and_new_context_resets(
        self,
    ) -> None:
        """A protected default change cannot silently change a current context override."""
        self.assertTrue(self.auto.enabled('peer'))
        self.auto.toggle('peer')
        self.auto.reconcile()
        self.assertFalse(self.auto.enabled('peer'))
        self.gui.state.snapshot.live_contexts[0].session_state = 'reconnecting'
        self.auto.reconcile()
        self.assertFalse(self.auto.enabled('peer'))
        self.gui.state.snapshot.live_contexts[0].context_generation = 2
        self.auto.reconcile()
        self.assertTrue(self.auto.enabled('peer'))

    def test_focus_navigation_and_manual_playback_leave_backlog_silent(self) -> None:
        """Only a start while currently eligible may queue automatic output."""
        self.auto.focused = False
        self.start('background')
        self.assertFalse(self.auto.queue)
        self.auto.focused = True
        self.start('fresh')
        self.assertEqual(len(self.auto.queue), 1)
        self.gui.playback.stop()
        self.assertFalse(self.auto.queue)
        self.auto.manual = True
        self.gui.playback.worker = Mock()
        self.gui.playback.worker.done.is_set.return_value = False
        self.start('during-manual')
        self.assertFalse(self.auto.queue)

    def test_old_context_queue_cannot_play_into_a_new_generation(self) -> None:
        """A stale queued start cannot cross a terminal context replacement."""
        self.start('old-context')
        self.assertEqual(len(self.auto.queue), 1)
        self.gui.state.snapshot.live_contexts[0].context_generation = 2
        self.gui.playback.play = Mock()
        self.auto.poll()
        self.gui.playback.play.assert_not_called()

    def test_incoming_output_remains_eligible_during_local_capture(self) -> None:
        """A held local PTT worker never imposes a half-duplex output gate.

        Args:
            None
        Returns:
            None
        """
        self.gui.voice.worker = Mock()
        self.gui.voice.worker.done.is_set.return_value = False
        self.gui.playback.play = Mock(return_value=True)
        self.start('duplex')
        self.assertEqual(len(self.auto.queue), 1)
        self.auto.poll()
        self.gui.playback.play.assert_called_once()
        target = self.gui.playback.play.call_args.args[0]
        self.assertEqual(target.msg_id, 'duplex')
        self.assertTrue(self.gui.playback.play.call_args.kwargs['automatic'])


if __name__ == '__main__':
    unittest.main()
