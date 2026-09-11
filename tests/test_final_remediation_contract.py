"""Focused regressions for the final Refactor-2 remediation workstream."""

# ruff: noqa: E402

import socket
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, cast
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.cli.handlers import CommandHandlers
from metor.client import (
    FRONTEND_LAUNCH_CONTRACT_VERSION,
    FrontendBootstrapError,
    FrontendDescriptor,
    FrontendEntry,
    FrontendLaunchContext,
    LoadedFrontend,
    MetorClient,
    FrontendProfileCreateRequest,
    FrontendProfileSecurity,
    OneUseSecretProvider,
    ProfileRuntimeCoordinator,
    ProfileSwitchError,
    ProfileSwitchPhase,
)
from metor.core.api import (
    AuthenticateSessionCommand,
    ClientUnlockMethod,
    ConfigureQuickUnlockCommand,
    Delivery,
    EventType,
    GetVoiceChunkCommand,
    IpcEvent,
    MessageDirectionCode,
    NotificationPrivacy,
    QuickUnlockAction,
    ReleaseVoiceCommand,
    RestrictClientCommand,
    RuntimeSnapshotEvent,
    VoiceResourceLimitEvent,
)
from metor.core.daemon.managed.engine.session_access import SessionAccessController
from metor.core.daemon.managed.local_auth import create_session_auth_context
from metor.core.daemon.managed.quick_unlock import (
    QuickUnlockStorageError,
    QuickUnlockStore,
    create_pin_verifier,
)
from metor.core.daemon.managed.network.state import StateTracker
from metor.core.daemon.managed.writer import BoundedSocketWriter, FrameQueueFull
from metor.core.profile_destruction import destroy_profile_storage
from metor.data import (
    ProfileManager,
    ProfileOperationResult,
    ProfileOperationType,
    ProfileSecurityMode,
)
from metor.data.sql import SqlManager
from metor.utils import Constants, build_session_auth_proof


class _Interactions:
    """No-TTY frontend interactions used by the fake GUI launcher."""

    def __init__(self) -> None:
        self.statuses: list[str] = []

    def confirm_daemon_start(self) -> Optional[bool]:
        return True

    def request_session_auth_secret(self) -> Optional[str]:
        return None

    def show_status(self, message: str) -> None:
        self.statuses.append(message)


