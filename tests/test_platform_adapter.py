"""Installed adapter selection, validation, activation and shared setting contracts."""

from importlib import import_module
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from metor.application.frontend.host import LocalFrontendHost
from metor.client.platform import (
    DeviceSettingDescriptor,
    DeviceSettingKind,
    DeviceSettingResult,
    DeviceSettingStatus,
    PlatformBindings,
)
from metor.client import FrontendLaunchContext
from metor.ui.gui.platform import (
    DeviceConfigurationError,
    open_platform,
    prepare_platform,
    read_configuration,
)
from metor.ui.gui.runtime.device.settings import DeviceSettings
from metor.ui.gui.launcher import GuiEntry
from metor.utils import open_private_binary_file


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = (ROOT / 'docs/examples/gui-reference-board.toml').read_text(encoding='utf-8')


def _configuration(root: Path, content: str = EXAMPLE) -> Path:
    """Write a trusted temporary deployment file through the production helper."""
    path = root / 'device.toml'
    with open_private_binary_file(path) as target:
        target.write(content.encode('utf-8'))
    return path


def _reference_provider() -> object:
    """Import the actual example package without installing it in the test host."""
    source = str(ROOT / 'examples/reference_adapter/src')
    sys.path.insert(0, source)
    try:
        return import_module('metor_reference_board').provider
    finally:
        sys.path.remove(source)


class _Entry:
    """Stand in for distribution metadata without importing another provider."""

    def __init__(self, name: str, provider: object) -> None:
        self.name = name
        self._provider = provider
        self.loads = 0

    def load(self) -> object:
        """Record import selection and return a controlled provider."""
        self.loads += 1
        return self._provider


