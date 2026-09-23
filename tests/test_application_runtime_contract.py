"""Regression tests for application-layer runtime cleanup ownership."""

# ruff: noqa: E402

import json
import os
import subprocess
import sys
import sysconfig
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.application import cleanup_local_runtime
from metor.data import ProfileManager
from metor.utils import Constants, ProcessManager, open_private_binary_file


def _identity_payload(
    pid: int,
    create_time: float,
    profile_name: str,
    *,
    role: str = Constants.PROCESS_ROLE_DAEMON,
    executable: Path | None = None,
    installation_root: Path | None = None,
) -> str:
    """Builds strict managed-process metadata without inspecting a real PID.

    Args:
        pid (int): Test process identifier.
        create_time (float): Test process creation timestamp.
        profile_name (str): Owning test profile.
        role (str): Managed role name.
        executable (Path | None): Recorded executable.
        installation_root (Path | None): Recorded installation root.

    Returns:
        str: Serialized strict process identity.
    """
    return json.dumps(
        {
            'create_time': create_time,
            'executable': str((executable or Path(sys.executable)).resolve()),
            'installation_root': str(
                installation_root or ProcessManager._installation_root()
            ),
            'pid': pid,
            'profile': profile_name,
            'role': role,
        },
        separators=(',', ':'),
        sort_keys=True,
    )


def _write_identity(path: Path, payload: str) -> None:
    """Writes owner-only managed-process metadata for a test.

    Args:
        path (Path): Destination metadata file.
        payload (str): Serialized metadata.

    Returns:
        None
    """
    with open_private_binary_file(path) as handle:
        handle.write(payload.encode('utf-8'))


