"""GUI security orchestration against real authenticated Core IPC and SQLCipher."""

import atexit
import json
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from private_fixtures import PrivateTemporaryDirectory

from metor.client import (
    FrontendBootstrapResult,
    FrontendProfileState,
    OneUseSecretProvider,
)
from metor.client import FrontendLaunchContext, MetorClient, build_session_auth_proof
from metor.client.platform import PlatformBindings
from metor.core.api import (
    ClientAccessRestrictedEvent,
    ClientRestrictedEvent,
    ConnectedEvent,
    InboxNotificationEvent,
    NotificationPrivacy,
    RestrictClientCommand,
    ClientReauthorizedEvent,
    ClientUnlockMethod,
    Delivery,
    GetMessageOutcomeCommand,
    GetContactsListCommand,
    ContactsDataEvent,
    MessageOutcomeEvent,
    SendMessageCommand,
    GetGuiPreferencesCommand,
    GetRuntimeSnapshotCommand,
    GuiPreferenceFailure,
    GuiPreferencesEvent,
    GuiPreferencesRejectedEvent,
    IpcEvent,
    IpcCommand,
    LocalAuthRateLimitedEvent,
    ReauthorizeClientCommand,
    SetGuiPreferencesCommand,
)
from metor.core.daemon.managed.engine import Daemon
from metor.core.daemon.managed.local_auth import create_session_auth_context
from metor.core.key import KeyManager
from metor.data import ContactManager, HistoryManager, MessageManager, SettingKey
from metor.data.profile import ProfileManager
from metor.data.profile.ipc_identity import read_daemon_certificate
from metor.data.sql import SqlManager
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.device import DeviceLifecycle
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update
from metor.utils import Constants


_SECURITY_WORKER_TIMEOUT_SEC: float = (
    Constants.DEFAULT_IPC_TIMEOUT + Constants.FILE_LOCK_TIMEOUT_SEC
)


class GuiUnlockCooldownTests(unittest.TestCase):
    """Check the UI cooldown without running a Core or shortening its retry policy."""

    def test_monotonic_countdown_blocks_all_unlock_paths_until_deadline(self) -> None:
        """Observe rounded seconds and retain the challenge without automatic retries."""
        controller = GuiController(FrontendLaunchContext('cooldown-fixture', Mock()))
        controller.client = Mock()
        controller.submit = Mock(return_value=True)
        controller.state.route = Route('V05')
        security = controller.security
        security.restriction = ClientRestrictedEvent(
            ClientUnlockMethod.PIN, '11' * 32, '22' * 16
        )
        restriction = security.restriction
        with patch('metor.ui.gui.runtime.security.controller.time.monotonic') as clock:
            clock.return_value = 100
            security.install('security:unlock', LocalAuthRateLimitedEvent(3))
            self.assertEqual(security.retry_seconds, 3)
            self.assertFalse(security.unlock('1234'))
            self.assertFalse(security.unlock(password=True))
            clock.return_value = 101.01
            self.assertTrue(security.update_retry())
            self.assertEqual(security.retry_seconds, 2)
            self.assertFalse(security.update_retry())
            controller.state.status = 'New authoritative feedback'
            clock.return_value = 102.99
            self.assertTrue(security.update_retry())
            self.assertEqual(security.retry_seconds, 1)
            self.assertFalse(security.unlock('1234'))
            clock.return_value = 103
            self.assertTrue(security.update_retry())
            self.assertEqual(security.retry_seconds, 0)
            self.assertEqual(controller.state.status, 'New authoritative feedback')
            self.assertIs(security.restriction, restriction)
            self.assertTrue(controller.state.covered)
            controller.submit.assert_not_called()
            self.assertTrue(security.unlock('1234'))
            controller.submit.assert_called_once()
            self.assertTrue(controller.state.covered)


