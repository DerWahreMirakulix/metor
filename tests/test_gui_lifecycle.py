"""Public coordinator phase truth and GUI-only detach against an isolated encrypted Core."""

import atexit
import socket
import unittest
from unittest.mock import Mock, patch

import test_gui_producers as support
from metor.client import (
    FrontendLaunchContext,
    MetorClient,
    build_session_auth_proof,
    FrontendBootstrapResult,
    OneUseSecretProvider,
    ProfileRuntimeCoordinator,
    ProfileSwitchError,
    ProfileSwitchPhase,
)
from metor.core.api import (
    Delivery,
    FinalizeVoiceCommand,
    MessageDirectionCode,
    RetainedMessagesEvent,
    RuntimeSnapshotEvent,
    VoiceFinalizedEvent,
)
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.voice.press import PressPhase
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update
from metor.core.daemon.managed.engine import Daemon
from metor.core.daemon.managed.local_auth import create_session_auth_context
from metor.core.key import KeyManager
from metor.data import ContactManager, HistoryManager, MessageManager, ProfileManager
from metor.data.blob import EncryptedBlobStore
from metor.data.sql import SqlManager


class CoordinatorPhaseTests(unittest.TestCase):
    """Checks SDK transaction failures without assuming that disconnect and hard lock coincide."""

    def test_disconnect_failure_reports_confirmed_source_preparation(self) -> None:
        """A prepared source is already locked even when socket release raises.

        Args:
            None
        Returns:
            None
        """
        source = Mock()
        source.runtime_snapshot.return_value = RuntimeSnapshotEvent('a', '')
        source.prepare_profile_exit.return_value = True
        source.disconnect.side_effect = OSError('release failed')
        factory = Mock()
        phases = []
        with self.assertRaises(ProfileSwitchError) as caught:
            ProfileRuntimeCoordinator(source, factory).switch(
                'b', on_phase=phases.append
            )
        self.assertIs(caught.exception.phase, ProfileSwitchPhase.SOURCE_RELEASE)
        self.assertTrue(caught.exception.source_prepared)
        self.assertFalse(caught.exception.source_released)
        factory.assert_not_called()
        self.assertEqual(
            phases,
            [
                ProfileSwitchPhase.SOURCE_SNAPSHOT,
                ProfileSwitchPhase.SOURCE_PREPARATION,
                ProfileSwitchPhase.SOURCE_RELEASE,
            ],
        )

    def test_unknown_preparation_never_opens_target_or_repeats_exit(self) -> None:
        """Unconfirmed preparation cannot become rollback or a second preparation request.

        Args:
            None
        Returns:
            None
        """
        source, factory = Mock(), Mock()
        source.runtime_snapshot.return_value = RuntimeSnapshotEvent('a', '')
        source.prepare_profile_exit.return_value = False
        with self.assertRaises(ProfileSwitchError) as caught:
            ProfileRuntimeCoordinator(source, factory).switch('b')
        self.assertIs(caught.exception.phase, ProfileSwitchPhase.SOURCE_PREPARATION)
        self.assertFalse(caught.exception.source_prepared)
        source.prepare_profile_exit.assert_called_once_with()
        source.disconnect.assert_not_called()
        factory.assert_not_called()


