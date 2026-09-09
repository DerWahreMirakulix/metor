"""Contract tests for secure daemon runtime locking."""

import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import CommandType, IpcCommand, LockCommand
from metor.core.daemon.managed.engine import Daemon, DaemonLifecycle


class DaemonLockLifecycleTests(unittest.TestCase):
    """Covers runtime teardown without daemon shutdown."""

    def test_lock_command_round_trips_over_typed_ipc(self) -> None:
        """Verifies the lock operation is registered in the public wire API.

        Args:
            None

        Returns:
            None
        """
        command = IpcCommand.from_dict({'command_type': CommandType.LOCK.value})
        self.assertIsInstance(command, LockCommand)

    @patch('metor.core.daemon.managed.engine.SqlManager.close_connection')
    def test_lock_releases_runtime_without_stopping_daemon(
        self,
        close_connection: Mock,
    ) -> None:
        """Verifies sensitive runtime references and sessions are released.

        Args:
            close_connection (Mock): Patched pooled database closer.

        Returns:
            None
        """
        daemon = Daemon.__new__(Daemon)
        daemon._lifecycle = DaemonLifecycle.UNLOCKED
        daemon._stop_flag = threading.Event()
        daemon._runtime_stop_flag = threading.Event()
        daemon._client_state_lock = threading.Lock()
        daemon._authenticated_clients = {Mock()}
        daemon._session_consumers = {Mock()}
        daemon._local_auth = Mock()
        daemon._outbox = Mock()
        daemon._network_handler = Mock()
        daemon._network = Mock()
        daemon._tm = Mock()
        daemon._km = Mock()
        daemon._pm = Mock()
        daemon._pm.paths.get_db_file.return_value = Path('/tmp/metor-lock-test.db')
        daemon._pm.paths.get_config_dir.return_value = Path('/tmp')
        daemon._db_handler = Mock()
        daemon._sys_handler = Mock()
        daemon._crypto = Mock()
        daemon._cm = Mock()
        daemon._hm = Mock()
        daemon._mm = Mock()

        daemon._lock_runtime()

        self.assertIs(daemon._lifecycle, DaemonLifecycle.LOCKED)
        self.assertFalse(daemon._stop_flag.is_set())
        self.assertTrue(daemon._runtime_stop_flag.is_set())
        self.assertEqual(daemon._authenticated_clients, set())
        self.assertEqual(daemon._session_consumers, set())
        close_connection.assert_called_once()
        self.assertIsNone(daemon._km)
        self.assertIsNone(daemon._network)
        self.assertIsNone(daemon._db_handler)


if __name__ == '__main__':
    unittest.main()
