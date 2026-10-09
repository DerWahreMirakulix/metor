"""Explicit per-direction audio selection without native activation or headset inference."""

import base64
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, PropertyMock, patch

from metor.client import FrontendLaunchContext
from metor.client.platform import AudioEndpoint
from metor.core.api import (
    Delivery,
    MessageDirectionCode,
    RuntimeSnapshotEvent,
    VoiceDataEvent,
)
from metor.ui.gui.platform.audio import HeadsetAudio, PcmVoice
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route


class AudioSelectionTests(unittest.TestCase):
    """Route selection admits only chosen directions and never opens streams itself."""

    def setUp(self) -> None:
        """Creates an inert GUI and explicit compatible synthetic endpoint descriptors."""
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.gui.simulator = False
        self.gui.state.covered = False
        self.gui.state.route = Route('V08', 'peer', Delivery.DROP)
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', '', epoch='epoch', profile_instance_id='instance'
        )
        self.gui.state.capabilities = frozenset({'calls'})
        self.gui.client = Mock()
        self.routes = self.gui.voice.routes
        self.routes.scanned = True
        self.routes.endpoints = (
            AudioEndpoint(1, 'Microphone', True, False),
            AudioEndpoint(2, 'Speakers', False, True),
            AudioEndpoint(3, 'Other output', False, True),
            AudioEndpoint(
                4, 'Incompatible output', False, True, output_error='Unsupported format'
            ),
        )
        self.addCleanup(self.gui.close)

    def test_output_only_selection_supports_actual_manual_playback(self) -> None:
        """An explicit output alone plays the complete source without microphone setup."""
        native_output = Mock()
        native_output.write.return_value = False
        sounddevice = SimpleNamespace(
            RawInputStream=Mock(),
            RawOutputStream=Mock(return_value=native_output),
        )
        payload = b'\x00\x01' * PcmVoice.FRAME_SAMPLES
        self.gui.client.get_voice_chunk.return_value = VoiceDataEvent(
            'Peer',
            'voice',
            MessageDirectionCode.OUT,
            Delivery.DROP,
            PcmVoice.CODEC,
            0,
            len(payload),
            len(payload),
            base64.b64encode(payload).decode('ascii'),
            True,
            onion='peer',
        )

        with patch.dict(sys.modules, {'sounddevice': sounddevice}):
            self.assertTrue(self.routes.select(2, microphone=False))
            self.assertIsNone(self.routes.input)
            self.assertFalse(self.gui.voice.headset_confirmed)
            self.assertFalse(self.gui.calls.ready)
            sounddevice.RawInputStream.assert_not_called()
            sounddevice.RawOutputStream.assert_not_called()
            target = self.gui.playback.target(
                'peer', Delivery.DROP, MessageDirectionCode.OUT, 'voice'
            )
            assert target is not None
            self.assertTrue(self.gui.playback.play(target))
            worker = self.gui.playback.worker
            assert worker is not None
            self.assertTrue(worker.done.wait(3))
            while (update := self.gui.mailbox.take()) is not None:
                self.gui.playback.install(update)

        sounddevice.RawInputStream.assert_not_called()
        native_output.write.assert_called_once_with(payload)
        native_output.stop.assert_called_once()
        native_output.close.assert_called_once()
        assert self.gui.playback.progress is not None
        self.assertEqual(self.gui.playback.progress.state, 'complete')

    def test_microphone_and_speaker_choices_admit_call_without_confirmation(
        self,
    ) -> None:
        """Calls require installed input/output and do not require a headphone declaration."""
        operations: list[str] = []
        self.gui.submit = lambda operation, _work, **_kwargs: (
            operations.append(operation) or True
        )
        sounddevice = SimpleNamespace(RawInputStream=Mock(), RawOutputStream=Mock())
        with patch.dict(sys.modules, {'sounddevice': sounddevice}):
            self.assertTrue(self.routes.select(1, microphone=True))
            self.assertIsNone(self.gui.playback.audio)
            self.assertTrue(self.gui.voice.headset_confirmed)
            self.assertFalse(self.gui.calls.ready)
            self.assertTrue(self.routes.select(2, microphone=False))
            self.assertTrue(self.gui.calls.ready)
            self.gui.voice.headset_confirmed = False
            self.assertTrue(self.gui.calls.ready)
            self.assertTrue(self.gui.calls.start('peer'))
            sounddevice.RawInputStream.assert_not_called()
            sounddevice.RawOutputStream.assert_not_called()
        self.assertEqual(len(operations), 1)
        self.assertTrue(operations[0].startswith('call:start:'))
        audio = self.gui.voice.audio
        assert isinstance(audio, HeadsetAudio)
        self.assertEqual((audio.input_device, audio.output_device), (1, 2))

    def test_unsupported_or_wrong_direction_cannot_replace_installed_output(
        self,
    ) -> None:
        """An invalid chooser target leaves the chosen and installed route untouched."""
        self.assertTrue(self.routes.select(2, microphone=False))
        original = self.gui.playback.audio
        for endpoint in (1, 4, 999):
            with self.subTest(endpoint=endpoint):
                self.assertFalse(self.routes.select(endpoint, microphone=False))
                self.assertEqual(self.routes.output, 2)
                self.assertIs(self.gui.playback.audio, original)

    def test_active_media_owners_block_endpoint_edits(self) -> None:
        """Input, output and accepted calls retain their native ports until cleanup completes."""
        self.assertTrue(self.routes.select(2, microphone=False))
        original = self.gui.playback.audio
        for owner, attribute in (
            (self.gui.voice, 'running'),
            (self.gui.playback, 'running'),
            (self.gui.calls, 'active'),
            (self.gui.calls, 'media_active'),
        ):
            with (
                self.subTest(attribute=attribute),
                patch.object(
                    type(owner), attribute, new_callable=PropertyMock, return_value=True
                ),
            ):
                self.assertFalse(self.routes.select(3, microphone=False))
                self.assertFalse(self.routes.select(1, microphone=True))
                self.assertEqual(self.routes.output, 2)
                self.assertIsNone(self.routes.input)
                self.assertIs(self.gui.playback.audio, original)

    def test_cover_blocks_route_edit_and_reselection_clears_output_failure(
        self,
    ) -> None:
        """Recovery is explicit and cannot reconfigure through a privacy cover."""
        self.assertTrue(self.routes.select(2, microphone=False))
        self.gui.playback.progress = Mock(state='output_unavailable')
        self.gui.state.covered = True
        self.assertFalse(self.routes.select(3, microphone=False))
        self.assertEqual(self.routes.output, 2)
        self.gui.state.covered = False
        self.assertTrue(self.routes.select(3, microphone=False))
        self.assertEqual(self.routes.output, 3)
        self.assertIsNone(self.gui.playback.progress)


if __name__ == '__main__':
    unittest.main()