class NativeLifecycleTests(unittest.TestCase):
    """Checks toolkit-independent focus and suspend orchestration."""

    def setUp(self) -> None:
        """Creates an inert GUI controller with observable lifecycle collaborators.

        Args:
            None
        Returns:
            None
        """
        self.gui = GuiController(FrontendLaunchContext('lifecycle', Mock()))
        self.addCleanup(self.gui.close)
        self.gui.inputs = Mock()
        self.gui.voice = Mock()
        self.gui.playback = Mock()
        self.gui.playback.auto.focused = True
        self.gui.security = Mock()

    def test_native_departure_revokes_input_and_both_audio_directions(self) -> None:
        """Focus loss cannot retain a held PTT owner or active local media.

        Args:
            None
        Returns:
            None
        """
        self.gui.native_departure()
        self.gui.inputs.focus_lost.assert_called_once_with()
        self.gui.voice.depart.assert_called_once_with()
        self.gui.playback.stop.assert_called_once_with()
        self.gui.security.lock.assert_not_called()

    def test_suspend_adds_privacy_cover_without_synthesizing_resume_input(self) -> None:
        """Suspend disables auto-play and locks after the lost-input barrier.

        Args:
            None
        Returns:
            None
        """
        self.gui.suspend()
        self.assertFalse(self.gui.playback.auto.focused)
        self.gui.inputs.focus_lost.assert_called_once_with()
        self.gui.voice.depart.assert_called_once_with()
        self.gui.playback.stop.assert_called_once_with()
        self.gui.security.lock.assert_called_once_with()

    def test_resume_retains_revoked_input_and_never_unlocks_or_starts_media(
        self,
    ) -> None:
        """Resume checks transport while leaving authorization user-driven."""
        self.gui.client = Mock(is_connected=True)

        self.gui.resume()

        self.assertFalse(self.gui.playback.auto.focused)
        self.gui.inputs.focus_lost.assert_called_once_with()
        self.gui.voice.depart.assert_called_once_with()
        self.gui.playback.stop.assert_called_once_with()
        self.gui.security.unlock.assert_not_called()

    def test_resume_disconnect_discards_old_generation_behind_cover(self) -> None:
        """A dead transport cannot remain an apparently authorized resume target."""
        self.gui.client = Mock(is_connected=False)
        with patch.object(self.gui, 'close') as close:
            self.gui.resume()

        close.assert_called_once_with()
        self.assertEqual(
            self.gui.state.status, 'Connection lost. Open profile to reconnect.'
        )


