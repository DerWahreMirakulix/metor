"""Private offline IPC authorization and confirmed sensitive-runtime cleanup."""

from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from metor.client import BufferedIpcEventReader
from metor.core.api import (
    ContactsDataEvent,
    GetContactsListCommand,
    IpcCommand,
    DaemonOfflineEvent,
)
from metor.core.daemon.headless import HeadlessDaemon
from metor.data import SqlManager
from metor.data.profile import ProfileManager
from metor.utils import Constants, FileLock


class HeadlessChannelSecurityTests(unittest.TestCase):
    """Offline credentials never authorize a discoverable localhost listener."""

    def setUp(self) -> None:
        """Isolates every encrypted profile and runtime resource."""
        temporary = TemporaryDirectory(prefix='metor-private-offline-')
        self.addCleanup(temporary.cleanup)
        data = patch.object(Constants, 'DATA', Path(temporary.name))
        data.start()
        self.addCleanup(data.stop)
        self.password = 'disposable-profile-password'
        result = ProfileManager.add_profile_folder(
            'offline', master_password=self.password
        )
        self.assertTrue(result.success)
        self.profile = ProfileManager('offline')
        self.addCleanup(SqlManager.close_connection, self.profile.paths.get_db_file())

    def test_other_local_sockets_cannot_reach_private_channel(self) -> None:
        """A new local caller cannot connect to either credential-bearing endpoint."""
        with HeadlessDaemon(self.profile, self.password) as daemon:
            connected = daemon.client_socket
            endpoints = (connected.getsockname(), connected.getpeername())
            self.assertFalse(connected.get_inheritable())
            self.assertEqual(
                connected.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN), 0
            )
            for endpoint in endpoints:
                with self.subTest(endpoint=endpoint):
                    with socket.socket(
                        connected.family, socket.SOCK_STREAM
                    ) as outsider:
                        outsider.settimeout(0.5)
                        with self.assertRaises(OSError):
                            outsider.connect(endpoint)
            connected.settimeout(Constants.DEFAULT_IPC_TIMEOUT)
            connected.sendall((GetContactsListCommand().to_json() + '\n').encode())
            event = BufferedIpcEventReader().read_from_socket(connected)
            self.assertIsInstance(event, ContactsDataEvent)
        self.assertIsNone(daemon._password)
        self.assertNotIn(
            str(self.profile.paths.get_db_file().absolute()), SqlManager._connections
        )

    def test_stop_joins_idle_reader_and_closes_both_private_endpoints(self) -> None:
        """An idle client cannot leave a worker or password alive after context exit."""
        daemon = HeadlessDaemon(self.profile, self.password)
        daemon.start()
        connected = daemon.client_socket
        worker = daemon._thread
        self.assertIsNotNone(worker)
        assert worker is not None
        daemon.stop()
        self.assertFalse(worker.is_alive())
        self.assertEqual(connected.fileno(), -1)
        self.assertIsNone(daemon._password)
        with self.assertRaises(RuntimeError):
            _ = daemon.client_socket
        daemon.stop()

    def test_stop_waits_for_command_before_clearing_keys(self) -> None:
        """A timeout reports incomplete teardown and does not race active key use."""
        entered, release, cleared = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        daemon = HeadlessDaemon(self.profile, self.password)
        key_manager = Mock()
        key_manager.clear_sensitive_state.side_effect = cleared.set
        daemon.__dict__['_km'] = key_manager

        def process(_command: IpcCommand, _conn: socket.socket) -> None:
            """Holds one command in its sensitive runtime until explicitly released."""
            entered.set()
            release.wait(2)

        with patch.object(daemon, '_process_command', side_effect=process):
            daemon.start()
            daemon.client_socket.sendall(
                (GetContactsListCommand().to_json() + '\n').encode()
            )
            try:
                self.assertTrue(entered.wait(1))
                with patch.object(Constants, 'HEADLESS_SHUTDOWN_TIMEOUT_SEC', 0.01):
                    with self.assertRaisesRegex(RuntimeError, 'did not stop'):
                        daemon.stop()
                self.assertFalse(cleared.is_set())
                self.assertEqual(daemon._password, self.password)
            finally:
                release.set()
                daemon.stop()
        self.assertTrue(cleared.is_set())
        self.assertIsNone(daemon._password)

    def test_failed_worker_start_closes_private_channel_and_credentials(self) -> None:
        """Partial startup never exposes sockets or retains the supplied password."""
        daemon = HeadlessDaemon(self.profile, self.password)
        with patch('threading.Thread.start', side_effect=RuntimeError('fixture')):
            with self.assertRaisesRegex(RuntimeError, 'fixture'):
                daemon.start()
        self.assertIsNone(daemon._server)
        self.assertIsNone(daemon._client)
        self.assertIsNone(daemon._password)
        daemon.stop()

    def test_failed_socketpair_creation_clears_supplied_credentials(self) -> None:
        """Socket-allocation failure releases secrets before context entry succeeds."""
        daemon = HeadlessDaemon(self.profile, self.password)
        with patch('socket.socketpair', side_effect=OSError('fixture')):
            with self.assertRaisesRegex(OSError, 'fixture'):
                daemon.start()
        self.assertIsNone(daemon._password)
        daemon.stop()

    def test_unpublished_managed_instance_refuses_offline_storage_access(self) -> None:
        """A child without a PID or IPC port still owns its exclusive profile runtime."""
        with FileLock(self.profile.paths.get_daemon_instance_lock_file()):
            with HeadlessDaemon(self.profile, self.password) as daemon:
                connected = daemon.client_socket
                connected.settimeout(Constants.DEFAULT_IPC_TIMEOUT)
                connected.sendall((GetContactsListCommand().to_json() + '\n').encode())
                event = BufferedIpcEventReader().read_from_socket(connected)
                self.assertIsInstance(event, DaemonOfflineEvent)
            self.assertNotIn('_km', daemon.__dict__)
            self.assertNotIn('_cm', daemon.__dict__)

    def test_storage_cleanup_finishes_under_lifecycle_gates_and_runs_once(self) -> None:
        """A later stop cannot close a new runtime's pooled SQL connection."""
        actual_close = SqlManager.close_connection
        closed: list[Path] = []

        def close_under_gate(path: Path) -> None:
            """Checks exclusion until the actual pooled database owner is released."""
            for lock in (
                self.profile.paths.get_daemon_start_lock_file(),
                self.profile.paths.get_daemon_instance_lock_file(),
            ):
                with self.assertRaises(TimeoutError):
                    with FileLock(lock, timeout=0.01):
                        pass
            actual_close(path)
            closed.append(path)

        daemon = HeadlessDaemon(self.profile, self.password)
        with patch.object(SqlManager, 'close_connection', side_effect=close_under_gate):
            daemon.start()
            try:
                connected = daemon.client_socket
                connected.settimeout(Constants.DEFAULT_IPC_TIMEOUT)
                connected.sendall((GetContactsListCommand().to_json() + '\n').encode())
                event = BufferedIpcEventReader().read_from_socket(connected)
                self.assertIsInstance(event, ContactsDataEvent)
                assert daemon._thread is not None
                daemon._thread.join(2)
                self.assertFalse(daemon._thread.is_alive())
                with FileLock(self.profile.paths.get_daemon_instance_lock_file()):
                    daemon.stop()
                self.assertEqual(closed, [self.profile.paths.get_db_file()])
            finally:
                daemon.stop()

    def test_failed_storage_cleanup_keeps_profile_fenced_until_safe_retry(self) -> None:
        """An unclosed SQL owner cannot be reused by a replacement profile runtime."""
        daemon = HeadlessDaemon(self.profile, self.password)
        daemon.start()
        try:
            with patch.object(
                SqlManager, 'close_connection', side_effect=OSError('fixture')
            ):
                connected = daemon.client_socket
                connected.settimeout(Constants.DEFAULT_IPC_TIMEOUT)
                connected.sendall((GetContactsListCommand().to_json() + '\n').encode())
                event = BufferedIpcEventReader().read_from_socket(connected)
                self.assertIsInstance(event, ContactsDataEvent)
                assert daemon._thread is not None
                daemon._thread.join(2)
                self.assertFalse(daemon._thread.is_alive())
                with self.assertRaisesRegex(RuntimeError, 'cleanup did not complete'):
                    daemon.stop()
                self.assertIsNone(daemon._password)
                with self.assertRaises(TimeoutError):
                    with FileLock(
                        self.profile.paths.get_daemon_instance_lock_file(), timeout=0.01
                    ):
                        pass
            daemon.stop()
            with FileLock(self.profile.paths.get_daemon_instance_lock_file()):
                self.assertNotIn(
                    str(self.profile.paths.get_db_file().absolute()),
                    SqlManager._connections,
                )
        finally:
            daemon.stop()


if __name__ == '__main__':
    unittest.main()