class AdapterSelectionTests(unittest.TestCase):
    """Exercise strict TOML and installed metadata before resource activation."""

    def test_selected_provider_only_and_shared_reference_value(self) -> None:
        """Two sessions share one effective simulated value without profile state."""
        selected = _Entry('reference-board', _reference_provider())
        unrelated = _Entry('other-board', object())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configuration = read_configuration(str(_configuration(root)), False)
            with (
                patch(
                    'metor.ui.gui.platform.providers.metadata.entry_points',
                    return_value=[unrelated, selected],
                ),
                patch('pathlib.Path.home', return_value=root),
            ):
                plan = prepare_platform(configuration, None)
                self.assertIsNotNone(plan)
                self.assertEqual(unrelated.loads, 0)
                self.assertEqual(selected.loads, 1)
                assert plan is not None
                host = LocalFrontendHost(None, None)
                first = open_platform(configuration, plan, host)
                second = open_platform(configuration, plan, host)
                try:
                    first_settings = first.bindings.settings
                    second_settings = second.bindings.settings
                    assert first_settings is not None and second_settings is not None
                    self.assertEqual(first_settings.read('brightness').value, 50)
                    self.assertEqual(
                        first_settings.write('brightness', 73),
                        DeviceSettingResult(DeviceSettingStatus.APPLIED, 73),
                    )
                    self.assertEqual(second_settings.read('brightness').value, 73)
                    self.assertEqual(
                        second_settings.write('brightness', 50.5),
                        DeviceSettingResult(DeviceSettingStatus.APPLIED, 50.5),
                    )
                    self.assertEqual(first_settings.read('brightness').value, 50.5)
                    self.assertEqual(
                        second_settings.write('brightness', True).status,
                        DeviceSettingStatus.DENIED,
                    )
                    self.assertEqual(
                        second_settings.write('purge', 1).status,
                        DeviceSettingStatus.UNSUPPORTED,
                    )
                finally:
                    first.close()
                    second.close()
                self.assertEqual(
                    first_settings.read('brightness').status,
                    DeviceSettingStatus.UNAVAILABLE,
                )

    def test_invalid_parameters_duplicate_and_contract_reject_before_open(self) -> None:
        """Bad config, ambiguous ID and incompatible factory cannot activate a board."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configuration = read_configuration(
                str(
                    _configuration(
                        root,
                        EXAMPLE.replace(
                            'initial_brightness = 50', 'initial_brightness = true'
                        ),
                    )
                ),
                False,
            )
            selected = _Entry('reference-board', _reference_provider())
            with patch(
                'metor.ui.gui.platform.providers.metadata.entry_points',
                return_value=[selected],
            ):
                with self.assertRaises(DeviceConfigurationError):
                    prepare_platform(configuration, None)
            self.assertEqual(selected.loads, 1)
            configuration = read_configuration(str(_configuration(root)), False)
            duplicate = _Entry('reference-board', object())
            with patch(
                'metor.ui.gui.platform.providers.metadata.entry_points',
                return_value=[selected, duplicate],
            ):
                with self.assertRaisesRegex(DeviceConfigurationError, 'ambiguous'):
                    prepare_platform(configuration, None)
            self.assertEqual(duplicate.loads, 0)
            incompatible = _Entry(
                'reference-board',
                Mock(adapter_id='reference-board', contract_version=2),
            )
            with patch(
                'metor.ui.gui.platform.providers.metadata.entry_points',
                return_value=[incompatible],
            ):
                with self.assertRaisesRegex(DeviceConfigurationError, 'incompatible'):
                    prepare_platform(configuration, None)

    def test_numeric_deployment_parameters_are_bounded_before_provider_load(
        self,
    ) -> None:
        """Large but finite scalar TOML cannot reach provider validation."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in ('9' * 300, '1e308'):
                with self.subTest(value_kind='integer' if value[0] == '9' else 'float'):
                    path = _configuration(
                        root,
                        EXAMPLE.replace(
                            'initial_brightness = 50', f'initial_brightness = {value}'
                        ),
                    )
                    with self.assertRaisesRegex(
                        DeviceConfigurationError,
                        'platform.config: number exceeds supported range',
                    ):
                        read_configuration(str(path), False)

    def test_none_disables_injected_optional_ports_and_required_none_fails(
        self,
    ) -> None:
        """Explicit none disables available actuators without disabling required input."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = read_configuration(
                str(_configuration(root)),
                False,
                PlatformBindings(
                    'reference-board', Mock(), Mock(), indicator=Mock(), haptics=Mock()
                ),
            )
            filtered = config.activate_platform(
                PlatformBindings(
                    'reference-board', Mock(), Mock(), indicator=Mock(), haptics=Mock()
                )
            )
            assert filtered is not None
            self.assertIsNone(filtered.shutdown)
            self.assertIsNone(filtered.indicator)
            self.assertIsNone(filtered.haptics)
            with self.assertRaises(DeviceConfigurationError):
                read_configuration(
                    str(
                        _configuration(
                            root,
                            EXAMPLE.replace(
                                "[input]\nadapter = 'reference-board'",
                                "[input]\nadapter = 'none'",
                            ),
                        )
                    ),
                    False,
                )

    def test_partial_session_is_closed_on_capability_mismatch(self) -> None:
        """A provider that changes advertised ports releases its opened session."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = read_configuration(str(_configuration(root)), False)
            session = Mock()
            session.bindings = PlatformBindings('reference-board', Mock())
            plan = Mock(capabilities=frozenset({'input', 'settings'}), exclusive=False)
            plan.open.return_value = session
            with self.assertRaises(DeviceConfigurationError):
                open_platform(config, plan, LocalFrontendHost(None, None))
            session.close.assert_called_once()

    def test_exclusive_resource_refuses_second_frontend(self) -> None:
        """The OS-backed resource lease prevents two local GUI owners."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = read_configuration(str(_configuration(root)), False)
            session = Mock()
            session.bindings = PlatformBindings('reference-board', Mock())
            plan = Mock(
                capabilities=frozenset({'input'}),
                resource_id='board0',
                exclusive=True,
            )
            plan.open.return_value = session
            with patch('pathlib.Path.home', return_value=root):
                host = LocalFrontendHost(None, None)
                with self.assertRaises(ValueError):
                    host.device_resource_lock('../other')
                first = open_platform(config, plan, host)
                try:
                    with self.assertRaisesRegex(
                        DeviceConfigurationError, 'already in use'
                    ):
                        open_platform(config, plan, host)
                    plan.open.assert_called_once()
                finally:
                    first.close()
                second = open_platform(config, plan, host)
                second.close()

    def test_launcher_selects_opens_and_releases_installed_adapter(self) -> None:
        """The production GUI entry point closes the example after app teardown."""
        selected = _Entry('reference-board', _reference_provider())
        module = ModuleType('metor.ui.gui.app')
        seen: list[object] = []

        class App:
            """Inert event loop retaining the selected public platform binding."""

            def __init__(
                self, context: FrontendLaunchContext, _configuration: object
            ) -> None:
                """Record the binding received by the application."""
                seen.append(context.platform)
                self.controller = SimpleNamespace(
                    lifecycle=SimpleNamespace(exit_ready=True)
                )
                self.exit_status = 0

            def run(self) -> None:
                """Return through the real launcher cleanup path."""

            def on_stop(self) -> None:
                """Observe the adapter before the launcher releases it."""
                binding = seen[0]
                assert isinstance(binding, PlatformBindings)
                assert binding.settings is not None
                self_outer.assertEqual(binding.settings.read('brightness').value, 50)

        self_outer = self
        module.MetorApp = App  # type: ignore[attr-defined]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = _configuration(root)
            with (
                patch(
                    'metor.ui.gui.platform.providers.metadata.entry_points',
                    return_value=[selected],
                ),
                patch('pathlib.Path.home', return_value=root),
                patch.dict(sys.modules, {'metor.ui.gui.app': module}),
                patch.dict('os.environ', {'SDL_VIDEODRIVER': 'offscreen'}),
            ):
                result = GuiEntry()(
                    FrontendLaunchContext(None, Mock(), device_config=str(path))
                )
        self.assertEqual(result, 0)
        binding = seen[0]
        assert isinstance(binding, PlatformBindings)
        assert binding.settings is not None
        self.assertEqual(
            binding.settings.read('brightness').status,
            DeviceSettingStatus.UNAVAILABLE,
        )

    def test_launcher_rejects_failed_activation_without_app(self) -> None:
        """A failed selected open reports a safe error before application creation."""
        selected = _Entry('reference-board', _reference_provider())
        module = ModuleType('metor.ui.gui.app')
        app_constructor = Mock()
        module.MetorApp = app_constructor  # type: ignore[attr-defined]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = _configuration(root)
            error = StringIO()
            with (
                patch(
                    'metor.ui.gui.platform.providers.metadata.entry_points',
                    return_value=[selected],
                ),
                patch(
                    'metor_reference_board._Plan.open',
                    side_effect=RuntimeError('private-error'),
                ),
                patch.dict(sys.modules, {'metor.ui.gui.app': module}),
                patch.dict('os.environ', {'SDL_VIDEODRIVER': 'offscreen'}),
                redirect_stderr(error),
            ):
                status = GuiEntry()(
                    FrontendLaunchContext(None, Mock(), device_config=str(path))
                )
        self.assertEqual(status, 2)
        app_constructor.assert_not_called()
        self.assertIn('Selected device adapter could not start', error.getvalue())
        self.assertNotIn('private-error', error.getvalue())


class DeviceSettingsTests(unittest.TestCase):
    """Protect the asynchronous readback and validation behavior."""

    def test_write_requires_matching_confirmed_readback(self) -> None:
        """A claimed application with different readback is shown as uncertain."""
        descriptor = DeviceSettingDescriptor(
            'brightness',
            'Brightness',
            DeviceSettingKind.NUMBER,
            minimum=0,
            maximum=100,
        )
        port = Mock()
        port.describe.return_value = (descriptor,)
        port.read.return_value = DeviceSettingResult(DeviceSettingStatus.APPLIED, 10)
        port.write.return_value = DeviceSettingResult(DeviceSettingStatus.APPLIED, 20)
        settings = DeviceSettings(port)
        self.assertTrue(settings.refresh())
        assert settings._worker is not None
        settings._worker.join(2)
        self.assertTrue(settings.poll())
        self.assertFalse(settings.write('brightness', True))
        port.write.assert_not_called()
        self.assertTrue(settings.write('brightness', 20))
        assert settings._worker is not None
        settings._worker.join(2)
        self.assertTrue(settings.poll())
        self.assertIn('unknown', settings.feedback)
        self.assertEqual(settings.values['brightness'].value, 10)
        settings.close()

    def test_failed_write_discards_stale_confirmed_readback(self) -> None:
        """A driver error leaves the previous value unknown until a fresh read."""
        descriptor = DeviceSettingDescriptor(
            'brightness',
            'Brightness',
            DeviceSettingKind.NUMBER,
            minimum=0,
            maximum=100,
        )
        port = Mock()
        port.describe.return_value = (descriptor,)
        port.read.return_value = DeviceSettingResult(DeviceSettingStatus.APPLIED, 10)
        settings = DeviceSettings(port)
        self.assertTrue(settings.refresh())
        assert settings._worker is not None
        settings._worker.join(2)
        self.assertTrue(settings.poll())
        port.write.side_effect = OSError('synthetic driver failure')
        self.assertTrue(settings.write('brightness', 20))
        assert settings._worker is not None
        settings._worker.join(2)
        self.assertTrue(settings.poll())
        self.assertEqual(
            settings.values['brightness'].status, DeviceSettingStatus.UNKNOWN
        )
        self.assertIn('retry', settings.feedback)
        settings.close()

    def test_descriptor_limits_reject_action_aliases(self) -> None:
        """No generic setting key may become a purge or power command."""
        with self.assertRaises(ValueError):
            DeviceSettingDescriptor('purge', 'Erase', DeviceSettingKind.BOOLEAN)
        with self.assertRaises(ValueError):
            DeviceSettingDescriptor(
                'brightness',
                'Invalid',
                DeviceSettingKind.CHOICE,
                choices=tuple(str(i) for i in range(20)),
            )
