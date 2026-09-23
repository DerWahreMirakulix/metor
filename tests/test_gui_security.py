"""GUI security orchestration against real authenticated Core IPC and SQLCipher."""

import atexit
import json
import socket
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from metor.client import FrontendLaunchContext, MetorClient, build_session_auth_proof
from metor.core.api import (
    ClientUnlockMethod,
    Delivery,
    SendMessageCommand,
    GetGuiPreferencesCommand,
    GuiPreferenceFailure,
    GuiPreferencesEvent,
    GuiPreferencesRejectedEvent,
    IpcEvent,
    IpcCommand,
    SetGuiPreferencesCommand,
)
from metor.core.daemon.managed.engine import Daemon
from metor.core.daemon.managed.local_auth import create_session_auth_context
from metor.core.daemon.managed.quick_unlock import QuickUnlockStore
from metor.core.key import KeyManager
from metor.data import ContactManager, HistoryManager, MessageManager, SettingKey
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update
from metor.utils import Constants


_SECURITY_WORKER_TIMEOUT_SEC: float = (
    Constants.QUICK_UNLOCK_HELPER_TIMEOUT_SEC + Constants.FILE_LOCK_TIMEOUT_SEC
)


class GuiSecurityIntegrationTests(unittest.TestCase):
    """No Tor connection or native audio is used; IPC, auth and storage are real."""

    def setUp(self) -> None:
        """Creates one encrypted runtime with two authenticated public SDK clients."""
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = patch.object(Constants, 'DATA', Path(temporary.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        pm = ProfileManager('gui-secured')
        pm.initialize()
        km = KeyManager(pm, 'test-password')
        key = km.get_database_key()
        self.addCleanup(SqlManager.close_connection, pm.paths.get_db_file())
        tor = Mock()
        tor.onion = 'a' * 56
        tor.is_running.return_value = True
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            self.daemon = Daemon(
                pm,
                km,
                tor,
                ContactManager(pm, key),
                HistoryManager(pm, key),
                MessageManager(pm, key),
                session_auth=create_session_auth_context('test-password'),
                require_session_auth=True,
            )
        atexit.unregister(self.daemon.stop)
        self.addCleanup(self.daemon.stop)
        self.daemon._ipc.start()
        self.client = self.make_client()
        self.other = self.make_client()
        self.controller = GuiController(FrontendLaunchContext('gui-secured', Mock()))
        self.controller.client = self.client
        self.controller.state.capabilities = frozenset(
            self.client.init_event.capabilities
        )
        self.controller.state.snapshot = self.client.runtime_snapshot()
        self.controller.state.preferences = self.client.request(
            GetGuiPreferencesCommand(), GuiPreferencesEvent
        )
        self.controller.state.covered = False
        self.controller.state.route = Route('V06')
        self.addCleanup(self.controller.close)

    def make_client(self) -> MetorClient:
        """Authenticates using public one-use password proofs."""
        provider = Mock()
        provider.get_session_auth_proof.side_effect = lambda challenge, salt: (
            build_session_auth_proof('test-password', challenge, salt)
        )
        client = MetorClient(self.daemon._ipc.port, auth_provider=provider, timeout=5)
        self.addCleanup(client.disconnect)
        self.assertIsNotNone(client.bootstrap())
        self.assertIn('protected_gui_preferences', client.init_event.capabilities)
        return client

    def settle(self, phase: str = 'security-operation') -> float:
        """Drains serial SDK work and reports one bounded phase duration.

        Args:
            phase (str): Non-secret operation label used only on assertion failure.

        Returns:
            float: Total worker and mailbox settlement duration in seconds.
        """
        started_at = time.monotonic()
        for _ in range(4):
            worker = self.controller._worker
            if worker is not None:
                worker.join(_SECURITY_WORKER_TIMEOUT_SEC)
                self.assertFalse(
                    worker.is_alive(),
                    {
                        'phase': phase,
                        'elapsed_seconds': round(time.monotonic() - started_at, 3),
                        'worker_name': worker.name,
                        'worker_timeout_seconds': _SECURITY_WORKER_TIMEOUT_SEC,
                    },
                )
            self.controller.poll()
            if not self.controller.state.busy:
                return time.monotonic() - started_at
        self.fail('Security work did not settle')

    def test_password_lock_covers_immediately_and_does_not_lock_other_clients(
        self,
    ) -> None:
        """One session restricts; another keeps normal authenticated snapshot access."""
        state = self.controller.state
        identity = state.snapshot.profile_instance_id
        self.assertTrue(self.controller.security.lock())
        self.assertTrue(state.covered)
        self.assertIsNone(state.snapshot)
        self.assertIsNone(state.preferences)
        self.controller.poll()
        self.settle()
        self.assertIsNotNone(self.controller.security.restriction)
        self.assertEqual(self.other.runtime_snapshot().profile_instance_id, identity)
        self.assertTrue(self.controller.security.unlock('test-password'))
        self.settle()
        self.assertFalse(state.covered)
        self.assertEqual(state.snapshot.profile_instance_id, identity)
        self.assertEqual(state.route.view, 'V06')

    def test_pin_forgot_password_and_none_use_core_challenges(self) -> None:
        """PIN cannot weaken policy; explicit password recovery restores full strength."""
        controller = self.controller
        acl_timings: list[tuple[str, float]] = []
        run_acl_helper = QuickUnlockStore._run_acl_helper

        def timed_acl_helper(
            path: Path, script: str, phase: str
        ) -> subprocess.CompletedProcess[str]:
            """Delegates to the native ACL helper while recording its phase duration.

            Args:
                path (Path): Exact temporary credential path.
                script (str): Constant production ACL script.
                phase (str): Non-secret production ACL phase.

            Returns:
                subprocess.CompletedProcess[str]: Unchanged production helper result.
            """
            started_at = time.monotonic()
            try:
                return run_acl_helper(path, script, phase)
            finally:
                acl_timings.append((phase, time.monotonic() - started_at))

        with patch.object(
            QuickUnlockStore,
            '_run_acl_helper',
            side_effect=timed_acl_helper,
        ):
            self.assertTrue(
                controller.security.configure(ClientUnlockMethod.PIN, '1357')
            )
            worker_elapsed = self.settle('configure-pin')
        print(
            'GUI_SECURITY_TIMING '
            + json.dumps(
                {
                    'acl_phases': [
                        {'phase': phase, 'seconds': round(elapsed, 3)}
                        for phase, elapsed in acl_timings
                    ],
                    'worker_seconds': round(worker_elapsed, 3),
                },
                sort_keys=True,
            )
        )
        self.assertEqual(
            controller.state.preferences.preferences.unlock_method,
            ClientUnlockMethod.PIN,
        )
        self.assertTrue(controller.security.lock())
        controller.poll()
        self.settle()
        self.assertEqual(
            controller.security.restriction.unlock_method, ClientUnlockMethod.PIN
        )
        self.assertTrue(controller.security.unlock('1357'))
        self.settle()
        self.assertFalse(controller.state.covered)
        current = controller.state.preferences
        rejected = self.client.request(
            SetGuiPreferencesCommand(
                current.preferences_revision,
                replace(current.preferences, unlock_method=ClientUnlockMethod.NONE),
            ),
            IpcEvent,
        )
        self.assertIsInstance(rejected, GuiPreferencesRejectedEvent)
        self.assertEqual(rejected.reason, GuiPreferenceFailure.FULL_AUTH_REQUIRED)
        controller.security.lock()
        controller.poll()
        self.settle()
        self.assertTrue(controller.security.unlock(password=True))
        self.settle()
        self.assertTrue(controller.state.covered)
        self.assertEqual(
            controller.security.restriction.unlock_method,
            ClientUnlockMethod.PROFILE_PASSWORD,
        )
        self.assertTrue(controller.security.unlock('test-password'))
        self.settle()
        self.assertTrue(controller.security.configure(ClientUnlockMethod.NONE))
        self.settle()
        controller.security.lock()
        controller.poll()
        self.settle()
        self.assertTrue(controller.state.covered)
        self.assertTrue(controller.security.unlock())
        self.settle()
        self.assertFalse(controller.state.covered)

    def test_live_text_local_acceptance_precedes_peer_ack_and_quota_is_definite(
        self,
    ) -> None:
        """GUI clears an admitted draft without a remote ACK; quota denial preserves it."""
        peer = 'b' * 56
        self.daemon._cm.ensure_alias_for_onion(peer)
        local, remote = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(remote.close)
        self.daemon._transport_state.add_active_connection(peer, local)
        self.daemon._pm.config.set(SettingKey.MAX_PENDING_LIVE_MSGS, 1)
        self.controller.state.set_draft(peer, Delivery.LIVE, 'accepted locally')
        self.controller.send_text(peer, Delivery.LIVE)
        self.settle()
        self.assertNotIn((peer, Delivery.LIVE), self.controller.state.drafts)
        inventory = self.client.list_retained_messages(
            target=peer, delivery=Delivery.LIVE
        )
        self.assertEqual(len(inventory.messages), 1)
        self.controller.state.set_draft(peer, Delivery.LIVE, 'keep this draft')
        self.controller.send_text(peer, Delivery.LIVE)
        self.settle()
        self.assertEqual(
            self.controller.state.drafts[(peer, Delivery.LIVE)], 'keep this draft'
        )
        self.assertEqual(self.controller.text.operations, {})
        self.assertEqual(self.controller._unknown_actions, set())

    def test_lost_local_text_result_reconciles_receipt_without_resending(self) -> None:
        """A lost success response clears only after a positive exact-ID receipt query."""
        peer = 'b' * 56
        self.daemon._cm.ensure_alias_for_onion(peer)
        local, remote = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(remote.close)
        self.daemon._transport_state.add_active_connection(peer, local)
        self.controller.state.set_draft(peer, Delivery.LIVE, 'one logical send')
        request = self.client.request
        sent: list[str] = []

        def lose_acceptance(
            command: IpcCommand, expected: type[IpcEvent]
        ) -> IpcEvent | None:
            """Discards only the local test's send response after Core admission.

            Args:
                command: Public SDK command.
                expected: Expected public response type.
            Returns:
                IpcEvent | None: Original result or injected lost acceptance.
            """
            result = request(command, expected)
            if isinstance(command, SendMessageCommand):
                sent.append(command.msg_id)
                return None
            return result

        with patch.object(self.client, 'request', side_effect=lose_acceptance):
            self.controller.send_text(peer, Delivery.LIVE)
            self.settle()
        self.assertEqual(len(sent), 1)
        self.assertNotIn((peer, Delivery.LIVE), self.controller.state.drafts)
        self.assertEqual(self.controller.text.operations, {})
        self.assertEqual(self.controller._unknown_actions, set())
        inventory = self.client.list_retained_messages(
            target=peer, delivery=Delivery.LIVE
        )
        self.assertEqual([item.msg_id for item in inventory.messages], sent)

    def test_unknown_restriction_disconnects_and_stale_success_cannot_uncover(
        self,
    ) -> None:
        """Only a current confirmed same-profile refresh can remove the private cover."""
        controller = self.controller
        old_generation = controller.state.generation
        controller.security.lock()
        self.assertTrue(controller.security.install('security:restrict', None))
        self.assertTrue(controller.state.covered)
        self.assertIsNone(controller.client)
        controller.mailbox.put(
            Update(old_generation, 'security:restore', GuiPreferencesEvent('old', 99))
        )
        controller.poll()
        self.assertTrue(controller.state.covered)
        self.assertIsNone(controller.state.preferences)


if __name__ == '__main__':
    unittest.main()
