"""Acceptance coverage for the independent CLI and frontend launcher boundary."""

# ruff: noqa: E402

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.cli.entry import run_cli
from metor.cli.handlers import CommandHandlers
from metor.cli.parser import CliParser
from metor.client import (
    FRONTEND_LAUNCH_CONTRACT_VERSION,
    FrontendLaunchContext,
    FrontendLaunchError,
    LoadedFrontend,
    load_frontend,
)
from metor.data import ProfileManager, SettingKey


class _Distribution:
    def __init__(self, name: str) -> None:
        self.name = name


class _EntryPoint:
    def __init__(
        self,
        name: str,
        value: str,
        entry: object,
        distribution: str = 'test-ui',
    ) -> None:
        self.name = name
        self.value = value
        self.dist = _Distribution(distribution)
        self._entry = entry

    def load(self) -> object:
        if isinstance(self._entry, BaseException):
            raise self._entry
        return self._entry


def _frontend(status: int = 0) -> object:
    def launch(_context: FrontendLaunchContext) -> int:
        return status

    setattr(launch, 'contract_version', FRONTEND_LAUNCH_CONTRACT_VERSION)
    return launch


class IndependentCliContractTests(unittest.TestCase):
    def test_all_help_variants_are_profile_and_frontend_side_effect_free(self) -> None:
        """R2-T30: help never constructs profiles, discovers UIs, or leaks slash help."""
        variants = (
            ['--help'],
            ['help'],
            ['chat', '--help'],
            ['chat', '--ui', 'terminal', '--help'],
            ['chat', '--ui', 'gui', '--help'],
        )
        for argv in variants:
            with self.subTest(argv=argv):
                output = io.StringIO()
                with (
                    patch(
                        'metor.cli.entry.ProfileManager',
                        side_effect=AssertionError('profile side effect'),
                    ),
                    patch(
                        'metor.client.frontends._frontend_entry_points',
                        side_effect=AssertionError('frontend discovery'),
                    ),
                    patch('sys.stdout', output),
                ):
                    self.assertEqual(run_cli(list(argv)), 0)
                rendered = output.getvalue()
                self.assertNotIn('/connect', rendered)
                self.assertNotIn('/fallback', rendered)
                self.assertNotIn('/help', rendered)
                if argv[0] == 'chat':
                    self.assertIn('--ui FRONTEND', rendered)
                    self.assertIn('--start-daemon', rendered)

    def test_non_chat_ui_tokens_remain_user_data(self) -> None:
        """R2-T32: the general parser does not strip UI-looking message data."""
        args, extra = CliParser.parse(['send', 'alice', '--ui', 'literal'])
        self.assertIsNone(args.ui)
        self.assertEqual(args.subcommand, 'alice')
        self.assertEqual(extra, ['--ui', 'literal'])

    def test_version_is_profile_and_frontend_independent(self) -> None:
        output = io.StringIO()
        with (
            patch(
                'metor.cli.entry.ProfileManager',
                side_effect=AssertionError('profile side effect'),
            ),
            patch('sys.stdout', output),
        ):
            self.assertEqual(run_cli(['--version']), 0)
        self.assertRegex(output.getvalue().strip(), r'^\d+\.\d+\.\d+$')

    def test_frontend_inventory_is_profile_independent_and_metadata_only(self) -> None:
        output = io.StringIO()
        with (
            patch(
                'metor.cli.entry.ProfileManager',
                side_effect=AssertionError('profile side effect'),
            ),
            patch('metor.cli.handlers.discover_frontends', return_value={}) as discover,
            patch('sys.stdout', output),
        ):
            self.assertEqual(run_cli(['chat', '--list-uis']), 0)
        discover.assert_called_once_with()
        self.assertIn('No interactive Metor frontends', output.getvalue())

    def test_selected_frontend_precedence_and_launch_context(self) -> None:
        """R2-T32: explicit, environment, then configured default selection wins."""
        for explicit, environment, configured, expected in (
            ('gui', 'env-ui', 'default-ui', 'gui'),
            (None, 'env-ui', 'default-ui', 'env-ui'),
            (None, None, 'default-ui', 'default-ui'),
        ):
            with self.subTest(expected=expected):
                pm = Mock(spec=ProfileManager)
                pm.profile_name = 'profile-a'
                pm.config = Mock()
                pm.config.get_str.return_value = configured
                pm.exists.return_value = True
                pm.is_daemon_running.return_value = True
                pm.is_remote.return_value = False
                pm.get_static_port.return_value = 37123
                loaded = Mock(spec=LoadedFrontend)
                environment_values = (
                    {'METOR_UI': environment} if environment is not None else {}
                )
                with (
                    patch.dict(os.environ, environment_values, clear=True),
                    patch(
                        'metor.cli.handlers.load_frontend', return_value=loaded
                    ) as load,
                    patch(
                        'metor.cli.handlers.invoke_frontend', return_value=7
                    ) as invoke,
                ):
                    status = CommandHandlers.handle_chat(
                        cast(ProfileManager, pm), frontend_id=explicit
                    )
                self.assertEqual(status, 7)
                load.assert_called_once_with(expected)
                context = invoke.call_args.args[1]
                self.assertEqual(context.profile, 'profile-a')
                interactions = Mock()
                result = context.host.bootstrap(interactions)
                self.assertEqual(result.port, 37123)

    def test_missing_selected_frontend_prevents_profile_and_daemon_side_effects(
        self,
    ) -> None:
        """R2-T32: launcher preflight fails before profile or daemon operations."""
        pm = Mock(spec=ProfileManager)
        pm.profile_name = 'default'
        pm.config = Mock()
        with (
            patch(
                'metor.cli.handlers.load_frontend',
                side_effect=FrontendLaunchError('install metor-ui-missing'),
            ),
            patch('metor.application.frontend.start_managed_daemon_process') as start,
            patch('sys.stderr', io.StringIO()),
        ):
            status = CommandHandlers.handle_chat(
                cast(ProfileManager, pm), frontend_id='missing'
            )
        self.assertEqual(status, 2)
        pm.exists.assert_not_called()
        pm.validate_integrity.assert_not_called()
        start.assert_not_called()

    def test_missing_frontend_preflight_does_not_create_global_settings(self) -> None:
        """R2-T32: default UI resolution is read-only before plugin preflight."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / '.metor'
            with (
                patch('metor.data.settings.Constants.DATA', data_path),
                patch(
                    'metor.cli.entry.ProfileManager',
                    side_effect=AssertionError('profile side effect'),
                ),
                patch(
                    'metor.cli.entry.load_frontend',
                    side_effect=FrontendLaunchError('install metor-ui-terminal'),
                ),
                patch.dict(os.environ, {}, clear=True),
                patch('sys.stderr', io.StringIO()),
            ):
                self.assertEqual(run_cli(['chat']), 2)
            self.assertFalse(data_path.exists())

    def test_discovery_rejects_duplicates_and_contract_mismatch(self) -> None:
        """R2-T32: conflicts and incompatible selected launchers are explicit."""
        duplicate = (
            _EntryPoint('gui', 'one:launch', _frontend(), 'one'),
            _EntryPoint('gui', 'two:launch', _frontend(), 'two'),
        )
        with patch(
            'metor.client.frontends._frontend_entry_points', return_value=duplicate
        ):
            with self.assertRaisesRegex(FrontendLaunchError, 'both'):
                load_frontend('gui')

        incompatible = Mock()
        incompatible.contract_version = FRONTEND_LAUNCH_CONTRACT_VERSION + 1
        with patch(
            'metor.client.frontends._frontend_entry_points',
            return_value=(_EntryPoint('gui', 'bad:launch', incompatible, 'bad-ui'),),
        ):
            with self.assertRaisesRegex(FrontendLaunchError, 'incompatible'):
                load_frontend('gui')

    def test_broken_selected_plugin_is_typed_and_does_not_load_siblings(self) -> None:
        """R2-T32: only the selected entry loads and dependency failure is typed."""
        sibling = Mock()
        entries = (
            _EntryPoint('terminal', 'terminal:launch', sibling, 'terminal-ui'),
            _EntryPoint(
                'gui',
                'gui:launch',
                ModuleNotFoundError('optional_gui_toolkit'),
                'gui-ui',
            ),
        )
        with patch(
            'metor.client.frontends._frontend_entry_points', return_value=entries
        ):
            with self.assertRaisesRegex(FrontendLaunchError, 'could not be loaded'):
                load_frontend('gui')
        sibling.assert_not_called()

    def test_default_ui_setting_key_is_canonical(self) -> None:
        self.assertEqual(SettingKey.DEFAULT_UI.value, 'client.default_ui')


if __name__ == '__main__':
    unittest.main()
