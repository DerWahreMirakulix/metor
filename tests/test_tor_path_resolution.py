"""Regression tests for Tor executable resolution across host environments."""

# ruff: noqa: E402

import sys
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.tor import TorManager
from metor.core.api import EventType, RuntimeErrorCode
from metor.utils import Constants


class TorPathResolutionTests(unittest.TestCase):
    """
    Covers Tor path resolution regression scenarios.
    """

    def test_env_override_wins_on_windows(self) -> None:
        """
        Verifies that env override wins on windows.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / 'tor.exe'
            executable.touch()
            with (
                patch('metor.core.tor._is_windows', return_value=True),
                patch.object(Constants, 'TOR_PATH', str(executable)),
            ):
                self.assertEqual(
                    TorManager._resolve_tor_command(),
                    str(executable.resolve()),
                )

    def test_windows_ignores_path_and_uses_owned_data_binary(self) -> None:
        """
        Verifies that Windows never selects an unrelated PATH executable.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / 'owned'
            data_dir.mkdir()
            owned = data_dir / Constants.TOR_WIN
            owned.touch()
            with (
                patch('metor.core.tor._is_windows', return_value=True),
                patch.object(Constants, 'TOR_PATH', ''),
                patch.object(Constants, 'DATA', data_dir),
                patch.dict('os.environ', {'PATH': str(Path(temp_dir) / 'foreign')}),
            ):
                self.assertEqual(
                    TorManager._resolve_tor_command(),
                    str(owned.resolve()),
                )

    def test_windows_falls_back_to_data_dir_tor_exe(self) -> None:
        """
        Verifies that windows falls back to data dir Tor exe.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            with (
                patch('metor.core.tor._is_windows', return_value=True),
                patch.object(Constants, 'TOR_PATH', ''),
                patch.object(Constants, 'DATA', data_dir),
                self.assertRaises(FileNotFoundError) as raised,
            ):
                TorManager._resolve_tor_command()
            self.assertNotIn(str(data_dir), str(raised.exception))


class TorLifecycleTests(unittest.TestCase):
    """Covers bounded Tor process and exported-key release outcomes."""

    def _manager(self, process: Mock | None) -> TorManager:
        """Builds a Tor manager around an inert process double and temporary paths.

        Args:
            process (Mock | None): Fake tracked Tor process.

        Returns:
            TorManager: Isolated lifecycle owner without a real Tor process.
        """
        root = Path(self.enterContext(TemporaryDirectory()))
        manager = TorManager(Mock(), Mock())
        manager._tm_proc = process
        manager.socks_port = 12346
        manager.control_port = 12347
        manager.incoming_port = 12348
        manager._pm.paths.get_hidden_service_dir.return_value = root
        manager._pm.paths.get_tor_data_dir.return_value = root
        return manager

    def test_stop_confirms_normal_exit_and_is_idempotent(self) -> None:
        """A bounded successful wait releases ownership and permits repeated stop.

        Args:
            None

        Returns:
            None
        """
        process = Mock()
        process.poll.return_value = None
        process.wait.return_value = 0
        manager = self._manager(process)

        manager._control = controller = Mock()
        manager.stop()
        manager.stop()

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
        process.kill.assert_not_called()
        self.assertIsNone(manager._tm_proc)
        controller.close.assert_called_once_with()

    def test_stop_wait_timeout_kills_and_waits_for_confirmed_exit(self) -> None:
        """A terminate timeout requires both kill and a second bounded wait.

        Args:
            None

        Returns:
            None
        """
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [
            subprocess.TimeoutExpired('tor', Constants.TOR_KILL_TIMEOUT_SEC),
            0,
        ]
        manager = self._manager(process)

        manager.stop()

        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_count, 2)
        self.assertIsNone(manager._tm_proc)

    def test_stop_uses_kill_after_terminate_error(self) -> None:
        """A failed terminate call can still complete through kill and bounded wait.

        Args:
            None

        Returns:
            None
        """
        process = Mock()
        process.poll.return_value = None
        process.terminate.side_effect = OSError('terminate failed')
        process.wait.return_value = 0
        manager = self._manager(process)

        manager.stop()

        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
        self.assertIsNone(manager._tm_proc)

    def test_stop_retains_process_when_termination_cannot_be_confirmed(self) -> None:
        """Terminate and kill failures keep ownership while key cleanup still runs.

        Args:
            None

        Returns:
            None
        """
        process = Mock()
        process.poll.return_value = None
        process.terminate.side_effect = OSError('terminate failed')
        process.kill.side_effect = OSError('kill failed')
        manager = self._manager(process)

        manager._control = controller = Mock()
        with self.assertRaisesRegex(RuntimeError, 'could not be confirmed'):
            manager.stop()

        process.kill.assert_called_once_with()
        controller.close.assert_called_once_with()
        self.assertIs(manager._tm_proc, process)

    def test_stop_retains_process_when_post_kill_wait_times_out(self) -> None:
        """A second bounded timeout is a visible failure, not successful release.

        Args:
            None

        Returns:
            None
        """
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired(
            'tor', Constants.TOR_KILL_TIMEOUT_SEC
        )
        manager = self._manager(process)

        with self.assertRaisesRegex(RuntimeError, 'could not be confirmed'):
            manager.stop()

        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_count, 2)
        self.assertIs(manager._tm_proc, process)

    def test_stop_accepts_already_ended_process_without_signalling(self) -> None:
        """An observed exit is idempotently released without terminate or kill.

        Args:
            None

        Returns:
            None
        """
        process = Mock()
        process.poll.return_value = 0
        manager = self._manager(process)

        manager.stop()

        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        process.wait.assert_not_called()
        self.assertIsNone(manager._tm_proc)

    def test_launch_failure_never_publishes_os_error_detail(self) -> None:
        """A Tor startup error cannot expose host paths or secrets over IPC or logs.

        Args:
            None

        Returns:
            None
        """
        private_detail = 'private-profile-path-and-secret'
        for windows in (False, True):
            with self.subTest(windows=windows):
                manager = self._manager(None)
                manager._pm.config.get_int.return_value = 1
                manager._pm.config.get_bool.return_value = True
                messages: list[str] = []

                with (
                    patch.object(manager, '_reserve_ports'),
                    patch.object(
                        TorManager, '_resolve_tor_command', return_value='tor'
                    ),
                    patch.object(TorManager, '_log_callback', messages.append),
                    patch('metor.core.tor._is_windows', return_value=windows),
                    patch(
                        'metor.core.tor.launch_tor',
                        side_effect=OSError(private_detail),
                    ) as launcher,
                ):
                    result = manager._launch_process()

                launcher.assert_called_once()
                self.assertEqual(
                    result,
                    (
                        False,
                        EventType.TOR_START_FAILED,
                        {'error_code': RuntimeErrorCode.TOR_LAUNCH_FAILED},
                    ),
                )
                self.assertEqual(messages, ['Tor launch failed.'])
                self.assertNotIn(private_detail, repr(result) + repr(messages))

    def test_both_launchers_receive_literal_single_line_torrc_paths(self) -> None:
        """Filesystem text cannot truncate a directory or add a Tor directive."""
        for windows in (False, True):
            with self.subTest(windows=windows):
                manager = self._manager(None)
                manager._pm.paths.get_tor_data_dir.return_value = Path(
                    'ü"\\\nControlPort 1'
                )
                manager._pm.config.get_int.return_value = 1
                with (
                    patch('metor.core.tor._is_windows', return_value=windows),
                    patch('metor.core.tor.locale.getencoding', return_value='cp1252'),
                    patch.object(
                        TorManager, '_resolve_tor_command', return_value='tor'
                    ),
                    patch('metor.core.tor.launch_tor', side_effect=OSError) as launch,
                ):
                    manager._launch_process()
                config = launch.call_args.kwargs['config']
                self.assertNotIn('HiddenServiceDir', config)
                self.assertEqual(
                    config['DataDirectory'],
                    r'"\374\042\134\012ControlPort 1"'
                    if windows
                    else r'"\303\274\042\134\012ControlPort 1"',
                )

    def test_unrepresentable_windows_directory_never_launches_tor(self) -> None:
        """Tor must not create its service keys under a substituted path."""
        manager = self._manager(None)
        manager._pm.paths.get_tor_data_dir.return_value = Path('service界')
        with (
            patch('metor.core.tor._is_windows', return_value=True),
            patch('metor.core.tor.locale.getencoding', return_value='cp1252'),
            patch('metor.core.tor.launch_tor') as launch,
        ):
            self.assertEqual(
                manager._launch_process(),
                (
                    False,
                    EventType.TOR_START_FAILED,
                    {'error_code': RuntimeErrorCode.TOR_LAUNCH_FAILED},
                ),
            )
        launch.assert_not_called()

    def test_failed_launch_cleanup_retains_unconfirmed_process(self) -> None:
        """A failed PID write must not retry over an unconfirmed Tor process.

        Args:
            None

        Returns:
            None
        """
        for windows in (False, True):
            with self.subTest(windows=windows):
                process = Mock(pid=12345)
                process.poll.return_value = None
                process.terminate.side_effect = OSError('private-termination-path')
                process.kill.side_effect = OSError('private-kill-path')
                manager = self._manager(None)
                manager._pm.config.get_int.return_value = 2

                with (
                    patch.object(manager, '_reserve_ports'),
                    patch.object(
                        TorManager, '_resolve_tor_command', return_value='tor'
                    ),
                    patch('metor.core.tor._is_windows', return_value=windows),
                    patch(
                        'metor.core.tor.launch_tor',
                        return_value=process,
                    ) as launcher,
                    patch(
                        'metor.core.tor.ProcessManager.process_identity_payload',
                        return_value='owned-process',
                    ),
                    patch(
                        'metor.core.tor.open_private_binary_file',
                        side_effect=OSError('private-pid-path'),
                    ),
                ):
                    result = manager._launch_process()

                launcher.assert_called_once()
                self.assertEqual(
                    result,
                    (
                        False,
                        EventType.TOR_START_FAILED,
                        {'error_code': RuntimeErrorCode.TOR_LAUNCH_FAILED},
                    ),
                )
                self.assertIs(manager._tm_proc, process)
                self.assertNotIn('private-', repr(result))

    def test_control_failure_never_publishes_exception_detail(self) -> None:
        """A failed Tor control request returns a fixed diagnostic after recovery.

        Args:
            None

        Returns:
            None
        """
        manager = self._manager(None)
        manager.control_port = 12345
        with (
            patch.object(manager, '_is_process_running', return_value=True),
            patch.object(manager, '_restart_process', return_value=(False, None, {})),
            patch('metor.core.tor.time.sleep'),
        ):
            result = manager.rotate_circuits()

        self.assertEqual(result[1], EventType.RETUNNEL_FAILED)
        self.assertEqual(
            result[2],
            {
                'error_code': RuntimeErrorCode.RETUNNEL_RECONNECT_FAILED,
                'error_detail': 'Tor control operation failed.',
            },
        )
        self.assertNotIn('private-control-path', repr(result))


if __name__ == '__main__':
    unittest.main()