class GuiSecurityIntegrationTests(unittest.TestCase):
    """No Tor connection or native audio is used; IPC, auth and storage are real."""

    def setUp(self) -> None:
        """Creates one encrypted runtime with two authenticated public SDK clients."""
        temporary = PrivateTemporaryDirectory()
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
        self.controller = GuiController(
            FrontendLaunchContext(
                'gui-secured',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'gui-secured', True, False, False
                    )
                ),
            )
        )
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

    def make_client(
        self, on_event: Callable[[IpcEvent], None] | None = None
    ) -> MetorClient:
        """Authenticates using public one-use password proofs."""
        provider = Mock()
        provider.get_session_auth_proof.side_effect = lambda challenge, salt: (
            build_session_auth_proof('test-password', challenge, salt)
        )
        client = MetorClient(
            self.daemon._ipc.port,
            auth_provider=provider,
            on_event=on_event,
            daemon_certificate=read_daemon_certificate(
                self.daemon._pm.paths.get_config_dir()
            ),
            timeout=Constants.DEFAULT_IPC_TIMEOUT,
        )
        self.addCleanup(client.disconnect)
        self.assertIsNotNone(client.bootstrap())
        self.assertIn('protected_gui_preferences', client.init_event.capabilities)
        return client

    def settle(
        self,
        phase: str = 'security-operation',
        *,
        completed: Callable[[], bool] | None = None,
    ) -> float:
        """Waits for a bounded foreground phase or its exact asynchronous outcome.

        Args:
            phase (str): Non-secret operation label used only on assertion failure.
            completed: Optional exact action predicate, including background reconciliation.

        Returns:
            float: Total worker and mailbox settlement duration in seconds.
        """
        started_at = time.monotonic()
        deadline = started_at + _SECURITY_WORKER_TIMEOUT_SEC
        while time.monotonic() < deadline:
            worker = self.controller._worker
            if worker is not None:
                worker.join(max(0.0, deadline - time.monotonic()))
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
            if completed() if completed is not None else not self.controller.state.busy:
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

    def test_locked_privacy_events_preserve_the_actual_sdk_stream(self) -> None:
        """A real locked TLS client stays connected across ordinary transport broadcasts."""
        for privacy in NotificationPrivacy:
            with self.subTest(privacy=privacy):
                observed: list[IpcEvent] = []
                received = threading.Event()

                def record(event: IpcEvent) -> None:
                    if isinstance(event, (ConnectedEvent, InboxNotificationEvent)):
                        observed.append(event)
                    if isinstance(event, InboxNotificationEvent):
                        received.set()

                reader = self.make_client(record)
                self.assertIsNotNone(
                    reader.request(
                        RestrictClientCommand(notification_privacy=privacy),
                        ClientRestrictedEvent,
                    )
                )
                self.daemon._broadcast_ipc_event(
                    ConnectedEvent('synthetic alias', 'a' * 56)
                )
                self.daemon._broadcast_ipc_event(
                    InboxNotificationEvent('synthetic alias', 'a' * 56)
                )
                self.assertIsInstance(
                    reader.request(GetRuntimeSnapshotCommand(), IpcEvent),
                    ClientAccessRestrictedEvent,
                )
                if privacy is NotificationPrivacy.OFF:
                    self.assertFalse(observed)
                else:
                    self.assertTrue(received.wait(_SECURITY_WORKER_TIMEOUT_SEC))
                    if privacy is NotificationPrivacy.ANONYMIZE:
                        self.assertEqual(len(observed), 1)
                        self.assertNotIn('synthetic alias', observed[0].to_json())
                        self.assertNotIn('a' * 56, observed[0].to_json())
                    else:
                        self.assertEqual(
                            [type(event) for event in observed],
                            [ConnectedEvent, InboxNotificationEvent],
                        )
                self.assertTrue(reader.is_connected)
                reader.disconnect()

    def test_large_contact_snapshot_is_browsable_across_identity_changes(self) -> None:
        """Real SQL, IPC and the GUI mailbox admit a book larger than one IPC frame."""
        import base64
        import hashlib

        manager = self.daemon._cm
        expected = {}
        # Populate current-format peer rows in one fixture transaction.
        with manager._peers.alias_mutation() as peers:
            for index in range(1400):
                public = hashlib.sha256(str(index).encode()).digest()
                suffix = b'\x03'
                checksum = hashlib.sha3_256(
                    b'.onion checksum' + public + suffix
                ).digest()[:2]
                onion = (
                    base64.b32encode(public + checksum + suffix).decode('ascii').lower()
                )
                alias = f'{index:04d}-' + ('a' * 3900)
                peers.insert(onion, alias, index % 2 == 0)
                expected[onion] = alias
        first = self.client.runtime_snapshot(first_page_only=True)
        assert first is not None and first.next_offset is not None
        self.assertLess(len(first.to_json().encode()), Constants.SNAPSHOT_PAGE_BYTES)
        changed = next(iter(expected))
        manager.rename_contact(expected[changed], 'Renamed', expected_onion=changed)
        # The frozen pages never mix the old and the new name.
        self.controller.state.snapshot = first
        self.controller._refresh_needed = False
        self.controller._messages_needed = False
        deadline = time.monotonic() + 60
        while self.controller.state.snapshot.next_offset is not None:
            self.assertLess(time.monotonic(), deadline)
            self.controller._poll_snapshot()
            worker = self.controller._worker
            assert worker is not None
            worker.join(_SECURITY_WORKER_TIMEOUT_SEC)
            self.controller.poll()
        contacts = self.controller.state.snapshot.contacts
        self.assertEqual(len(contacts), len(expected))
        self.assertEqual({row.onion: row.alias for row in contacts}, expected)
        fresh = self.client.runtime_snapshot(first_page_only=True)
        assert fresh is not None
        observed = list(fresh.contacts)
        while fresh.next_offset is not None:
            fresh = self.client.next_runtime_snapshot_page(fresh)
            assert fresh is not None
            self.assertLess(
                len(fresh.to_json().encode()), Constants.SNAPSHOT_PAGE_BYTES
            )
            observed.extend(fresh.contacts)
        exact = self.client.request(
            GetContactsListCommand(onions=[changed]), ContactsDataEvent
        )
        assert exact is not None
        self.assertEqual(
            [(entry.onion, entry.alias) for entry in exact.saved],
            [(changed, 'Renamed')],
        )
        self.assertEqual(exact.checked_onions, [changed])
        expected[changed] = 'Renamed'
        self.assertEqual({row.onion: row.alias for row in observed}, expected)
        complete = self.client.runtime_snapshot()
        assert complete is not None
        self.assertEqual({row.onion: row.alias for row in complete.contacts}, expected)

    def test_device_menu_screen_lock_restricts_real_core_session(self) -> None:
        """A reversible hardware overlay cannot stand in for Core authorization."""
        controller = self.controller
        controller.device = DeviceLifecycle(
            controller, PlatformBindings('fixture', Mock(), shutdown=Mock())
        )
        self.assertTrue(controller.device.open_power_menu())
        controller.screen_lock()
        controller.poll()
        self.settle()
        self.assertIsNotNone(controller.security.restriction)
        denied = self.client.request(GetRuntimeSnapshotCommand(), IpcEvent)
        self.assertIsInstance(denied, ClientAccessRestrictedEvent)
        self.assertIsNotNone(self.other.runtime_snapshot())
        controller.device.cancel()
        self.assertTrue(controller.state.covered)
        self.assertTrue(controller.security.unlock('test-password'))
        self.settle()
        self.assertFalse(controller.state.covered)
        self.assertEqual(controller.state.route, Route('V06'))

    def test_native_source_failure_fences_inflight_unlock_and_keeps_other_client(
        self,
    ) -> None:
        """A real accepted proof cannot restore this GUI after its monitor fails."""
        self._assert_native_failure_fences_completion(ReauthorizeClientCommand)

    def test_native_source_failure_fences_inflight_restore_and_keeps_other_client(
        self,
    ) -> None:
        """A real fresh snapshot and preferences cannot remove the failure cover."""
        self._assert_native_failure_fences_completion(GetGuiPreferencesCommand)

    def test_os_lock_disconnects_candidate_while_hydration_is_still_blocked(
        self,
    ) -> None:
        """An already-authenticated connection cannot survive behind a slow startup read."""
        host = Mock()
        host.profile_state.return_value = FrontendProfileState(
            'gui-secured', True, False, True
        )
        host.bootstrap.return_value = FrontendBootstrapResult(
            'gui-secured',
            True,
            self.daemon._ipc.port,
            False,
            OneUseSecretProvider('test-password'),
            Mock(),
            True,
            daemon_certificate=read_daemon_certificate(
                self.daemon._pm.paths.get_config_dir()
            ),
        )
        gui = GuiController(FrontendLaunchContext('gui-secured', host))
        self.addCleanup(gui.close)
        reached, disconnected, release = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        candidates: list[MetorClient] = []
        original = MetorClient.disconnect

        def hold(client: MetorClient, _initialized: object) -> None:
            candidates.append(client)
            reached.set()
            release.wait(_SECURITY_WORKER_TIMEOUT_SEC)
            raise RuntimeError('Hydration retired')

        def disconnect(client: MetorClient) -> None:
            original(client)
            if candidates and client is candidates[0]:
                disconnected.set()

        with (
            patch.object(MetorClient, 'disconnect', disconnect),
            patch.object(gui.activation, 'hydrate', side_effect=hold),
        ):
            self.assertTrue(gui.open_profile())
            worker = gui._worker
            assert worker is not None
            try:
                self.assertTrue(reached.wait(_SECURITY_WORKER_TIMEOUT_SEC))
                self.assertTrue(candidates[0].is_connected)
                gui.screen_lock()
                self.assertTrue(disconnected.wait(_SECURITY_WORKER_TIMEOUT_SEC))
                self.assertFalse(candidates[0].is_connected)
                self.assertTrue(gui.state.covered)
                self.assertTrue(worker.is_alive())
            finally:
                release.set()
                worker.join(_SECURITY_WORKER_TIMEOUT_SEC)
        gui.poll()
        self.assertIsNone(gui.client)
        self.assertTrue(gui.state.covered)
        self.assertIsNotNone(self.other.runtime_snapshot())

    def test_os_lock_abandons_startup_and_switch_candidates(self) -> None:
        """An authenticated candidate cannot publish a queued startup or switch after lock."""
        for switching in (False, True):
            with self.subTest(switching=switching):
                gui = GuiController(self.controller.context)
                self.addCleanup(gui.close)
                candidate = self.make_client()
                original = candidate.disconnect
                released = threading.Event()

                def release() -> None:
                    original()
                    released.set()

                with patch.object(candidate, 'disconnect', side_effect=release):
                    if switching:
                        gui.client = self.make_client()
                        gui.state.covered = False
                        gui.state.route = Route('V06')
                        with patch(
                            'metor.ui.gui.runtime.profiles.transition.ProfileRuntimeCoordinator'
                        ) as coordinator:
                            coordinator.return_value.client = candidate
                            self.assertTrue(gui.lifecycle.start('selected'))
                            worker = gui._worker
                            assert worker is not None
                            worker.join(_SECURITY_WORKER_TIMEOUT_SEC)
                        self.assertIsNotNone(gui.lifecycle._candidate)
                    else:
                        with (
                            patch.object(
                                gui.activation, 'connect', return_value=candidate
                            ),
                            patch.object(
                                candidate,
                                'bootstrap',
                                return_value=candidate.init_event,
                            ),
                        ):
                            self.assertTrue(gui.open_profile())
                            worker = gui._worker
                            assert worker is not None
                            worker.join(_SECURITY_WORKER_TIMEOUT_SEC)
                        self.assertIs(gui.client, candidate)
                    self.assertFalse(worker.is_alive())
                    gui.screen_lock()
                    gui.poll()
                    self.assertTrue(released.wait(_SECURITY_WORKER_TIMEOUT_SEC))
                    self.assertIsNone(gui.client)
                    self.assertTrue(gui.state.covered)
                    self.assertIsNone(gui.state.snapshot)
                    self.assertFalse(candidate.is_connected)
                    self.assertIsNotNone(self.other.runtime_snapshot())

    def test_os_lock_fences_accepted_unlock_and_restore(self) -> None:
        """A second screen lock supersedes either stage of a valid proof."""
        for command in (ReauthorizeClientCommand, GetGuiPreferencesCommand):
            with self.subTest(command=command):
                self._assert_native_failure_fences_completion(
                    command, ordinary_lock=True
                )

    def _assert_native_failure_fences_completion(
        self, gate_command: type[IpcCommand], *, ordinary_lock: bool = False
    ) -> None:
        """Holds one successful Core response until the GUI loses native monitoring.

        Args:
            gate_command: Unlock or restore command whose real response is delayed.

        Returns:
            None
        """
        controller = self.controller
        identity = controller.state.snapshot.profile_instance_id
        self.assertTrue(controller.security.lock())
        controller.poll()
        self.settle()
        self.assertIsNotNone(controller.security.restriction)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        request = self.client.request
        replies: list[IpcEvent | None] = []

        def hold_completed_response(
            command: IpcCommand, expected: type[IpcEvent]
        ) -> IpcEvent | None:
            """Runs the actual authenticated exchange before delaying GUI delivery."""
            result = request(command, expected)
            if isinstance(command, gate_command):
                replies.append(result)
                entered.set()
                if not release.wait(_SECURITY_WORKER_TIMEOUT_SEC):
                    raise TimeoutError('Native failure test gate was not released')
            return result

        with patch.object(self.client, 'request', side_effect=hold_completed_response):
            self.assertTrue(controller.security.unlock('test-password'))
            worker = controller._worker
            self.assertIsNotNone(worker)
            assert worker is not None
            if gate_command is GetGuiPreferencesCommand:
                worker.join(_SECURITY_WORKER_TIMEOUT_SEC)
                self.assertFalse(worker.is_alive())
                controller.poll()
                worker = controller._worker
                self.assertIsNotNone(worker)
                assert worker is not None
            try:
                self.assertTrue(entered.wait(_SECURITY_WORKER_TIMEOUT_SEC))
                self.assertEqual(len(replies), 1)
                self.assertIsInstance(
                    replies[0],
                    ClientReauthorizedEvent
                    if gate_command is ReauthorizeClientCommand
                    else GuiPreferencesEvent,
                )
                old_generation = controller.state.generation
                if ordinary_lock:
                    controller.screen_lock()
                else:
                    controller.fail_native_lifecycle()
                    self.assertTrue(controller.native_lifecycle_failed)
                    self.assertGreater(controller.state.generation, old_generation)
                self.assertTrue(controller.state.covered)
                if not ordinary_lock:
                    self.assertIsNone(controller.client)
                self.assertEqual(
                    self.other.runtime_snapshot().profile_instance_id, identity
                )
            finally:
                release.set()
                worker.join(_SECURITY_WORKER_TIMEOUT_SEC)
                self.assertFalse(worker.is_alive())
            controller.poll()

        if ordinary_lock:
            self.settle()
            self.assertTrue(controller.state.covered)
            self.assertIsNone(controller.state.snapshot)
            self.assertIsNone(controller.state.preferences)
            self.assertIsInstance(
                self.client.request(GetRuntimeSnapshotCommand(), IpcEvent),
                ClientAccessRestrictedEvent,
            )
            self.assertTrue(controller.security.unlock('test-password'))
            self.settle()
            self.assertFalse(controller.state.covered)
            return
        self.assertTrue(controller.native_lifecycle_failed)
        self.assertTrue(controller.state.covered)
        self.assertIsNone(controller.state.snapshot)
        self.assertIsNone(controller.state.preferences)
        self.assertIsNone(controller.client)
        self.assertFalse(controller.security.unlock('test-password'))
        self.assertEqual(self.other.runtime_snapshot().profile_instance_id, identity)

    def test_pin_forgot_password_and_none_use_core_challenges(self) -> None:
        """PIN cannot weaken policy; explicit password recovery restores full strength."""
        controller = self.controller
        self.assertTrue(controller.security.configure(ClientUnlockMethod.PIN, '1357'))
        worker_elapsed = self.settle('configure-pin')
        print(
            'GUI_SECURITY_TIMING '
            + json.dumps(
                {
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
        queries: list[str] = []
        receipts: list[MessageOutcomeEvent] = []
        receipt_started = threading.Event()
        receipt_release = threading.Event()
        self.addCleanup(receipt_release.set)

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
            if isinstance(command, GetMessageOutcomeCommand):
                queries.append(command.msg_id)
                receipt_started.set()
                if not receipt_release.wait(_SECURITY_WORKER_TIMEOUT_SEC):
                    raise TimeoutError('Text receipt test gate was not released')
            result = request(command, expected)
            if isinstance(command, SendMessageCommand):
                sent.append(command.msg_id)
                return None
            if isinstance(result, MessageOutcomeEvent):
                receipts.append(result)
            return result

        with patch.object(self.client, 'request', side_effect=lose_acceptance):
            self.controller.send_text(peer, Delivery.LIVE)
            self.settle()
            self.assertTrue(receipt_started.wait(_SECURITY_WORKER_TIMEOUT_SEC))
            self.assertEqual(len(sent), 1)
            action = 'A11:' + sent[0]
            self.assertFalse(self.controller.state.busy)
            self.assertEqual(
                self.controller.text.operations[action][2], 'one logical send'
            )
            self.assertNotIn((peer, Delivery.LIVE), self.controller.state.drafts)
            self.assertIn(action, self.controller.text.operations)
            self.assertIn(action, self.controller._unknown_actions)
            self.assertEqual(
                self.controller.text.pending_status(peer, Delivery.LIVE),
                'Checking send result…',
            )
            self.controller.send_text(peer, Delivery.LIVE)
            self.assertEqual(len(sent), 1)
            receipt_release.set()
            self.settle(
                'text-receipt-reconciliation',
                completed=lambda: (
                    not self.controller.text.pending(peer, Delivery.LIVE)
                    and action not in self.controller._unknown_actions
                    and (peer, Delivery.LIVE) not in self.controller.state.drafts
                ),
            )
        self.assertEqual(len(sent), 1)
        self.assertEqual(queries, sent)
        self.assertEqual([receipt.msg_id for receipt in receipts], sent)
        self.assertEqual([receipt.onion for receipt in receipts], [peer])
        self.assertTrue(all(receipt.status is not None for receipt in receipts))
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
