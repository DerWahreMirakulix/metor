"""Regression coverage for the canonical daemon bootstrap path."""

# ruff: noqa: E402

import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.data import ProfileManager, SettingKey
from metor.utils import Constants


class DaemonBootstrapContractTests(unittest.TestCase):
    """Covers argument gates, secret transport, and failed-child ownership."""

    def test_headless_parser_does_not_resolve_default_profile(self) -> None:
        from metor import daemon_main

        with patch.object(
            ProfileManager,
            'load_default_profile',
            side_effect=AssertionError('profile I/O during parser construction'),
        ):
            args = daemon_main._build_parser().parse_args([])

        self.assertIsNone(args.profile)

    def test_autostart_uses_public_metor_entry_and_child_marker(self) -> None:
        from metor.application.runtime.daemon import _build_daemon_launch_command

        profile = Mock(spec=ProfileManager)
        profile.profile_name = 'alpha'

        command = _build_daemon_launch_command(
            cast(ProfileManager, profile),
            start_locked=True,
            startup_session_auth_stdin=True,
        )

        self.assertEqual(Path(command[0]).name, 'metor')
        self.assertNotIn('metor.daemon_main', command)
        self.assertIn('--daemon-child', command)
        self.assertEqual(command[-1], 'daemon')

    def test_importing_public_main_does_not_eagerly_import_cli(self) -> None:
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                "import sys; import metor.main; print('metor.cli' in sys.modules)",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'False')

    def test_child_help_needs_no_profile_or_cli_import(self) -> None:
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        result = subprocess.run(
            [sys.executable, '-m', 'metor', '--daemon-child', '--help'],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: metor', result.stdout)

        import_graph = subprocess.run(
            [
                sys.executable,
                '-c',
                (
                    'import sys; import metor.daemon_main; '
                    "print(any(name == 'metor.cli' or name.startswith('metor.ui') "
                    'for name in sys.modules))'
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(import_graph.returncode, 0, import_graph.stderr)
        self.assertEqual(import_graph.stdout.strip(), 'False')

    def test_child_initializes_environment_before_resolving_default(self) -> None:
        from metor import daemon_main

        calls: list[str] = []

        def load_default() -> str:
            self.assertEqual(calls, ['environment'])
            calls.append('default')
            return 'alpha'

        with (
            patch(
                'metor.application.initialize_runtime_environment',
                side_effect=lambda: calls.append('environment'),
            ),
            patch.object(
                ProfileManager,
                'load_default_profile',
                side_effect=load_default,
            ),
            patch.object(daemon_main, '_run_daemon', return_value=0) as run_daemon,
        ):
            result = daemon_main.run(['--daemon-child', 'daemon'])

        self.assertEqual(result, 0)
        self.assertEqual(calls, ['environment', 'default'])
        run_daemon.assert_called_once_with(
            profile='alpha',
            start_locked=False,
            startup_session_auth_stdin=False,
        )

    def test_explicit_child_profile_never_loads_default(self) -> None:
        from metor import daemon_main

        with (
            patch('metor.application.initialize_runtime_environment'),
            patch.object(
                ProfileManager,
                'load_default_profile',
                side_effect=AssertionError('unexpected default profile read'),
            ),
            patch.object(daemon_main, '_run_daemon', return_value=0) as run_daemon,
        ):
            result = daemon_main.run(
                ['-p', 'explicit', '--locked', '--daemon-child', 'daemon']
            )

        self.assertEqual(result, 0)
        run_daemon.assert_called_once_with(
            profile='explicit',
            start_locked=True,
            startup_session_auth_stdin=False,
        )

    def test_environment_data_path_is_loaded_before_profile_resolution(self) -> None:
        from metor.application import environment

        old_data = Constants.DATA
        old_loaded = environment._loaded
        try:
            with TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                data_parent = root / 'state'
                (root / '.env').write_text(
                    f'METOR_DATA_DIR_PARENT={data_parent}\n',
                    encoding='utf-8',
                )
                with (
                    patch.dict(
                        os.environ,
                        {'METOR_DATA_DIR_PARENT': ''},
                        clear=False,
                    ),
                    patch('pathlib.Path.cwd', return_value=root),
                    patch('metor.application.environment.load_dotenv') as load_dotenv,
                ):
                    load_dotenv.side_effect = lambda: os.environ.__setitem__(
                        'METOR_DATA_DIR_PARENT', str(data_parent)
                    )
                    environment._loaded = False
                    environment.initialize_runtime_environment()

                self.assertEqual(Constants.DATA, data_parent / Constants.DATA_DIR)
        finally:
            Constants.DATA = old_data
            environment._loaded = old_loaded

    def test_shared_preparation_rejects_remote_and_locked_plaintext(self) -> None:
        from metor.application.runtime.daemon import (
            PlaintextLockedDaemonError,
            RemoteDaemonProfileError,
            prepare_managed_daemon_start,
        )

        profile = self._spawn_profile()
        cast(Mock, profile.is_remote).return_value = True
        with (
            patch('metor.application.runtime.daemon.Settings.validate_integrity'),
            self.assertRaises(RemoteDaemonProfileError),
        ):
            prepare_managed_daemon_start(profile, start_locked=False)

        cast(Mock, profile.is_remote).return_value = False
        with (
            patch('metor.application.runtime.daemon.Settings.validate_integrity'),
            self.assertRaises(PlaintextLockedDaemonError),
        ):
            prepare_managed_daemon_start(profile, start_locked=True)

    def test_startup_secret_reader_rejects_empty_and_overlong_input(self) -> None:
        from metor.application.runtime.daemon import read_startup_secret

        self.assertIsNone(read_startup_secret(io.StringIO('')))
        self.assertEqual(read_startup_secret(io.StringIO('Grüße\n')), 'Grüße')
        with self.assertRaisesRegex(ValueError, 'too long'):
            read_startup_secret(io.StringIO('x' * 4097 + '\n'))

    @staticmethod
    def _spawn_profile() -> ProfileManager:
        profile = Mock(spec=ProfileManager)
        profile.profile_name = 'alpha'
        profile.config = Mock()
        profile.config.get_float.side_effect = lambda key: {
            SettingKey.IPC_TIMEOUT: 0.1,
            SettingKey.TOR_TIMEOUT: 0.1,
        }[key]
        profile.config.get_bool.return_value = False
        profile.exists.return_value = True
        profile.validate_integrity.return_value = None
        profile.is_remote.return_value = False
        profile.is_daemon_running.return_value = False
        profile.uses_plaintext_storage.return_value = True
        profile.uses_encrypted_storage.return_value = False
        profile.get_daemon_port.return_value = None
        return cast(ProfileManager, profile)

    def test_secret_write_failure_terminates_owned_child(self) -> None:
        from metor.application.runtime.daemon import start_managed_daemon_process

        process = Mock()
        process.stdin = Mock()
        process.stdin.write.side_effect = BrokenPipeError('closed')
        process.poll.return_value = None
        profile = self._spawn_profile()

        with (
            patch('metor.application.runtime.daemon.Settings.validate_integrity'),
            patch(
                'metor.application.runtime.daemon.subprocess.Popen',
                return_value=process,
            ),
        ):
            self.assertFalse(
                start_managed_daemon_process(
                    profile,
                    session_auth_password='secret',
                )
            )

        process.terminate.assert_called_once_with()
        process.wait.assert_called()

    def test_readiness_timeout_terminates_owned_child_with_bounded_wait(self) -> None:
        from metor.application.runtime.daemon import start_managed_daemon_process

        process = Mock()
        process.stdin = None
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired('metor', 2.0)
        profile = self._spawn_profile()

        with (
            patch('metor.application.runtime.daemon.Settings.validate_integrity'),
            patch(
                'metor.application.runtime.daemon.subprocess.Popen',
                return_value=process,
            ),
            patch(
                'metor.application.runtime.daemon.time.monotonic',
                side_effect=[0.0, 100.0],
            ),
        ):
            self.assertFalse(start_managed_daemon_process(profile))

        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        process.wait.assert_called()


if __name__ == '__main__':
    unittest.main()