def _make_identity_foreign_writable(path: Path) -> None:
    """Makes one fixture writable by a foreign identity on the active platform.

    Args:
        path (Path): Private process-identity fixture to expose deliberately.

    Returns:
        None
    """
    if os.name != 'nt':
        path.chmod(0o644)
        return
    result = subprocess.run(
        ['icacls', str(path), '/grant', '*S-1-1-0:(W)'],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)


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
        interpreter = str(Path(sys.executable).resolve())
        scripts = Path(sysconfig.get_path('scripts')).resolve()
        launcher_name = 'metor.exe' if os.name == 'nt' else 'metor'
        launcher = str(scripts / launcher_name)
        accepted = (
            [interpreter, '-I', '-m', 'metor', '-p', 'alpha', 'daemon'],
            [interpreter, '-I', '-m', 'metor', 'daemon', '--profile=alpha'],
            [
                interpreter,
                launcher,
                '-p',
                'alpha',
                'daemon',
                '--non-interactive',
                '--locked',
            ],
        )
        rejected = (
            [sys.executable, '/tmp/metor-helper.py', 'daemon'],
            ['/tmp/python-malware', '-m', 'metor.daemon_main', 'daemon'],
            [sys.executable, '-m', 'other.metor', 'daemon'],
            [interpreter, '-m', 'metor', '-p', 'alpha', 'daemon'],
            [sys.executable, '-m', 'metor.daemon_main', 'daemon'],
            ['/usr/bin/metor-daemon', '-p', 'alpha', '--locked', 'daemon'],
            ['/usr/bin/metor', 'chat', 'daemon'],
            [interpreter, '-m', 'metor', '-p', 'beta', 'daemon'],
            [
                interpreter,
                '-m',
                'metor',
                '-p',
                'alpha',
                'daemon',
                '--startup-session-auth-stdin',
            ],
            [
                interpreter,
                '-m',
                'metor',
                '-p',
                'alpha',
                '--profile=alpha',
                'daemon',
            ],
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

    def test_daemon_detector_accepts_an_actual_owned_shebang_process(self) -> None:
        """The Linux console-script argv shape is verified against a live child.

        Args:
            None

        Returns:
            None
        """
        if sys.platform == 'win32':
            self.skipTest('POSIX shebang execution is Linux-specific.')
        with TemporaryDirectory() as temp_dir:
            scripts = Path(temp_dir)
            launcher = scripts / 'metor'
            launcher.write_text(
                f'#!{Path(sys.executable).resolve()}\nimport time\ntime.sleep(30)\n'
            )
            launcher.chmod(0o700)
            child = subprocess.Popen(
                [
                    str(launcher),
                    '-p',
                    'alpha',
                    'daemon',
                    '--non-interactive',
                ]
            )
            try:
                process = psutil.Process(child.pid)
                with patch(
                    'metor.utils.process.sysconfig.get_path',
                    return_value=str(scripts),
                ):
                    self.assertTrue(
                        ProcessManager._is_metor_daemon_process(process, 'alpha')
                    )
            finally:
                child.terminate()
                child.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)

    def test_daemon_detector_accepts_exact_windows_launcher_form(self) -> None:
        """The Windows launcher must belong to the current scripts directory.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            scripts = Path(temp_dir)
            launcher = scripts / 'metor.exe'
            launcher.touch()
            process = Mock()
            process.cmdline.return_value = [
                str(launcher),
                '-p',
                'alpha',
                'daemon',
                '--non-interactive',
            ]
            os_double = Mock(wraps=os)
            os_double.name = 'nt'
            with (
                patch('metor.utils.process.os', os_double),
                patch(
                    'metor.utils.process.sysconfig.get_path',
                    return_value=str(scripts),
                ),
            ):
                self.assertTrue(
                    ProcessManager._is_metor_daemon_process(process, 'alpha')
                )

            process.cmdline.return_value[0] = str(scripts / 'foreign.exe')
            with (
                patch('metor.utils.process.os', os_double),
                patch(
                    'metor.utils.process.sysconfig.get_path',
                    return_value=str(scripts),
                ),
            ):
                self.assertFalse(
                    ProcessManager._is_metor_daemon_process(process, 'alpha')
                )

    def test_managed_daemon_accepts_same_interpreter_through_path_alias(self) -> None:
        """Native aliases and the exact Windows venv base remain recognized."""
        with TemporaryDirectory() as temp_dir:
            primary = Path(temp_dir) / 'python-primary.exe'
            alias = Path(temp_dir) / 'python-alias.exe'
            base = Path(temp_dir) / 'python-base.exe'
            foreign = Path(temp_dir) / 'python-foreign.exe'
            primary.touch()
            alias.hardlink_to(primary)
            base.touch()
            foreign.touch()

            identity = Mock()
            identity.pid = 12345
            identity.create_time = 20.0
            identity.profile_name = 'alpha'
            identity.role = Constants.PROCESS_ROLE_DAEMON
            identity.executable = str(alias)
            identity.installation_root = str(ProcessManager._installation_root())

            process = Mock()
            process.create_time.return_value = 20.0
            process.cmdline.return_value = [
                str(alias),
                '-I',
                '-m',
                'metor',
                '-p',
                'alpha',
                'daemon',
                '--non-interactive',
                '--locked',
            ]
            process.is_running.return_value = True
            process.status.return_value = psutil.STATUS_RUNNING

            os_double = Mock(wraps=os)
            os_double.name = 'nt'
            with (
                patch('metor.utils.process.os', os_double),
                patch('metor.utils.process.sys.executable', str(primary)),
                patch(
                    'metor.utils.process.sys._base_executable',
                    str(base),
                    create=True,
                ),
                patch.object(
                    ProcessManager, '_read_process_identity', return_value=identity
                ),
                patch('metor.utils.process.psutil.Process', return_value=process),
                patch.object(ProcessManager, '_same_os_owner', return_value=True),
            ):
                self.assertTrue(
                    ProcessManager.is_managed_process_running(
                        Path(temp_dir) / Constants.DAEMON_PID_FILE,
                        'alpha',
                    )
                )
                process.cmdline.return_value[0] = str(base)
                self.assertTrue(
                    ProcessManager.is_managed_process_running(
                        Path(temp_dir) / Constants.DAEMON_PID_FILE,
                        'alpha',
                    )
                )
                process.cmdline.return_value[0] = str(foreign)
                self.assertIsNone(
                    ProcessManager.is_managed_process_running(
                        Path(temp_dir) / Constants.DAEMON_PID_FILE,
                        'alpha',
                    )
                )

    def test_process_identity_rejects_nonfinite_foreign_and_exposed_metadata(
        self,
    ) -> None:
        """Untrusted lifetime, installation, and permission data never confirms a PID.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / Constants.DAEMON_PID_FILE
            for create_time in (float('nan'), float('inf'), float('-inf'), -1.0):
                with self.subTest(create_time=create_time):
                    _write_identity(
                        pid_file,
                        _identity_payload(12345, create_time, 'alpha'),
                    )
                    self.assertIsNone(
                        ProcessManager.managed_process_pid(
                            pid_file,
                            'alpha',
                            Constants.PROCESS_ROLE_DAEMON,
                        )
                    )

            _write_identity(
                pid_file,
                _identity_payload(
                    12345,
                    20.0,
                    'alpha',
                    installation_root=Path(temp_dir) / 'foreign',
                ),
            )
            self.assertIsNone(
                ProcessManager.managed_process_pid(
                    pid_file,
                    'alpha',
                    Constants.PROCESS_ROLE_DAEMON,
                )
            )

            _write_identity(pid_file, _identity_payload(12345, 20.0, 'alpha'))
            _make_identity_foreign_writable(pid_file)
            self.assertIsNone(ProcessManager._read_process_identity(pid_file))

    def test_tor_detector_requires_profile_owned_runtime_arguments(self) -> None:
        """A Tor executable belongs to Metor only with both exact profile paths.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / 'alpha'
            tor_executable = Path(temp_dir) / 'tor'
            tor_executable.touch()
            proc = Mock()
            proc.exe.return_value = str(tor_executable)
            pid_file = profile_dir / 'tor.pid'
            profile_dir.mkdir()
            _write_identity(
                pid_file,
                _identity_payload(
                    12345,
                    20.0,
                    'alpha',
                    role=Constants.PROCESS_ROLE_TOR,
                    executable=tor_executable,
                ),
            )
            identity = ProcessManager._read_process_identity(pid_file)
            self.assertIsNotNone(identity)
            self.assertTrue(
                ProcessManager._is_tor_process(
                    proc,
                    profile_dir,
                    identity=identity,
                )
            )

            proc.exe.return_value = str(Path(temp_dir) / 'foreign')
            self.assertFalse(
                ProcessManager._is_tor_process(
                    proc,
                    profile_dir,
                    identity=identity,
                )
            )

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

            for payload in (
                '12345',
                _identity_payload(12345, 10.0, 'alpha'),
                _identity_payload(12345, 20.0, 'beta'),
            ):
                with self.subTest(payload=payload):
                    _write_identity(pid_file, payload)
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

            _write_identity(pid_file, _identity_payload(12345, 20.0, 'alpha'))
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

            payload = json.loads(profile.paths.get_daemon_pid_file().read_text())
            self.assertEqual(payload['create_time'], 42.5)
            self.assertEqual(payload['profile'], 'alpha')
            self.assertEqual(payload['role'], Constants.PROCESS_ROLE_DAEMON)
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
            _write_identity(pid_file, _identity_payload(12345, 20.0, 'alpha'))
            identity = ProcessManager._read_process_identity(pid_file)
            self.assertIsNotNone(identity)
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
            validator.assert_called_once_with(process, identity)
            terminate.assert_called_once_with(process)
            self.assertFalse(pid_file.exists())

    @staticmethod
    def _write_runtime_state(
        data_dir: Path,
        profile_name: str,
        *,
        daemon_identity: tuple[int, float] | None = None,
        malformed_pid: str | None = None,
        daemon_port: str | None = None,
    ) -> Path:
        """
        Writes runtime state for the surrounding tests.

        Args:
            data_dir (Path): The data dir.
            profile_name (str): The profile name.
            daemon_identity (tuple[int, float] | None): PID and process creation time.
            malformed_pid (str | None): Explicit malformed metadata payload.
            daemon_port (str | None): The daemon port.

        Returns:
            Path: The computed return value.
        """

        profile_dir = data_dir / profile_name
        profile_dir.mkdir(parents=True)

        pid_file = profile_dir / Constants.DAEMON_PID_FILE
        if daemon_identity is not None:
            _write_identity(
                pid_file,
                _identity_payload(
                    daemon_identity[0],
                    daemon_identity[1],
                    profile_name,
                ),
            )
        elif malformed_pid is not None:
            _write_identity(pid_file, malformed_pid)

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
                daemon_identity=(999999, 10.0),
                daemon_port='43111',
            )
            active_dir = self._write_runtime_state(
                data_dir,
                'active',
                daemon_identity=(12345, 20.0),
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
                    'is_managed_process_running',
                    side_effect=lambda _path, profile: profile == 'active',
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
                daemon_identity=(12345, 10.0),
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
            _write_identity(pid_file, _identity_payload(12345, 10.0, 'alpha'))
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
                    lambda _proc, _identity: True,
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
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(cmd[1:4], ['-I', '-m', 'metor'])
        self.assertIn('--non-interactive', cmd)
        self.assertNotIn('--daemon-child', cmd)
        self.assertNotIn('metor.daemon_main', cmd)
        self.assertNotIn('metor.ui', ' '.join(cmd))


if __name__ == '__main__':
    unittest.main()