class GuiLifecycleCoreTests(unittest.TestCase):
    """Uses real SDK/IPC, encrypted storage and inert local peer sockets; no hardware or Tor."""

    def setUp(self) -> None:
        """Starts one protected temporary Core and two independent authenticated clients.

        Args:
            None
        Returns:
            None
        """
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.host = Mock()
        self.gui = GuiController(FrontendLaunchContext('voice-owned', self.host))
        self.addCleanup(self.gui.close)
        self.gui.client = self.h.client
        self.gui.state.snapshot = self.h.client.runtime_snapshot()
        self.gui.state.covered = False
        self.gui.state.route = Route('V20')
        self.gui.state.capabilities = frozenset(self.h.client.init_event.capabilities)
        self.gui.voice_owner.token = self.h.owner

    def settle(self) -> None:
        """Runs the actual GUI mailbox until its admitted lifecycle worker completes.

        Args:
            None
        Returns:
            None
        """
        for _ in range(20):
            if self.gui._worker is not None:
                self.gui._worker.join(2)
            self.gui.poll()
            if not self.gui.lifecycle.active:
                return
        self.fail('Lifecycle worker did not complete')

    def test_desktop_exit_releases_only_own_draft_and_preserves_other_live_client(
        self,
    ) -> None:
        """GUI-only exit never invokes global preparation and leaves another client's socket active.

        Args:
            None
        Returns:
            None
        """
        local, peer = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(peer.close)
        state = self.h.daemon._transport_state
        state.add_active_connection(self.h.onion, local)
        self.h.capture('discard-on-close')
        self.h.client.request(
            FinalizeVoiceCommand('discard-on-close', 20, self.h.owner),
            VoiceFinalizedEvent,
        )
        with patch.object(
            self.h.client,
            'prepare_profile_exit',
            wraps=self.h.client.prepare_profile_exit,
        ) as prepare:
            self.assertTrue(self.gui.lifecycle.start())
            self.assertTrue(self.gui.state.covered)
            self.assertFalse(self.gui.lifecycle.start())
            self.settle()
            prepare.assert_not_called()
        self.assertTrue(self.gui.lifecycle.exit_ready)
        self.assertIsNone(self.gui.client)
        self.assertIs(state.get_connection(self.h.onion), local)
        snapshot = self.h.other.runtime_snapshot()
        self.assertIsNotNone(snapshot)
        retained = self.h.other.list_retained_messages(
            target=self.h.onion,
            direction=MessageDirectionCode.OUT,
            msg_id='discard-on-close',
        )
        self.assertIsInstance(retained, RetainedMessagesEvent)
        self.assertEqual(retained.messages, [])

    def test_failed_target_after_actual_preparation_stays_covered_without_rollback(
        self,
    ) -> None:
        """A confirmed old-profile lock followed by host failure offers fresh entry, not auto-unlock.

        Args:
            None
        Returns:
            None
        """
        self.host.select_profile.side_effect = OSError('unavailable target')
        self.gui.state.set_draft(
            self.h.onion, Delivery.LIVE, 'discard at confirmed exit'
        )
        with patch.object(
            self.h.client,
            'prepare_profile_exit',
            wraps=self.h.client.prepare_profile_exit,
        ) as prepare:
            self.assertTrue(self.gui.lifecycle.start('target'))
            self.settle()
            prepare.assert_called_once_with()
        self.assertTrue(self.gui.lifecycle.failed)
        self.assertTrue(self.gui.state.covered)
        self.assertFalse(self.gui.lifecycle.return_available)
        self.assertIn('previous profile is locked', self.gui.state.status)
        self.assertIsNone(self.gui.state.snapshot)
        self.assertEqual(self.gui.state.drafts, {})
        self.host.bootstrap.assert_not_called()
        self.assertFalse(self.h.client.is_connected)

    def test_successful_switch_hydrates_independent_target_and_fences_old_callbacks(
        self,
    ) -> None:
        """Two actual encrypted runtimes prove candidate auth, hydration and callback ownership.

        Args:
            None
        Returns:
            None
        """
        profile = ProfileManager('target')
        profile.initialize()
        key_manager = KeyManager(profile, 'target-password')
        key = key_manager.get_database_key()
        self.addCleanup(SqlManager.close_connection, profile.paths.get_db_file())
        contacts = ContactManager(profile, key)
        messages = MessageManager(profile, key)
        root = self.h.pm.paths.get_db_file().parent / 'target-test-blobs'
        blobs = EncryptedBlobStore(root / 'persistent', root / 'temporary', key)
        self.addCleanup(blobs.close)
        tor = Mock()
        tor.onion = 'c' * 56
        tor.is_running.return_value = True
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            target = Daemon(
                profile,
                key_manager,
                tor,
                contacts,
                HistoryManager(profile, key),
                messages,
                blobs,
                session_auth=create_session_auth_context('target-password'),
                require_session_auth=True,
            )
        atexit.unregister(target.stop)
        self.addCleanup(target.stop)
        target._ipc.start()
        self.host.bootstrap.return_value = FrontendBootstrapResult(
            'target',
            False,
            target._ipc.port,
            False,
            OneUseSecretProvider('target-password'),
            Mock(),
            True,
        )
        generation = self.gui.state.generation
        original = self.h.client.disconnect

        def old_disconnect() -> None:
            """Queues the old connection's actual lifecycle callback before releasing it.

            Args:
                None
            Returns:
                None
            """
            self.gui.mailbox.put(Update(generation, 'lost', status='Connection lost'))
            original()

        with patch.object(self.h.client, 'disconnect', side_effect=old_disconnect):
            self.assertTrue(self.gui.lifecycle.start('target'))
            self.settle()
        self.assertFalse(self.gui.lifecycle.failed, self.gui.state.status)
        self.assertFalse(self.gui.state.covered, self.gui.state.status)
        self.assertEqual(self.gui.state.snapshot.profile, 'target')
        self.assertEqual(self.gui.state.generation, generation + 1)
        self.assertIsNotNone(self.gui.voice_owner.token)
        self.assertEqual(
            self.gui.state.preferences.profile_instance_id,
            self.gui.state.snapshot.profile_instance_id,
        )
        self.gui.mailbox.put(Update(generation, 'lost', status='old callback'))
        self.gui.poll()
        self.assertFalse(self.gui.state.covered)
        self.assertTrue(self.gui.client.is_connected)
        self.assertIsNotNone(self.gui.client.runtime_snapshot())
        # Disconnect the GUI before stopping the target's temporary Core.
        self.gui.close()

    def test_unknown_preparation_keeps_cover_and_never_enters_target(self) -> None:
        """Dropping an actual positive receipt cannot make the GUI claim source-active rollback.

        Args:
            None
        Returns:
            None
        """
        original = self.h.client.prepare_profile_exit

        def lost_receipt() -> bool:
            """Performs the real lock but hides its response from the frontend.

            Args:
                None
            Returns:
                bool: Unconfirmed receipt despite actual Core completion.
            """
            self.assertTrue(original())
            return False

        with patch.object(
            self.h.client, 'prepare_profile_exit', side_effect=lost_receipt
        ) as prepare:
            self.assertTrue(self.gui.lifecycle.start('target'))
            self.settle()
            prepare.assert_called_once_with()
        self.assertTrue(self.gui.lifecycle.failed)
        self.assertTrue(self.gui.state.covered)
        self.assertFalse(self.gui.lifecycle.return_available)
        self.host.select_profile.assert_not_called()
        self.assertIn('unconfirmed', self.gui.state.status)

    def test_unconfirmed_capture_stops_before_profile_preparation(self) -> None:
        """Capture failure keeps Core active and offers owner-loss exit only on GUI close.

        Args:
            None
        Returns:
            None
        """
        self.gui.voice.press.phase = PressPhase.FAILED
        with patch.object(
            self.h.client,
            'prepare_profile_exit',
            wraps=self.h.client.prepare_profile_exit,
        ) as prepare:
            self.assertTrue(self.gui.lifecycle.start())
            self.settle()
            prepare.assert_not_called()
        self.assertTrue(self.gui.lifecycle.failed)
        self.assertTrue(self.gui.lifecycle.return_available)
        self.assertFalse(self.gui.lifecycle.exit_ready)
        self.assertIsNotNone(self.h.other.runtime_snapshot())
        self.gui.lifecycle.exit_anyway()
        self.assertTrue(self.gui.lifecycle.exit_ready)

    def password_client(self) -> None:
        """Uses the production SDK timeout for Core's full session-proof derivation.

        The generic producer fixture's two-second transport limit is intentionally
        shorter than the measured password-verifier derivation (2.432 seconds).

        Args:
            None
        Returns:
            None
        """
        provider = Mock()
        provider.get_session_auth_proof.side_effect = lambda challenge, salt: (
            build_session_auth_proof('test-password', challenge, salt)
        )
        client = MetorClient(self.h.daemon._ipc.port, auth_provider=provider)
        self.addCleanup(client.disconnect)
        self.assertIsNotNone(client.bootstrap())
        self.gui.client = client
        self.gui.voice_owner.token = None

    def test_changed_password_controls_new_session_authentication(self) -> None:
        """A persisted password change must retire the old live-session proof verifier too.

        Args:
            None
        Returns:
            None
        """
        self.password_client()
        self.assertTrue(
            self.gui.identity.change_password('test-password', 'new-test-password')
        )
        self.gui._worker.join(5)
        self.gui.poll()
        self.assertEqual(self.gui.identity.outcome, 'saved')
        for secret, accepted in (('test-password', False), ('new-test-password', True)):
            provider = Mock()
            available = [secret]

            def proof(challenge: str, salt: str) -> str | None:
                """Supplies at most one actual proof, never an automatic repeated credential attempt.

                Args:
                    challenge: Actual Core session challenge.
                    salt: Actual Core salt.
                Returns:
                    str | None: One proof or explicit cancellation.
                """
                return (
                    build_session_auth_proof(available.pop(), challenge, salt)
                    if available
                    else None
                )

            provider.get_session_auth_proof.side_effect = proof
            candidate = MetorClient(
                self.h.daemon._ipc.port, auth_provider=provider, timeout=2
            )
            try:
                self.assertEqual(candidate.bootstrap() is not None, accepted)
            finally:
                candidate.disconnect()

    def test_password_change_requires_real_current_password_and_clears_command_secrets(
        self,
    ) -> None:
        """Core rejects a wrong full credential, then accepts an explicit correct replacement.

        Args:
            None
        Returns:
            None
        """
        self.password_client()
        self.assertTrue(
            self.gui.identity.change_password('wrong-password', 'new-test-password')
        )
        self.gui._worker.join(5)
        self.gui.poll()
        self.assertEqual(self.gui.identity.outcome, 'rejected')
        self.assertTrue(
            self.gui.identity.change_password('test-password', 'new-test-password')
        )
        self.gui._worker.join(5)
        self.gui.poll()
        self.assertEqual(self.gui.identity.outcome, 'saved')
        self.assertFalse(self.gui.identity.unknown)
