"""Runtime startup failures release authority and acquired resources."""

import atexit
import base64
from contextlib import redirect_stderr
import hashlib
from io import StringIO
from pathlib import Path
import signal
import socket
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from metor.client import MetorClient, MetorRequestRejectedError
from metor.core.api import EventType, JsonValue
from metor.core.daemon.managed.engine import Daemon, DaemonLifecycle
from metor.core.daemon.managed.engine import RuntimeStartFailure, RuntimeStartupError
from metor.core.daemon.managed.factory import create_managed_daemon
from metor.core.daemon.managed.ipc import IpcServer
from metor.core.daemon.managed.network import NetworkManager
from metor.core.daemon.managed.outbox import OutboxWorker
from metor.core.key import KeyManager
from metor.core.tor import TorManager
from metor.application import DaemonStartPreparation
from metor.cli.handlers import CommandHandlers
from metor.data import ProfileManager, SqlManager
from metor.data.blob.store import BLOB_KEY_BYTES, EncryptedBlobStore
from metor.shared.network import decode_tor_v3_onion_public_key
from metor.utils import Constants

_PUBLIC = bytes(range(32))
_CHECKSUM = hashlib.sha3_256(b'.onion checksum' + _PUBLIC + b'\x03').digest()[:2]
SYNTHETIC_VALID_ONION = (
    base64.b32encode(_PUBLIC + _CHECKSUM + b'\x03').decode('ascii').lower().rstrip('=')
)


