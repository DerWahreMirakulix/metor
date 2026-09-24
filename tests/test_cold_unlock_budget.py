"""A real temporary encrypted daemon may initialize beyond ordinary IPC time."""

import atexit
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

from metor.client import MetorClient
from metor.client.auth import IpcAuthResult
from metor.core.api import DaemonLockedEvent, InitCommand, InitEvent
from metor.core.daemon.managed.engine import Daemon
from metor.core.key import KeyManager
from metor.data import ProfileManager
from metor.utils import Constants
from metor.versioning import IPC_PROTOCOL_VERSION, IPC_PROTOCOL_MIN_SUPPORTED


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
        KeyManager(profile, 'test-password')
        tor = Mock()
        tor.onion = 'a' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        tor.is_running.return_value = True
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            daemon = Daemon(profile, tm=tor, start_locked=True)
        atexit.unregister(daemon.stop)
        self.addCleanup(daemon.stop)
        daemon._ipc.start()
        provider = Mock()
        provider.get_unlock_password.return_value = 'test-password'
        client = MetorClient(daemon._ipc.port, auth_provider=provider)
        self.addCleanup(client.disconnect)
        original_start = daemon._start_subsystems

        def delayed_start() -> bool:
            """Delay only the test startup phase, retaining real subsystem work.

            Args:
                None
            Returns:
                bool: Actual subsystem start result.
            """
            time.sleep(Constants.DEFAULT_IPC_TIMEOUT + 1)
            return original_start()

        with patch.object(daemon, '_start_subsystems', side_effect=delayed_start):
            started = time.monotonic()
            initialized = client.bootstrap()
            elapsed = time.monotonic() - started
        self.assertIsNotNone(initialized)
        self.assertGreater(elapsed, Constants.DEFAULT_IPC_TIMEOUT)
        self.assertLess(elapsed, Constants.MAX_UNLOCK_INITIALIZATION_WAIT_SEC)
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
