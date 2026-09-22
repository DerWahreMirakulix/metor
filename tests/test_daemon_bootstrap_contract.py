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

    def test_canonical_parser_does_not_resolve_default_profile(self) -> None:
        from metor.cli.parser import CliParser

        with patch.object(
            ProfileManager,
            'load_default_profile',
            side_effect=AssertionError('profile I/O during parser construction'),
        ):
            args, extra = CliParser.parse(['daemon', '--non-interactive'])

        self.assertIsNone(args.profile)
        self.assertTrue(args.non_interactive)
        self.assertEqual(extra, [])

    def test_autostart_uses_exact_interpreter_and_canonical_module(self) -> None:
        from metor.application.runtime.daemon import _build_daemon_launch_command

        profile = Mock(spec=ProfileManager)
        profile.profile_name = 'alpha'

        command = _build_daemon_launch_command(
            cast(ProfileManager, profile),
            start_locked=True,
            startup_session_auth_stdin=True,
        )

        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[1:4], ['-I', '-m', 'metor'])
        self.assertNotIn('metor.daemon_main', command)
        self.assertNotIn('--daemon-child', command)
        self.assertIn('--non-interactive', command)
        self.assertIn('daemon', command)

    def test_autostart_preserves_a_symlinked_virtualenv_interpreter(self) -> None:
        """The child invocation retains venv selection instead of canonicalizing it."""
        from metor.application.runtime.daemon import _build_daemon_launch_command

        profile = Mock(spec=ProfileManager)
        profile.profile_name = 'alpha'
        with TemporaryDirectory() as temp_dir:
            interpreter = Path(temp_dir) / 'venv' / 'bin' / 'python'
            interpreter.parent.mkdir(parents=True)
            interpreter.symlink_to(Path(sys.executable).resolve())
            resolved_interpreter = interpreter.resolve()
            with patch('sys.executable', str(interpreter)):
                command = _build_daemon_launch_command(
                    cast(ProfileManager, profile),
                    start_locked=True,
                    startup_session_auth_stdin=False,
                )

        self.assertEqual(command[0], str(interpreter))
        self.assertNotEqual(command[0], str(resolved_interpreter))

    def test_importing_cli_definition_is_runtime_side_effect_free(self) -> None:
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                (
                    'import sys; import metor.cli; '
                    "print(any(name.startswith(('metor.application', 'metor.data', "
                    "'metor.ui')) for name in sys.modules))"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'False')

    def test_daemon_help_uses_canonical_cli_without_runtime_imports(self) -> None:
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        result = subprocess.run(
            [sys.executable, '-m', 'metor', 'daemon', '--help'],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('metor daemon', result.stdout)

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

    def test_noninteractive_daemon_never_falls_back_to_a_prompt(self) -> None:
        from metor.application import DaemonStartPreparation
        from metor.cli.handlers import CommandHandlers

        profile = self._spawn_profile()
        with (
            patch(
                'metor.cli.handlers.prepare_managed_daemon_start',
                return_value=DaemonStartPreparation(False, False, True),
            ),
            patch(
                'metor.cli.handlers.prompt_hidden',
                side_effect=AssertionError('interactive prompt'),
            ),
            patch('metor.cli.handlers.run_managed_daemon') as run_daemon,
            patch('sys.stderr', io.StringIO()) as errors,
        ):
            result = CommandHandlers.handle_daemon(
                profile,
                non_interactive=True,
            )

        self.assertEqual(result, 1)
        run_daemon.assert_not_called()
        self.assertIn('--startup-session-auth-stdin', errors.getvalue())

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
