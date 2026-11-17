"""Generic native audio selection and provenance regressions."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from metor.client.platform import AudioEndpoint
from tests.gui_native_route import select_audio_route, verify_gui_module_origin


class NativeAudioRouteTests(unittest.TestCase):
    """Covers capabilities without depending on a device name or stable index."""

    def test_equivalent_pairs_are_selected_independently_of_names_and_indices(
        self,
    ) -> None:
        pairs = (
            (
                AudioEndpoint(3, 'Generic capture alpha', True, False),
                AudioEndpoint(8, 'Generic playback alpha', False, True),
            ),
            (
                AudioEndpoint(41, 'Unrelated input label', True, False),
                AudioEndpoint(12, 'Unrelated output label', False, True),
            ),
        )
        for source, sink in pairs:
            with self.subTest(source=source.index, sink=sink.index):
                validate = Mock()
                selected = select_audio_route(
                    (sink, source),
                    source.index,
                    sink.index,
                    headset_confirmed=True,
                    validate_format=validate,
                )
                self.assertEqual(selected.source.index, source.index)
                self.assertEqual(selected.sink.index, sink.index)
                validate.assert_called_once_with(source.index, sink.index)

    def test_invalid_direction_and_format_fail_without_stream_activation(self) -> None:
        validate = Mock(side_effect=RuntimeError('unsupported PCM'))
        with self.assertRaisesRegex(RuntimeError, 'capture direction'):
            select_audio_route(
                (AudioEndpoint(1, 'Output only', False, True),),
                1,
                1,
                headset_confirmed=True,
                validate_format=validate,
            )
        validate.assert_not_called()

        with self.assertRaisesRegex(RuntimeError, 'playback direction'):
            select_audio_route(
                (
                    AudioEndpoint(3, 'Input', True, False),
                    AudioEndpoint(4, 'Second input', True, False),
                ),
                3,
                4,
                headset_confirmed=True,
                validate_format=validate,
            )
        validate.assert_not_called()

        with self.assertRaisesRegex(RuntimeError, 'unsupported PCM'):
            select_audio_route(
                (AudioEndpoint(2, 'Duplex endpoint', True, True),),
                2,
                2,
                headset_confirmed=True,
                validate_format=validate,
            )
        validate.assert_called_once_with(2, 2)

    def test_confirmation_and_current_enumeration_are_fail_closed(self) -> None:
        validate = Mock()
        endpoint = AudioEndpoint(7, 'Neutral duplex', True, True)
        with self.assertRaisesRegex(RuntimeError, 'confirmation'):
            select_audio_route(
                (endpoint,),
                7,
                7,
                headset_confirmed=False,
                validate_format=validate,
            )
        with self.assertRaisesRegex(RuntimeError, 'no longer enumerated'):
            select_audio_route(
                (),
                7,
                7,
                headset_confirmed=True,
                validate_format=validate,
            )
        validate.assert_not_called()

    def test_source_and_installed_modes_require_exact_module_origin(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / 'checkout'
            environment = root / 'venv'
            source_module = checkout / 'src/metor/ui/gui/app.py'
            installed_module = environment / 'lib/site-packages/metor/ui/gui/app.py'
            verify_gui_module_origin(
                str(source_module),
                mode='source',
                checkout=checkout,
                environment_root=environment,
            )
            verify_gui_module_origin(
                str(installed_module),
                mode='installed',
                checkout=checkout,
                environment_root=environment,
            )
            with self.assertRaisesRegex(RuntimeError, 'checkout'):
                verify_gui_module_origin(
                    str(source_module),
                    mode='installed',
                    checkout=checkout,
                    environment_root=environment,
                )


if __name__ == '__main__':
    unittest.main()
