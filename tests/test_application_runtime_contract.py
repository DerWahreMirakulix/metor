"""Regression tests for application-layer runtime cleanup ownership."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.application import cleanup_local_runtime
from metor.data import ProfileManager
from metor.utils import Constants, ProcessManager


class ApplicationRuntimeContractTests(unittest.TestCase):
    """
    Covers application runtime contract regression scenarios.
    """

    def test_daemon_detector_accepts_only_supported_exact_start_forms(self) -> None:
        """Canonical CLI starts exclude aliases and module lookalikes.

        Args:
            None

        Returns:
            None
        """
        accepted = (
            ['/usr/bin/metor', 'daemon'],
            ['/usr/bin/metor', '-p', 'alpha', 'daemon'],
            [
                '/usr/bin/metor',
                '-p',
                'alpha',
                '--locked',
                '--daemon-child',
                'daemon',
            ],
        )
        rejected = (
            [sys.executable, '/tmp/metor-helper.py', 'daemon'],
            ['/tmp/python-malware', '-m', 'metor.daemon_main', 'daemon'],
            [sys.executable, '-m', 'other.metor', 'daemon'],
            [sys.executable, '-m', 'metor.daemon_main', 'daemon'],
            ['/usr/bin/metor-daemon', '-p', 'alpha', '--locked', 'daemon'],
            ['/usr/bin/metor', 'chat', 'daemon'],
        )
        for command in accepted:
            with self.subTest(command=command):
                proc = Mock()
                proc.cmdline.return_value = command
                self.assertTrue(ProcessManager._is_metor_daemon_process(proc, 'alpha'))
        for command in rejected:
            with self.subTest(command=command):
                proc = Mock()
                proc.cmdline.return_value = command
                self.assertFalse(ProcessManager._is_metor_daemon_process(proc, 'alpha'))

    def test_tor_detector_requires_profile_owned_runtime_arguments(self) -> None:
        """A Tor executable belongs to Metor only with both exact profile paths.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / 'alpha'
            data_dir = profile_dir / Constants.TOR_DATA_DIR
            service_dir = profile_dir / Constants.HIDDEN_SERVICE_DIR
            proc = Mock()
            proc.name.return_value = 'tor'
            proc.cmdline.return_value = [
                '/usr/bin/tor',
                '--DataDirectory',
                str(data_dir),
                '--HiddenServiceDir',
                str(service_dir),
            ]
            self.assertTrue(ProcessManager._is_tor_process(proc, profile_dir))

            proc.cmdline.return_value[-1] = str(Path(temp_dir) / 'foreign')
            self.assertFalse(ProcessManager._is_tor_process(proc, profile_dir))

    def test_cleanup_requires_lifetime_profile_and_known_owner(self) -> None:
        """Reused PIDs, mismatched profiles, and AccessDenied never authorize kill.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / Constants.DAEMON_PID_FILE
            validator = Mock(return_value=True)
            process = Mock()
            process.create_time.return_value = 20.0

            for payload in ('12345', '12345:10.0:alpha', '12345:20.0:beta'):
                with self.subTest(payload=payload):
                    pid_file.write_text(payload)
                    with (
                        patch(
                            'metor.utils.process.psutil.Process',
                            return_value=process,
                        ),
                        patch.object(
                            ProcessManager,
                            '_same_os_owner',
                            return_value=True,
                        ),
                        patch.object(
                            ProcessManager,
                            '_terminate_process',
                        ) as terminate,
                    ):
                        self.assertEqual(
                            ProcessManager._cleanup_pid_file_process(
                                pid_file,
                                'alpha',
                                validator,
                            ),
                            0,
                        )
                    terminate.assert_not_called()
                    self.assertTrue(pid_file.exists())

            pid_file.write_text('12345:20.0:alpha')
            with (
                patch(
                    'metor.utils.process.psutil.Process',
                    side_effect=psutil.AccessDenied(12345),
                ),
                patch.object(ProcessManager, '_terminate_process') as terminate,
            ):
                self.assertEqual(
                    ProcessManager._cleanup_pid_file_process(
                        pid_file,
                        'alpha',
                        validator,
                    ),
                    0,
                )
            terminate.assert_not_called()
            self.assertTrue(pid_file.exists())

    def test_daemon_runtime_state_persists_lifetime_and_profile(self) -> None:
        """New daemon PID metadata binds cleanup to one process generation.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            (data_root / 'alpha').mkdir()
            process = Mock()
            process.create_time.return_value = 42.5
            with (
                patch.object(Constants, 'DATA', data_root),
                patch('metor.utils.process.psutil.Process', return_value=process),
            ):
                profile = ProfileManager('alpha')
                profile.set_daemon_port(43111, 12345)

            payload = profile.paths.get_daemon_pid_file().read_text()
            self.assertEqual(payload, '12345:42.5:alpha')
            self.assertEqual(profile.get_daemon_pid(), 12345)

    def test_windows_owner_check_is_conservative(self) -> None:
        """Windows usernames must match and AccessDenied remains unknown.

        Args:
            None

        Returns:
            None
        """
        candidate = Mock()
        current = Mock()
        current.username.return_value = 'DOMAIN\\alice'
        with (
            patch('metor.utils.process.os.name', 'nt'),
            patch('metor.utils.process.psutil.Process', return_value=current),
        ):
            candidate.username.return_value = 'DOMAIN\\alice'
            self.assertTrue(ProcessManager._same_os_owner(candidate))
            candidate.username.return_value = 'DOMAIN\\bob'
            self.assertFalse(ProcessManager._same_os_owner(candidate))
            candidate.username.side_effect = psutil.AccessDenied(12345)
            self.assertIsNone(ProcessManager._same_os_owner(candidate))

    def test_cleanup_terminates_only_fully_verified_identity(self) -> None:
        """All identity proofs permit bounded termination and metadata removal.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / Constants.DAEMON_PID_FILE
            pid_file.write_text('12345:20.0:alpha')
            process = Mock()
            process.create_time.return_value = 20.0
            validator = Mock(return_value=True)
            with (
                patch('metor.utils.process.psutil.Process', return_value=process),
                patch.object(ProcessManager, '_same_os_owner', return_value=True),
                patch.object(
                    ProcessManager,
                    '_terminate_process',
                    return_value=True,
                ) as terminate,
            ):
                killed = ProcessManager._cleanup_pid_file_process(
                    pid_file,
                    'alpha',
                    validator,
                )

            self.assertEqual(killed, 1)
            validator.assert_called_once_with(process)
            terminate.assert_called_once_with(process)
            self.assertFalse(pid_file.exists())

    @staticmethod
    def _write_runtime_state(
        data_dir: Path,
        profile_name: str,
        *,
        daemon_pid: str | None = None,
        daemon_port: str | None = None,
    ) -> Path:
        """
        Writes runtime state for the surrounding tests.

        Args:
            data_dir (Path): The data dir.
            profile_name (str): The profile name.
            daemon_pid (str | None): The daemon PID.
            daemon_port (str | None): The daemon port.

        Returns:
            Path: The computed return value.
        """

        profile_dir = data_dir / profile_name
        profile_dir.mkdir(parents=True)

        if daemon_pid is not None:
            (profile_dir / Constants.DAEMON_PID_FILE).write_text(daemon_pid)

        if daemon_port is not None:
            (profile_dir / Constants.DAEMON_PORT_FILE).write_text(daemon_port)

        return profile_dir

    def test_cleanup_local_runtime_clears_only_dead_pid_owned_state_by_default(
        self,
    ) -> None:
        """
        Verifies that cleanup local runtime clears only dead PID owned state by default.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            stale_dir = self._write_runtime_state(
                data_dir,
                'stale',
                daemon_pid='999999',
                daemon_port='43111',
            )
            active_dir = self._write_runtime_state(
                data_dir,
                'active',
                daemon_pid='12345',
                daemon_port='43112',
            )
            damaged_dir = self._write_runtime_state(
                data_dir,
                'damaged',
                daemon_port='43113',
            )

            with (
                patch.object(Constants, 'DATA', data_dir),
                patch.object(ProcessManager, 'cleanup_processes', return_value=0),
                patch.object(
                    ProcessManager,
                    'is_pid_running',
                    side_effect=lambda pid: pid == 12345,
                ),
            ):
                result = cleanup_local_runtime(force=False)

            self.assertEqual(result.killed_processes, 0)
            self.assertEqual(result.cleared_runtime_state, 1)
            self.assertFalse((stale_dir / Constants.DAEMON_PID_FILE).exists())
            self.assertFalse((stale_dir / Constants.DAEMON_PORT_FILE).exists())
            self.assertTrue((active_dir / Constants.DAEMON_PID_FILE).exists())
            self.assertTrue((active_dir / Constants.DAEMON_PORT_FILE).exists())
            self.assertTrue((damaged_dir / Constants.DAEMON_PORT_FILE).exists())

    def test_cleanup_local_runtime_force_clears_orphaned_runtime_state(self) -> None:
        """
        Verifies that cleanup local runtime force clears orphaned runtime state.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            damaged_dir = self._write_runtime_state(
                data_dir,
                'damaged',
                daemon_port='43113',
            )

            with (
                patch.object(Constants, 'DATA', data_dir),
                patch.object(ProcessManager, 'cleanup_processes', return_value=0),
            ):
                result = cleanup_local_runtime(force=True)

            self.assertEqual(result.killed_processes, 0)
            self.assertEqual(result.cleared_runtime_state, 1)
            self.assertFalse((damaged_dir / Constants.DAEMON_PORT_FILE).exists())

    def test_cleanup_clears_state_from_a_reused_pid_without_terminating_it(
        self,
    ) -> None:
        """Lifetime mismatch expires metadata but never targets the new process.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            profile_dir = self._write_runtime_state(
                data_dir,
                'alpha',
                daemon_pid='12345:10.0:alpha',
                daemon_port='43111',
            )
            reused = Mock()
            reused.create_time.return_value = 20.0
            with (
                patch.object(Constants, 'DATA', data_dir),
                patch.object(ProcessManager, 'cleanup_processes', return_value=0),
                patch('metor.utils.process.psutil.Process', return_value=reused),
                patch.object(ProcessManager, '_same_os_owner', return_value=True),
                patch.object(ProcessManager, '_terminate_process') as terminate,
            ):
                result = cleanup_local_runtime()

            self.assertEqual(result.cleared_runtime_state, 1)
            terminate.assert_not_called()
            self.assertFalse((profile_dir / Constants.DAEMON_PID_FILE).exists())
            self.assertFalse((profile_dir / Constants.DAEMON_PORT_FILE).exists())

    def test_pid_file_cleanup_preserves_live_state_when_termination_fails(self) -> None:
        """
        Verifies that PID file cleanup preserves live state when termination fails.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / Constants.DAEMON_PID_FILE
            pid_file.write_text('12345:10.0:alpha')
            process = Mock()
            process.create_time.return_value = 10.0

            with (
                patch(
                    'metor.utils.process.psutil.Process',
                    return_value=process,
                ),
                patch.object(ProcessManager, '_same_os_owner', return_value=True),
                patch.object(ProcessManager, '_terminate_process', return_value=False),
            ):
                killed = ProcessManager._cleanup_pid_file_process(
                    pid_file,
                    'alpha',
                    lambda _proc: True,
                )

            self.assertEqual(killed, 0)
            self.assertTrue(pid_file.exists())

    def test_daemon_launch_command_uses_public_metor_child_entry(self) -> None:
        """
        Verifies that daemon autostart uses the canonical public Metor command.

        Args:
            None

        Returns:
            None
        """
        from metor.application.runtime.daemon import _build_daemon_launch_command
        from unittest.mock import Mock

        pm = Mock()
        pm.profile_name = 'default'

        cmd = _build_daemon_launch_command(
            pm, start_locked=False, startup_session_auth_stdin=False
        )
        self.assertEqual(Path(cmd[0]).name, 'metor')
        self.assertIn('--daemon-child', cmd)
        self.assertNotIn('metor.daemon_main', cmd)
        self.assertNotIn('metor.ui', ' '.join(cmd))


if __name__ == '__main__':
    unittest.main()
