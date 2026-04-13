"""Regression tests for application-layer runtime cleanup ownership."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.application import cleanup_local_runtime
from metor.utils import Constants, ProcessManager


class ApplicationRuntimeContractTests(unittest.TestCase):
    @staticmethod
    def _write_runtime_state(
        data_dir: Path,
        profile_name: str,
        *,
        daemon_pid: str | None = None,
        daemon_port: str | None = None,
    ) -> Path:
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

    def test_pid_file_cleanup_preserves_live_state_when_termination_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            pid_file = Path(temp_dir) / Constants.DAEMON_PID_FILE
            pid_file.write_text('12345')

            with (
                patch.object(ProcessManager, 'is_pid_running', return_value=True),
                patch(
                    'metor.utils.process.psutil.Process',
                    return_value=cast(object, object()),
                ),
                patch.object(ProcessManager, '_terminate_process', return_value=False),
            ):
                killed = ProcessManager._cleanup_pid_file_process(
                    pid_file,
                    lambda _proc: True,
                )

            self.assertEqual(killed, 0)
            self.assertTrue(pid_file.exists())


if __name__ == '__main__':
    unittest.main()