class FinalRemediationContractTests(unittest.TestCase):
    """Exercises corrected behavior at public or enclosing production boundaries."""

    def test_windows_acl_helpers_are_bounded_and_fail_safely(self) -> None:
        """C01: a stuck credential helper becomes a sanitized bounded failure."""
        with patch(
            'metor.core.daemon.managed.quick_unlock.subprocess.run',
            side_effect=subprocess.TimeoutExpired('powershell.exe', 10),
        ) as run:
            with self.assertRaisesRegex(QuickUnlockStorageError, 'could not'):
                QuickUnlockStore._protect_windows_path(
                    Path('path with spaces'), directory=False
                )
        self.assertEqual(
            run.call_args.kwargs['timeout'], Constants.QUICK_UNLOCK_HELPER_TIMEOUT_SEC
        )

    def test_sensitive_grant_is_verified_scoped_consumed_and_session_local(
        self,
    ) -> None:
        """C02: idempotent auth cannot upgrade PIN/NONE-strength sessions."""
        with TemporaryDirectory() as temp_dir:
            events: list[IpcEvent] = []
            store = QuickUnlockStore(Path(temp_dir) / 'quick-unlock.json')
            controller = SessionAccessController(
                require_auth=False,
                send_callback=lambda _conn, event: events.append(event),
                lockout_timeout_callback=lambda: 30.0,
                failure_limit_callback=lambda: 5,
                live_consumer_available_callback=lambda: None,
                quick_unlock_store=store,
            )
            controller.install_context(create_session_auth_context('password'))
            conn = cast(socket.socket, object())
            other = cast(socket.socket, object())
            controller.mark_authenticated(conn, full_password=False)
            command = ConfigureQuickUnlockCommand(
                QuickUnlockAction.SET, *create_pin_verifier('1234')
            )

            controller.authorize(AuthenticateSessionCommand('invalid'), conn, True)
            self.assertFalse(controller.authorize(command, conn, True))
            prompt = events[-1]
            challenge = cast(str, getattr(prompt, 'challenge'))
            salt = cast(str, getattr(prompt, 'salt'))
            proof = build_session_auth_proof('password', challenge, salt)
            controller.authorize(AuthenticateSessionCommand(proof), conn, True)
            self.assertTrue(controller.authorize(command, conn, True))
            self.assertEqual(
                controller.configure_quick_unlock(conn, command).event_type,
                EventType.QUICK_UNLOCK_CONFIGURED,
            )
            self.assertEqual(
                controller.configure_quick_unlock(conn, command).event_type,
                EventType.QUICK_UNLOCK_FAILED,
            )
            self.assertFalse(controller.authorize(command, other, True))

    def test_writer_survives_idle_and_failure_closes_real_socket(self) -> None:
        """C03: accepted work always has a worker and write failure owns cleanup."""
        local, remote = socket.socketpair()
        self.addCleanup(remote.close)
        writer = BoundedSocketWriter(
            local, capacity=2, byte_capacity=8, max_frame_bytes=4
        )
        self.assertTrue(writer.wait_started(timeout=1.0))
        writer.enqueue(b'ok')
        self.assertEqual(remote.recv(2), b'ok')
        with self.assertRaises(FrameQueueFull):
            writer.enqueue(b'oversized')
        writer.close()
        self.assertEqual(local.fileno(), -1)

        failed, peer = socket.socketpair()
        failure = threading.Event()
        peer.close()
        failed_writer = BoundedSocketWriter(
            failed,
            capacity=1,
            on_failure=lambda _conn, _exc: failure.set(),
        )
        failed_writer.enqueue(b'x')
        self.assertTrue(failure.wait(timeout=1.0))
        for _ in range(100):
            if failed.fileno() == -1:
                break
            threading.Event().wait(0.005)
        self.assertEqual(failed.fileno(), -1)

    def test_destruction_attempts_disk_key_after_every_preparation_failure(
        self,
    ) -> None:
        """C06: false prep, DB close, and memory-key errors cannot skip erasure."""
        pm = Mock(spec=ProfileManager)
        pm.paths = Mock()
        pm.paths.get_db_file.return_value = Path('db')
        pm.paths.get_config_dir.return_value = Path('profile')
        protector = Mock()
        cleanup = Mock()
        failures: list[tuple[str, bool]] = []
        with (
            patch.object(SqlManager, 'close_connection', side_effect=OSError('close')),
            self.assertRaises(RuntimeError),
        ):
            destroy_profile_storage(
                cast(ProfileManager, pm),
                prepare_runtime=lambda: False,
                clear_runtime_keys=Mock(side_effect=RuntimeError('memory')),
                protector=protector,
                cleanup=cleanup,
                failure_callback=lambda phase, destroyed: failures.append(
                    (phase, destroyed)
                ),
            )
        protector.destroy.assert_called_once_with()
        cleanup.assert_called_once_with(Path('profile'))
        self.assertEqual(failures, [('preparation', True)])

    def test_restricted_media_is_direction_delivery_and_context_bound(self) -> None:
        """C09: locked reads/releases cannot escape the frozen LIVE context."""
        token = object()
        current_token: list[object] = [token]
        conn = cast(socket.socket, object())
        access = SessionAccessController(
            require_auth=False,
            send_callback=lambda _conn, _event: None,
            lockout_timeout_callback=lambda: 30.0,
            failure_limit_callback=lambda: 3,
            live_consumer_available_callback=lambda: None,
            resolve_target_callback=lambda target: {'alice': 'alice-onion'}.get(
                target, target
            ),
            inbound_voice_delivery_callback=lambda onion, msg_id: (
                Delivery.LIVE
                if (onion, msg_id) == ('alice-onion', 'voice')
                else Delivery.DROP
            ),
            live_context_callback=lambda _onion: current_token[0],
        )
        access.restrict(
            conn,
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                continued_live_target='alice',
                live_while_locked=True,
                notification_privacy=NotificationPrivacy.ANONYMIZE,
            ),
        )
        self.assertTrue(
            access.authorize(
                GetVoiceChunkCommand('alice', 'voice', MessageDirectionCode.IN, 0, 10),
                conn,
                True,
            )
        )
        self.assertFalse(
            access.authorize(
                GetVoiceChunkCommand('alice', 'voice', MessageDirectionCode.OUT, 0, 10),
                conn,
                True,
            )
        )
        current_token[0] = object()
        self.assertFalse(
            access.authorize(ReleaseVoiceCommand('alice', 'voice'), conn, True)
        )

    def test_live_context_generation_survives_recovery_not_new_conversation(
        self,
    ) -> None:
        """C09: recovery preserves scope while a later same-peer call cannot inherit it."""
        state = StateTracker()
        first = cast(socket.socket, Mock())
        recovered = cast(socket.socket, Mock())
        later = cast(socket.socket, Mock())
        state.add_active_connection('alice', first)
        original = state.get_live_context_generation('alice')

        self.assertIs(state.pop_any_connection('alice'), first)
        state.mark_scheduled_auto_reconnect('alice')
        state.add_active_connection('alice', recovered)
        self.assertEqual(state.get_live_context_generation('alice'), original)

        self.assertIs(state.pop_any_connection('alice'), recovered)
        state.add_active_connection('alice', later)
        self.assertNotEqual(state.get_live_context_generation('alice'), original)

    def test_snapshot_barrier_excludes_mutate_and_restore_windows(self) -> None:
        """C08: aggregate collection owns a real mutation barrier, not a fingerprint."""
        state = StateTracker()
        attempting = threading.Event()
        completed = threading.Event()

        def mutate() -> None:
            attempting.set()
            state.mark_scheduled_auto_reconnect('alice')
            state.clear_scheduled_auto_reconnect('alice')
            completed.set()

        with state.snapshot_barrier():
            worker = threading.Thread(target=mutate)
            worker.start()
            self.assertTrue(attempting.wait(timeout=1.0))
            self.assertFalse(completed.is_set())
        worker.join(timeout=1.0)
        self.assertFalse(worker.is_alive())
        self.assertTrue(completed.is_set())

    def test_public_append_voice_returns_correlated_resource_outcome(self) -> None:
        """C07: quota finalization is preserved at the public SDK method."""
        client = MetorClient(1)
        transport = Mock()
        outcome = VoiceResourceLimitEvent(
            used_bytes=8,
            limit_bytes=8,
            msg_id='voice',
        )
        transport.wait_for_response.return_value = outcome
        client._ipc = transport

        self.assertIs(client.append_voice('voice', 8, 'YQ=='), outcome)
        transport.begin_request.assert_called_once()
        transport.send_command.assert_called_once()
        transport.end_request.assert_called_once()

    def test_profile_switch_failure_keeps_candidate_unpublished(self) -> None:
        """C10: target failures are typed and partial clients are disposed."""
        old = Mock()
        old.runtime_snapshot.return_value = RuntimeSnapshotEvent(profile='a', onion='')
        old.prepare_profile_exit.return_value = True
        candidate = Mock()
        candidate.bootstrap.return_value = Mock()
        candidate.runtime_snapshot.return_value = None
        coordinator = ProfileRuntimeCoordinator(old, lambda _profile: candidate)

        with self.assertRaises(ProfileSwitchError) as raised:
            coordinator.switch('b')
        self.assertIs(raised.exception.phase, ProfileSwitchPhase.TARGET_SNAPSHOT)
        self.assertIs(coordinator.client, old)
        candidate.disconnect.assert_called_once_with()

    def test_fake_gui_starts_before_deferred_host_without_terminal_prompts(
        self,
    ) -> None:
        """C11: a no-TTY frontend owns interaction timing through the public host."""
        started = threading.Event()
        interactions = _Interactions()
        pm = Mock(spec=ProfileManager)
        pm.profile_name = 'default'
        pm.config = Mock()
        pm.config.get_str.return_value = 'always'
        pm.exists.side_effect = lambda: started.is_set()
        pm.is_daemon_running.return_value = False
        pm.is_remote.return_value = False
        pm.uses_plaintext_storage.return_value = False
        pm.uses_encrypted_storage.return_value = True
        pm.get_static_port.return_value = 4312

        def fake_gui(context: FrontendLaunchContext) -> int:
            started.set()
            result = context.host.bootstrap(interactions)
            self.assertEqual(result.port, 4312)
            return 0

        setattr(fake_gui, 'contract_version', FRONTEND_LAUNCH_CONTRACT_VERSION)
        loaded = LoadedFrontend(
            FrontendDescriptor('fake-gui', 'tests', 'tests:fake_gui'),
            cast(FrontendEntry, fake_gui),
        )
        with (
            patch(
                'metor.cli.handlers.prompt_text',
                side_effect=AssertionError('base terminal prompt used'),
            ),
            patch(
                'metor.cli.handlers.prompt_hidden',
                side_effect=AssertionError('base terminal prompt used'),
            ),
            patch(
                'metor.application.frontend.start_managed_daemon_process',
                return_value=True,
            ),
        ):
            status = CommandHandlers.handle_chat(
                cast(ProfileManager, pm), loaded_frontend=loaded
            )
        self.assertEqual(status, 0)
        self.assertTrue(started.is_set())
        self.assertEqual(interactions.statuses, ['Starting local daemon...'])

    def test_fake_gui_observes_missing_profile_as_typed_first_run_state(self) -> None:
        """C11: missing profile is reported after frontend startup, not before it."""
        started = False
        pm = Mock(spec=ProfileManager)
        pm.profile_name = 'missing'
        pm.config = Mock()
        pm.config.get_str.return_value = 'always'
        pm.exists.return_value = False

        def fake_gui(context: FrontendLaunchContext) -> int:
            nonlocal started
            started = True
            self.assertFalse(context.host.profile_state().exists)
            with self.assertRaises(FrontendBootstrapError) as raised:
                context.host.bootstrap(_Interactions())
            self.assertIn('does not exist', str(raised.exception))
            return 0

        setattr(fake_gui, 'contract_version', FRONTEND_LAUNCH_CONTRACT_VERSION)
        loaded = LoadedFrontend(
            FrontendDescriptor('fake-gui', 'tests', 'tests:fake_gui'),
            cast(FrontendEntry, fake_gui),
        )
        self.assertEqual(
            CommandHandlers.handle_chat(
                cast(ProfileManager, pm), loaded_frontend=loaded
            ),
            0,
        )
        self.assertTrue(started)

    def test_fake_gui_creates_and_selects_profile_via_public_host(self) -> None:
        """C11: first-run creation consumes its secret through the base factory."""
        initial = Mock(spec=ProfileManager)
        initial.profile_name = 'missing'
        initial.config = Mock()
        initial.config.get_str.return_value = 'fake-gui'
        created = Mock(spec=ProfileManager)
        created.profile_name = 'created'
        created.exists.return_value = True
        created.is_remote.return_value = False
        created.is_daemon_running.return_value = False
        profile_factory = Mock(return_value=created)
        profile_factory.add_profile_folder.return_value = ProfileOperationResult(
            True,
            ProfileOperationType.PROFILE_CREATED,
            {'profile': 'created'},
        )
        secret = OneUseSecretProvider('temporary-password')

        def fake_gui(context: FrontendLaunchContext) -> int:
            result = context.host.create_profile(
                FrontendProfileCreateRequest(
                    'created', security=FrontendProfileSecurity.ENCRYPTED
                ),
                secret,
            )
            self.assertTrue(result.success)
            self.assertEqual(context.host.profile_state().profile, 'created')
            return 0

        setattr(fake_gui, 'contract_version', FRONTEND_LAUNCH_CONTRACT_VERSION)
        loaded = LoadedFrontend(
            FrontendDescriptor('fake-gui', 'tests', 'tests:fake_gui'),
            cast(FrontendEntry, fake_gui),
        )
        with patch('metor.application.frontend.ProfileManager', profile_factory):
            self.assertEqual(
                CommandHandlers.handle_chat(
                    cast(ProfileManager, initial), loaded_frontend=loaded
                ),
                0,
            )
        profile_factory.add_profile_folder.assert_called_once_with(
            'created',
            is_remote=False,
            port=None,
            security_mode=ProfileSecurityMode.ENCRYPTED,
            master_password='temporary-password',
        )
        self.assertIsNone(secret.take())


if __name__ == '__main__':
    unittest.main()
