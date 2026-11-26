"""PCM framing and native-port safety tests; mock streams do not prove acoustics."""

import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from metor.ui.gui.platform.audio import HeadsetAudio, PcmVoice


class AudioPortTests(unittest.TestCase):
    """Verifies complete sample framing and resource ownership."""

    def test_pcm_timing_seek_and_incomplete_sample_rejection(self) -> None:
        """Frame duration and decoder checkpoints derive from encoded samples."""
        frame = struct.pack('<320h', *range(320))
        PcmVoice.validate(frame)
        self.assertEqual(struct.unpack('<320h', frame)[-1], 319)
        self.assertEqual(PcmVoice.duration_ms(len(frame)), 20)
        self.assertEqual(PcmVoice.seek_offset(10, len(frame)), 320)
        self.assertEqual(PcmVoice.seek_offset(99, len(frame)), 640)
        with self.assertRaises(ValueError):
            PcmVoice.validate(frame[:-1], final=True)
        with self.assertRaises(ValueError):
            PcmVoice.validate(frame[:2])

    def test_inert_adapter_does_not_capture_on_construction(self) -> None:
        """No native stream exists before explicit capture or playback intent."""
        audio = HeadsetAudio()
        self.assertIsNone(audio._capture)
        self.assertIsNone(audio._output)
        self.assertIsNone(audio.take_frame())
        audio.stop()

    def test_inert_enumeration_keeps_unsupported_directions_visible(self) -> None:
        """Format checks explain incompatible endpoints without opening any native stream."""
        sounddevice = SimpleNamespace(
            query_devices=Mock(
                return_value=[
                    {
                        'name': 'Headset',
                        'hostapi': 0,
                        'max_input_channels': 1,
                        'max_output_channels': 2,
                    },
                    {
                        'name': 'Headset',
                        'hostapi': 1,
                        'max_input_channels': 0,
                        'max_output_channels': 2,
                    },
                ]
            ),
            query_hostapis=Mock(
                return_value=[{'name': 'MME'}, {'name': 'DirectSound'}]
            ),
            check_input_settings=Mock(),
            check_output_settings=Mock(side_effect=[None, ValueError('Unsupported')]),
            RawInputStream=Mock(),
            RawOutputStream=Mock(),
            PortAudioError=RuntimeError,
        )

        with patch.dict(sys.modules, {'sounddevice': sounddevice}):
            endpoints = HeadsetAudio.endpoints()

        self.assertEqual(len(endpoints), 2)
        self.assertEqual(endpoints[0].input_error, '')
        self.assertEqual(endpoints[0].output_error, '')
        self.assertTrue(endpoints[1].output_available)
        self.assertTrue(endpoints[1].output_error)
        sounddevice.check_input_settings.assert_called_once_with(
            device=0,
            samplerate=PcmVoice.SAMPLE_RATE,
            channels=PcmVoice.CHANNELS,
            dtype='int16',
        )
        self.assertEqual(sounddevice.check_output_settings.call_count, 2)
        sounddevice.RawInputStream.assert_not_called()
        sounddevice.RawOutputStream.assert_not_called()

    def test_output_still_closes_if_capture_cleanup_fails(self) -> None:
        """A failed microphone does not strand the independent playback device."""
        audio = HeadsetAudio()
        capture, output = Mock(), Mock()
        capture.stop.side_effect = OSError('unplug')
        audio._capture, audio._output = capture, output
        with self.assertRaises(RuntimeError):
            audio.stop()
        capture.close.assert_called_once()
        output.stop.assert_called_once()
        output.close.assert_called_once()
        self.assertIsNone(audio._capture)
        self.assertIsNone(audio._output)

    def test_capture_permission_denial_does_not_claim_or_stop_output(self) -> None:
        """A denied microphone leaves independent output ownership untouched."""
        denied = Mock(side_effect=PermissionError('microphone denied'))
        sounddevice = SimpleNamespace(RawInputStream=denied)
        audio = HeadsetAudio()
        output = Mock()
        output.write.return_value = False
        audio._output = output

        with (
            patch.dict(sys.modules, {'sounddevice': sounddevice}),
            self.assertRaises(PermissionError),
        ):
            audio.start_capture(headset_confirmed=True)

        self.assertIsNone(audio._capture)
        self.assertIs(audio._output, output)
        output.stop.assert_not_called()

    def test_output_permission_denial_does_not_claim_or_stop_capture(self) -> None:
        """A denied speaker leaves the active microphone owner untouched."""
        denied = Mock(side_effect=PermissionError('speaker denied'))
        sounddevice = SimpleNamespace(RawOutputStream=denied)
        audio = HeadsetAudio()
        capture = Mock()
        audio._capture = capture

        with (
            patch.dict(sys.modules, {'sounddevice': sounddevice}),
            self.assertRaises(PermissionError),
        ):
            audio.play_frame(b'\x00\x01' * 320, headset_confirmed=True)

        self.assertIsNone(audio._output)
        self.assertIs(audio._capture, capture)
        capture.stop.assert_not_called()

    def test_output_underflow_accepts_current_samples_until_successful_drain(
        self,
    ) -> None:
        """Inserted silence between blocking writes does not reject the submitted samples."""
        output = Mock()
        output.write.side_effect = [True, False, True]
        sounddevice = SimpleNamespace(RawOutputStream=Mock(return_value=output))
        audio = HeadsetAudio(output_device=7)
        frame = b'\x00\x01' * PcmVoice.FRAME_SAMPLES

        with patch.dict(sys.modules, {'sounddevice': sounddevice}):
            for _ in range(3):
                audio.play_frame(frame, headset_confirmed=True)
            self.assertIs(audio._output, output)
            output.stop.assert_not_called()
            audio.stop_output()

        self.assertEqual(output.write.call_count, 3)
        output.start.assert_called_once()
        output.stop.assert_called_once()
        output.close.assert_called_once()
        self.assertIsNone(audio._output)


if __name__ == '__main__':
    unittest.main()
