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

    @patch('metor.core.daemon.managed.engine.daemon.SqlManager.close_connection')
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
        daemon._session_access = Mock()
        daemon._outbox = Mock()
        daemon._command_dispatcher = Mock()
        daemon._network = Mock()
        daemon._session_maintenance = Mock()
        daemon._tm = Mock()
        key_manager = Mock()
        blob_store = Mock()
        daemon._km = key_manager
        daemon._blob_store = blob_store
        daemon._pm = Mock()
        daemon._pm.paths.get_db_file.return_value = Path('/tmp/metor-lock-test.db')
        daemon._pm.paths.get_config_dir.return_value = Path('/tmp')
        daemon._crypto = Mock()
        daemon._cm = Mock()
        daemon._hm = Mock()
        daemon._mm = Mock()

        daemon._lock_runtime()

        self.assertIs(daemon._lifecycle, DaemonLifecycle.LOCKED)
        self.assertFalse(daemon._stop_flag.is_set())
        self.assertTrue(daemon._runtime_stop_flag.is_set())
        daemon._session_access.clear_all.assert_called_once_with()
        daemon._command_dispatcher.clear_runtime_handlers.assert_called_once_with()
        close_connection.assert_called_once()
        key_manager.clear_sensitive_state.assert_called_once_with()
        blob_store.close.assert_called_once_with()
        self.assertIsNone(daemon._km)
        self.assertIsNone(daemon._blob_store)
        self.assertIsNone(daemon._network)
        self.assertIsNone(daemon._session_maintenance)


if __name__ == '__main__':
    unittest.main()
