"""A real temporary encrypted daemon may initialize beyond ordinary IPC time."""

import atexit
import base64
import hashlib
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

from metor.client import MetorClient
from metor.client.auth import IpcAuthResult
from metor.core.api import DaemonLockedEvent, InitCommand, InitEvent, JsonValue
from metor.core.daemon.managed.engine import Daemon, DaemonLifecycle
from metor.core.key import KeyManager
from metor.core.tor import TorManager
from metor.data import ProfileManager
from metor.shared.network import decode_tor_v3_onion_public_key
from metor.utils import Constants
from metor.versioning import IPC_PROTOCOL_VERSION, IPC_PROTOCOL_MIN_SUPPORTED


COLD_UNLOCK_MARGIN_SEC = 1.0
_PUBLIC = bytes(range(32))
_CHECKSUM = hashlib.sha3_256(b'.onion checksum' + _PUBLIC + b'\x03').digest()[:2]
SYNTHETIC_VALID_ONION = (
    base64.b32encode(_PUBLIC + _CHECKSUM + b'\x03').decode('ascii').lower().rstrip('=')
)


class ColdUnlockBudgetTests(unittest.TestCase):
    """Use a real locked runtime and SDK IPC with a controlled startup delay."""

    def test_cold_unlock_above_ordinary_ipc_deadline(self) -> None:
        """Finish real unlock within its own budget after the normal IPC deadline.

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
        profile = ProfileManager('cold')
        profile.initialize()
        KeyManager(profile, 'test-password').generate_keys()
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            daemon = Daemon(profile, start_locked=True)
        atexit.unregister(daemon.stop)
        daemon._ipc.start()
        provider = Mock()
        provider.get_unlock_password.return_value = 'test-password'
        port = daemon._ipc.port
        assert port is not None
        client = MetorClient(port, auth_provider=provider)
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        launched: list[TorManager] = []
        entered_at: list[float] = []
        completed_at: list[float] = []
        outcomes: list[InitEvent | None] = []
        failures: list[Exception] = []

        def controlled_launch(
            manager: TorManager,
        ) -> tuple[bool, None, dict[str, JsonValue]]:
            """Hold the actual runtime's Tor manager at its external launch boundary.

            Args:
                manager: Tor manager constructed by the production runtime builder.
            Returns:
                tuple[bool, None, dict[str, JsonValue]]: Successful synthetic launch.
            """
            assert decode_tor_v3_onion_public_key(SYNTHETIC_VALID_ONION) == _PUBLIC
            launched.append(manager)
            manager.onion = SYNTHETIC_VALID_ONION
            assert manager.incoming_port is not None
            entered_at.append(time.monotonic())
            entered.set()
            if not release.wait(Constants.MAX_UNLOCK_INITIALIZATION_WAIT_SEC):
                raise TimeoutError('Controlled Tor launch was not released')
            return True, None, {}

        def bootstrap() -> None:
            """Run the normal SDK unlock exchange in one bounded test worker.

            Args:
                None
            Returns:
                None
            """
            try:
                outcomes.append(client.bootstrap())
            except Exception as error:
                failures.append(error)
            finally:
                completed_at.append(time.monotonic())
                finished.set()

        worker = threading.Thread(target=bootstrap, daemon=True)
        started_at = time.monotonic()
        try:
            with (
                patch.object(TorManager, '_launch_process', controlled_launch),
                patch.object(
                    TorManager,
                    '_resolve_tor_command',
                    side_effect=AssertionError('Native Tor resolution was attempted'),
                ) as resolve,
                patch(
                    'stem.process.launch_tor_with_config',
                    side_effect=AssertionError('Native Tor launch was attempted'),
                ) as native_launch,
            ):
                worker.start()
                self.assertTrue(
                    entered.wait(Constants.MAX_UNLOCK_INITIALIZATION_WAIT_SEC)
                )
                self.assertIs(daemon._tm, launched[0])
                self.assertIs(daemon._lifecycle, DaemonLifecycle.UNLOCKING)
                self.assertFalse(
                    finished.wait(
                        Constants.DEFAULT_IPC_TIMEOUT + COLD_UNLOCK_MARGIN_SEC
                    )
                )
                release.set()
                self.assertTrue(
                    finished.wait(Constants.MAX_UNLOCK_INITIALIZATION_WAIT_SEC)
                )
                with patch.object(
                    client._ipc,
                    'wait_for_response',
                    wraps=client._ipc.wait_for_response,
                ) as ordinary_wait:
                    self.assertIsNotNone(client.runtime_snapshot())
                self.assertTrue(ordinary_wait.call_args_list)
                self.assertTrue(
                    all(
                        call.kwargs['timeout'] is None
                        for call in ordinary_wait.call_args_list
                    )
                )
                resolve.assert_not_called()
                native_launch.assert_not_called()
        finally:
            release.set()
            worker.join(Constants.MAX_UNLOCK_INITIALIZATION_WAIT_SEC)
            client.disconnect()
            daemon.stop()
        self.assertFalse(worker.is_alive())
        self.assertFalse(failures)
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], InitEvent)
        self.assertEqual(len(launched), 1)
        self.assertGreater(
            completed_at[0] - entered_at[0], Constants.DEFAULT_IPC_TIMEOUT
        )
        self.assertLess(
            completed_at[0] - started_at, Constants.MAX_UNLOCK_INITIALIZATION_WAIT_SEC
        )
        provider.get_unlock_password.assert_called_once_with()

    def test_unlock_wait_clamps_to_declared_budget(self) -> None:
        """Controlled clock verifies the upper bound on post-lock IPC waiting.

        Args:
            None
        Returns:
            None
        """
        client = MetorClient(
            1, unlock_timeout=Constants.MAX_UNLOCK_INITIALIZATION_WAIT_SEC + 60
        )
        ipc = client._ipc = Mock()
        ipc.wait_for_response.side_effect = [DaemonLockedEvent(), None]
        exchange = Mock()
        exchange.handle.return_value = IpcAuthResult(handled=True)
        with (
            patch.object(client, '_create_auth_exchange', return_value=exchange),
            patch('metor.client.session.time.monotonic', side_effect=[100.0, 101.0]),
        ):
            self.assertIsNone(
                client.request(
                    InitCommand(IPC_PROTOCOL_VERSION, IPC_PROTOCOL_MIN_SUPPORTED),
                    InitEvent,
                )
            )
        self.assertEqual(ipc.wait_for_response.call_count, 2)
        self.assertIsNone(ipc.wait_for_response.call_args_list[0].kwargs['timeout'])
        self.assertEqual(
            ipc.wait_for_response.call_args_list[1].kwargs['timeout'],
            Constants.MAX_UNLOCK_INITIALIZATION_WAIT_SEC - 1,
        )


if __name__ == '__main__':
    unittest.main()