class RuntimeStartTransactionTests(unittest.TestCase):
    """Exercise temporary encrypted profiles through the real local SDK exchange."""

    def setUp(self) -> None:
        """Prepare one locked daemon with an owned temporary profile.

        Args:
            None
        Returns:
            None
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_patch = patch.object(Constants, 'DATA', Path(temporary.name))
        data_patch.start()
        self.addCleanup(data_patch.stop)
        self.profile = ProfileManager('startup')
        self.profile.initialize()
        KeyManager(self.profile, 'test-password').generate_keys()
        self.status = Mock()
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            self.daemon = Daemon(
                self.profile, start_locked=True, status_callback=self.status
            )
        atexit.unregister(self.daemon.stop)
        self.daemon._ipc.start()
        port = self.daemon._ipc.port
        assert port is not None
        provider = Mock()
        provider.get_unlock_password.return_value = 'test-password'
        self.provider = provider
        self.client = MetorClient(port, auth_provider=provider)
        self.addCleanup(self.daemon.stop)
        self.addCleanup(self.client.disconnect)

    @staticmethod
    def _synthetic_launch(
        manager: TorManager,
    ) -> tuple[bool, None, dict[str, JsonValue]]:
        """Substitute only the external Tor process launch.

        Args:
            manager: Actual Tor manager built by the daemon runtime factory.
        Returns:
            tuple[bool, None, dict[str, JsonValue]]: Synthetic launch success.
        """
        assert decode_tor_v3_onion_public_key(SYNTHETIC_VALID_ONION) == _PUBLIC
        manager.onion = SYNTHETIC_VALID_ONION
        assert manager.incoming_port is not None
        return True, None, {}

    def _assert_rejected_and_locked(self, phase: str, category: str) -> None:
        """Check the correlated rejection and post-release authority boundary.

        Args:
            phase: Expected safe start phase.
            category: Expected safe failure category.
        Returns:
            None
        """
        with self.assertRaises(MetorRequestRejectedError) as raised:
            self.client.bootstrap()
        self.assertIs(raised.exception.event.event_type, EventType.INTERNAL_ERROR)
        failure = self.daemon._last_start_failure
        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual((failure.phase, failure.category), (phase, category))
        self.assertIs(self.daemon._lifecycle, DaemonLifecycle.LOCKED)
        self.assertIsNone(self.daemon._tm)
        self.assertIsNone(self.daemon._km)
        self.assertFalse(self.daemon._session_access.authenticated_recipients())
        self.assertNotIn(
            str(self.profile.paths.get_db_file().absolute()), SqlManager._connections
        )
        self.assertFalse(
            (
                self.profile.paths.get_hidden_service_dir() / Constants.TOR_SECRET_KEY
            ).exists()
        )

    def test_thrown_tor_launch_rejects_then_clean_retry_succeeds(self) -> None:
        """A native launch exception rolls back and permits one later valid unlock.

        Args:
            None
        Returns:
            None
        """
        with (
            patch.object(
                TorManager,
                '_launch_process',
                side_effect=FileNotFoundError('private-sentinel'),
            ),
            patch.object(
                TorManager,
                '_resolve_tor_command',
                side_effect=AssertionError('Unexpected native resolution'),
            ),
        ):
            self._assert_rejected_and_locked('tor_start', 'FileNotFoundError')
        self.assertNotIn('private-sentinel', str(self.status.call_args_list))
        with patch.object(TorManager, '_launch_process', self._synthetic_launch):
            self.assertIsNotNone(self.client.bootstrap())
            self.assertIs(self.daemon._lifecycle, DaemonLifecycle.UNLOCKED)
            self.assertIsNotNone(self.client.runtime_snapshot())

    def test_false_tor_start_rejects_without_success_dto(self) -> None:
        """A negative starter result follows the same rollback path.

        Args:
            None
        Returns:
            None
        """
        with patch.object(
            TorManager,
            '_launch_process',
            return_value=(False, EventType.TOR_START_FAILED, {}),
        ):
            self._assert_rejected_and_locked('tor_start', 'Rejected')

    def test_listener_and_outbox_failures_release_started_tor(self) -> None:
        """Later service failures independently release already acquired services.

        Args:
            None
        Returns:
            None
        """
        original_stop = TorManager.stop
        stopped: list[TorManager] = []

        def record_stop(manager: TorManager) -> None:
            """Observe real Tor cleanup without replacing it.

            Args:
                manager: Runtime Tor manager.
            Returns:
                None
            """
            stopped.append(manager)
            original_stop(manager)

        with (
            patch.object(TorManager, '_launch_process', self._synthetic_launch),
            patch.object(TorManager, 'stop', record_stop),
            patch.object(
                NetworkManager,
                'start_listener',
                side_effect=OSError('private-listener'),
            ),
        ):
            self._assert_rejected_and_locked('network_listener', 'OSError')
        self.assertEqual(len(stopped), 1)
        self.assertNotIn('private-listener', str(self.status.call_args_list))

        with (
            patch.object(TorManager, '_launch_process', self._synthetic_launch),
            patch.object(TorManager, 'stop', record_stop),
            patch.object(
                OutboxWorker,
                'start',
                side_effect=RuntimeError('private-outbox'),
            ),
        ):
            self._assert_rejected_and_locked('outbox', 'RuntimeError')
        self.assertEqual(len(stopped), 2)
        self.assertNotIn('private-outbox', str(self.status.call_args_list))

    def test_partial_runtime_install_releases_constructed_resources(self) -> None:
        """An installation constructor failure cannot strand SQL or keys.

        Args:
            None
        Returns:
            None
        """
        with (
            patch.object(
                NetworkManager,
                '__init__',
                side_effect=RuntimeError('private-install'),
            ),
            patch.object(TorManager, '_launch_process') as launch,
        ):
            self._assert_rejected_and_locked('runtime_install', 'RuntimeError')
        launch.assert_not_called()
        self.assertNotIn('private-install', str(self.status.call_args_list))

    def test_wrong_password_never_reaches_external_launch(self) -> None:
        """Rejected credentials do not construct an externally started runtime.

        Args:
            None
        Returns:
            None
        """
        self.provider.get_unlock_password.return_value = 'wrong-password'
        with patch.object(TorManager, '_launch_process') as launch:
            with self.assertRaises(MetorRequestRejectedError) as raised:
                self.client.bootstrap()
        self.assertIs(
            raised.exception.event.event_type, EventType.LOCAL_AUTH_RATE_LIMITED
        )
        launch.assert_not_called()
        self.assertIs(self.daemon._lifecycle, DaemonLifecycle.LOCKED)
        self.assertIsNone(self.daemon._tm)

    def test_close_during_launch_cannot_commit_unlocked_runtime(self) -> None:
        """A concurrent stop fences an in-flight external launch before commit.

        Args:
            None
        Returns:
            None
        """
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        failures: list[Exception] = []

        def blocked_launch(
            manager: TorManager,
        ) -> tuple[bool, None, dict[str, JsonValue]]:
            """Hold one startup while close sets its cancellation fence.

            Args:
                manager: Actual runtime Tor manager.
            Returns:
                tuple[bool, None, dict[str, JsonValue]]: Synthetic launch success.
            """
            entered.set()
            if not release.wait(10):
                raise TimeoutError('Controlled launch gate was not released')
            return self._synthetic_launch(manager)

        def bootstrap() -> None:
            """Attempt SDK bootstrap while the daemon is closing.

            Args:
                None
            Returns:
                None
            """
            try:
                self.client.bootstrap()
            except Exception as error:
                failures.append(error)
            finally:
                finished.set()

        worker = threading.Thread(target=bootstrap, daemon=True)
        with patch.object(TorManager, '_launch_process', blocked_launch):
            try:
                worker.start()
                self.assertTrue(entered.wait(10))
                closer = threading.Thread(target=self.daemon.stop, daemon=True)
                closer.start()
                self.assertTrue(self.daemon._stop_flag.wait(2))
            finally:
                release.set()
                worker.join(10)
                if 'closer' in locals():
                    closer.join(10)
        self.assertTrue(finished.is_set())
        self.assertFalse(worker.is_alive())
        self.assertIsNot(self.daemon._lifecycle, DaemonLifecycle.UNLOCKED)
        self.assertIsNone(self.daemon._tm)
        self.assertFalse(self.daemon._session_access.authenticated_recipients())
        self.assertFalse(
            any(isinstance(error, RuntimeStartupError) for error in failures)
        )

    def test_partial_build_cleanup_is_retained_until_retry_succeeds(self) -> None:
        """Failed partial cleanup stays owned by the daemon for a later stop.

        Args:
            None
        Returns:
            None
        """
        original_close = SqlManager.close_connection
        close_calls = 0

        def delayed_close(path: str | Path) -> bool | None:
            """Model an initially unsuccessful database release.

            Args:
                path: Temporary profile database path.
            Returns:
                bool | None: False until the later retry calls the real close.
            """
            nonlocal close_calls
            close_calls += 1
            if close_calls <= 3:
                return False
            return original_close(path)

        with (
            patch.object(
                TorManager, '__init__', side_effect=RuntimeError('private-build')
            ),
            patch.object(SqlManager, 'close_connection', delayed_close),
        ):
            with self.assertRaises(MetorRequestRejectedError) as raised:
                self.client.bootstrap()
            self.assertIs(raised.exception.event.event_type, EventType.INTERNAL_ERROR)
            self.assertIs(self.daemon._lifecycle, DaemonLifecycle.LOCKING)
            self.assertIsNotNone(self.daemon._partial_build_cleanup)
            self.daemon.stop()
        self.assertIs(self.daemon._lifecycle, DaemonLifecycle.LOCKED)
        self.assertIsNone(self.daemon._partial_build_cleanup)
        self.assertGreaterEqual(close_calls, 4)
        self.assertNotIn('private-build', str(self.status.call_args_list))

    def test_direct_start_failure_raises_safe_error_and_stops(self) -> None:
        """A foreground start cannot exit successfully after a Tor rejection.

        Args:
            None
        Returns:
            None
        """
        self.client.disconnect()
        self.daemon.stop()
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            daemon = create_managed_daemon(
                self.profile,
                password='test-password',
                status_callback=self.status,
            )
        atexit.unregister(daemon.stop)
        with patch.object(
            TorManager,
            '_launch_process',
            return_value=(False, EventType.TOR_START_FAILED, {}),
        ):
            with self.assertRaises(RuntimeStartupError) as raised:
                daemon.run()
        self.assertEqual(
            (raised.exception.failure.phase, raised.exception.failure.category),
            ('tor_start', 'Rejected'),
        )
        self.assertTrue(daemon._stop_completed)
        self.assertIsNone(daemon._tm)

    def test_direct_runtime_install_failure_has_cleanup_owner(self) -> None:
        """A constructor failure releases its authenticated runtime bundle.

        Args:
            None
        Returns:
            None
        """
        self.client.disconnect()
        self.daemon.stop()
        with (
            patch('metor.core.daemon.managed.engine.daemon.signal.signal'),
            patch.object(
                NetworkManager,
                '__init__',
                side_effect=RuntimeError('private-constructor'),
            ),
        ):
            with self.assertRaises(RuntimeStartupError) as raised:
                create_managed_daemon(self.profile, password='test-password')
        self.assertEqual(raised.exception.failure.phase, 'runtime_install')
        self.assertNotIn('private-constructor', str(raised.exception))
        self.assertNotIn(
            str(self.profile.paths.get_db_file().absolute()), SqlManager._connections
        )

    def test_close_after_runtime_build_never_enters_tor_launch(self) -> None:
        """A stop during runtime build is fenced before native startup.

        Args:
            None
        Returns:
            None
        """
        from metor.core.daemon.managed.bootstrap import DaemonRuntime, build_runtime

        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def gated_build(
            pm: ProfileManager,
            password: str | None,
            *,
            enable_session_auth: bool,
        ) -> DaemonRuntime:
            """Pause after the real builder returns its owned runtime.

            Args:
                pm: Temporary profile.
                password: Synthetic test password.
                enable_session_auth: Existing daemon session policy.
            Returns:
                DaemonRuntime: The actual built runtime.
            """
            runtime = build_runtime(
                pm, password, enable_session_auth=enable_session_auth
            )
            entered.set()
            if not release.wait(10):
                raise TimeoutError('Controlled runtime build gate was not released')
            return runtime

        def bootstrap() -> None:
            """Complete one SDK bootstrap attempt after stop wins the fence.

            Args:
                None
            Returns:
                None
            """
            try:
                self.client.bootstrap()
            except Exception:
                pass
            finally:
                finished.set()

        worker = threading.Thread(target=bootstrap, daemon=True)
        with (
            patch(
                'metor.core.daemon.managed.engine.daemon.build_runtime',
                side_effect=gated_build,
            ),
            patch.object(TorManager, '_launch_process') as launch,
        ):
            try:
                worker.start()
                self.assertTrue(entered.wait(10))
                closer = threading.Thread(target=self.daemon.stop, daemon=True)
                closer.start()
                self.assertTrue(self.daemon._stop_flag.wait(2))
            finally:
                release.set()
                worker.join(10)
                if 'closer' in locals():
                    closer.join(10)
        self.assertTrue(finished.is_set())
        launch.assert_not_called()
        self.assertIsNot(self.daemon._lifecycle, DaemonLifecycle.UNLOCKED)
        self.assertIsNone(self.daemon._tm)

    def test_stop_during_locked_ipc_start_closes_listener(self) -> None:
        """A late locked-mode listener cannot reopen after stop completed.

        Args:
            None
        Returns:
            None
        """
        self.client.disconnect()
        self.daemon.stop()
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            daemon = Daemon(self.profile, start_locked=True)
        atexit.unregister(daemon.stop)
        entered = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        start_errors: list[Exception] = []
        original_start = daemon._ipc.start

        def delayed_start() -> None:
            """Pause before the real IPC listener acquisition.

            Args:
                None
            Returns:
                None
            """
            entered.set()
            if not release.wait(10):
                raise TimeoutError('Controlled IPC start gate was not released')
            original_start()

        def run() -> None:
            """Run one locked daemon under an external stop race.

            Args:
                None
            Returns:
                None
            """
            try:
                daemon.run()
            except Exception as error:
                start_errors.append(error)
            finally:
                completed.set()

        worker = threading.Thread(target=run, daemon=True)
        with patch.object(daemon._ipc, 'start', delayed_start):
            try:
                worker.start()
                self.assertTrue(entered.wait(10))
                closer = threading.Thread(target=daemon.stop, daemon=True)
                closer.start()
                self.assertTrue(daemon._stop_flag.wait(2))
            finally:
                release.set()
                worker.join(10)
                if 'closer' in locals():
                    closer.join(10)
        self.assertTrue(completed.is_set())
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(start_errors), 1)
        self.assertIsInstance(start_errors[0], RuntimeStartupError)
        self.assertTrue(daemon._stop_completed)
        self.assertIsNone(daemon._ipc._server)

    def test_stop_before_direct_start_prevents_tor_launch(self) -> None:
        """A stopped foreground daemon never begins a later Tor operation.

        Args:
            None
        Returns:
            None
        """
        self.client.disconnect()
        self.daemon.stop()
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            daemon = create_managed_daemon(self.profile, password='test-password')
        atexit.unregister(daemon.stop)
        daemon._stop_flag.set()
        with patch.object(TorManager, '_launch_process') as launch:
            with self.assertRaises(RuntimeStartupError) as raised:
                daemon.run()
        launch.assert_not_called()
        self.assertEqual(raised.exception.failure.phase, 'cancelled')
        self.assertTrue(daemon._stop_completed)

    def test_signal_during_direct_launch_defers_cleanup_until_launch_returns(
        self,
    ) -> None:
        """A signal cannot release resources before a native launch finishes.

        Args:
            None
        Returns:
            None
        """
        self.client.disconnect()
        self.daemon.stop()
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            daemon = create_managed_daemon(self.profile, password='test-password')
        atexit.unregister(daemon.stop)
        launched: list[TorManager] = []

        def interrupted_launch(
            manager: TorManager,
        ) -> tuple[bool, None, dict[str, JsonValue]]:
            """Simulate signal delivery inside the real Tor start path.

            Args:
                manager: Installed runtime's Tor manager.
            Returns:
                tuple[bool, None, dict[str, JsonValue]]: Synthetic launch result.
            """
            launched.append(manager)
            daemon._sig_handler(signal.SIGTERM, None)
            self.assertFalse(getattr(daemon, '_stop_completed', False))
            self.assertIs(daemon._tm, manager)
            manager.onion = SYNTHETIC_VALID_ONION
            return True, None, {}

        with (
            patch.object(TorManager, '_launch_process', interrupted_launch),
            patch.object(
                TorManager,
                '_resolve_tor_command',
                side_effect=AssertionError('Native Tor resolution was attempted'),
            ) as resolve,
        ):
            with self.assertRaises(RuntimeStartupError) as raised:
                daemon.run()
        self.assertEqual(len(launched), 1)
        self.assertEqual(raised.exception.failure.phase, 'cancelled')
        self.assertTrue(daemon._stop_completed)
        self.assertIsNone(daemon._tm)
        resolve.assert_not_called()

    def test_direct_build_error_maps_to_safe_stderr_and_nonzero(self) -> None:
        """A foreground build error reports only a fixed phase and category.

        Args:
            None
        Returns:
            None
        """
        with patch(
            'metor.core.daemon.managed.factory.build_runtime',
            side_effect=OSError('private-build-path'),
        ):
            with self.assertRaises(RuntimeStartupError) as raised:
                create_managed_daemon(self.profile, password='test-password')
        self.assertEqual(
            raised.exception.failure,
            RuntimeStartFailure('runtime_build', 'OSError'),
        )
        self.assertNotIn('private-build-path', str(raised.exception))

        sink = StringIO()
        with (
            patch(
                'metor.cli.handlers.prepare_managed_daemon_start',
                return_value=DaemonStartPreparation(False, False, False),
            ),
            patch('metor.cli.handlers.configure_daemon_runtime_logging'),
            patch(
                'metor.cli.handlers.run_managed_daemon',
                side_effect=raised.exception,
            ),
            redirect_stderr(sink),
        ):
            status = CommandHandlers.handle_daemon(self.profile, start_locked=True)
        self.assertEqual(status, 1)
        self.assertIn('runtime_build', sink.getvalue())
        self.assertIn('OSError', sink.getvalue())
        self.assertNotIn('private-build-path', sink.getvalue())


class ResourceConstructionTests(unittest.TestCase):
    """Check partial resource ownership without starting a background daemon."""

    def setUp(self) -> None:
        """Use an isolated profile for each resource construction probe.

        Args:
            None
        Returns:
            None
        """
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_patch = patch.object(Constants, 'DATA', Path(temporary.name))
        data_patch.start()
        self.addCleanup(data_patch.stop)
        self.profile = ProfileManager('resource')

    def test_ipc_listener_start_failure_closes_owned_socket(self) -> None:
        """A pre-bind IPC error closes its local socket immediately.

        Args:
            None
        Returns:
            None
        """
        server = IpcServer(self.profile, lambda _command, _connection: None)
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with (
            patch.object(
                self.profile,
                'get_static_port',
                side_effect=OSError('private-static-port'),
            ),
            patch('metor.core.daemon.managed.ipc.socket.socket', return_value=raw),
        ):
            with self.assertRaises(OSError):
                server.start()
        self.assertEqual(raw.fileno(), -1)
        self.assertIsNone(server.port)
        self.assertIsNone(server._server)

    def test_blob_constructor_failure_clears_acquired_key_copy(self) -> None:
        """Directory failure cannot strand a key inside a partial blob store.

        Args:
            None
        Returns:
            None
        """
        from metor.shared import secure_clear_buffer

        with (
            patch(
                'metor.data.blob.store._create_blob_directories',
                side_effect=OSError('private-directory'),
            ),
            patch(
                'metor.data.blob.store.secure_clear_buffer',
                wraps=secure_clear_buffer,
            ) as clear,
        ):
            with self.assertRaises(OSError):
                EncryptedBlobStore(
                    self.profile.paths.get_persistent_blob_dir(),
                    self.profile.paths.get_temporary_blob_dir(),
                    b'x' * BLOB_KEY_BYTES,
                )
        clear.assert_called_once()
        self.assertEqual(clear.call_args.args[0], bytearray(BLOB_KEY_BYTES))


if __name__ == '__main__':
    unittest.main()
