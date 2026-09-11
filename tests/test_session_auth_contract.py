"""Regression tests for local daemon session-auth challenge and proof flows."""

# ruff: noqa: E402

import socket
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch

import nacl.pwhash

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import (
    AcceptCommand,
    AuthenticateSessionCommand,
    AppendVoiceChunkCommand,
    AuthRequiredEvent,
    InvalidPasswordEvent,
    IpcCommand,
    IpcEvent,
    BeginVoiceCommand,
    ClientReauthorizedEvent,
    ClientUnlockMethod,
    ConfigureQuickUnlockCommand,
    Delivery,
    GetContactsListCommand,
    LockedAcceptPolicy,
    LocalAuthRateLimitedEvent,
    IncomingConnectionEvent,
    PendingConnectionExpiredEvent,
    PrepareProfileExitCommand,
    NotificationPrivacy,
    QuickUnlockFailedEvent,
    QuickUnlockAction,
    ReauthorizeClientCommand,
    RestrictClientCommand,
    RejectCommand,
    SelfDestructCommand,
    SessionAuthenticatedEvent,
    VoiceChunkReceivedEvent,
    VoiceIncomingStartedEvent,
)
from metor.core.daemon.managed.engine.session_access import SessionAccessController
from metor.core.daemon.managed.local_auth import (
    LocalAuthTracker,
    create_session_auth_context,
)
from metor.core.daemon.managed.quick_unlock import (
    QuickUnlockStore,
    create_pin_verifier,
)
from metor.utils import Constants, build_session_auth_proof


class SessionAuthContractTests(unittest.TestCase):
    """
    Covers session auth contract regression scenarios.
    """

    def test_quick_unlock_configuration_requires_full_password_proof(self) -> None:
        """Keeps PIN mutation gated when ordinary session auth is optional."""
        with TemporaryDirectory() as temp_dir:
            store = QuickUnlockStore(Path(temp_dir) / 'quick-unlock.json')
            sent: list[IpcEvent] = []
            conn = cast(socket.socket, object())
            controller = SessionAccessController(
                require_auth=False,
                send_callback=lambda _conn, event: sent.append(event),
                lockout_timeout_callback=lambda: 30.0,
                failure_limit_callback=lambda: 3,
                live_consumer_available_callback=lambda: None,
                quick_unlock_store=store,
            )
            controller.install_context(create_session_auth_context('profile-password'))
            salt, verifier = create_pin_verifier('1234')
            command = ConfigureQuickUnlockCommand(
                action=QuickUnlockAction.SET,
                salt=salt,
                verifier=verifier,
            )

            self.assertFalse(controller.authorize(command, conn, True))
            prompt = cast(AuthRequiredEvent, sent[-1])
            self.assertIsInstance(prompt, AuthRequiredEvent)
            assert prompt.challenge is not None
            assert prompt.salt is not None
            proof = build_session_auth_proof(
                'profile-password', prompt.challenge, prompt.salt
            )
            self.assertFalse(
                controller.authorize(AuthenticateSessionCommand(proof), conn, True)
            )
            self.assertIsInstance(sent[-1], SessionAuthenticatedEvent)
            self.assertTrue(controller.authorize(command, conn, True))

    def test_quick_unlock_verifier_has_owner_only_permissions(self) -> None:
        """Treats the persisted PIN verifier as protected credential material."""
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'protected' / 'quick-unlock.json'
            store = QuickUnlockStore(path)
            salt, verifier = create_pin_verifier('1234')

            store.configure(salt, verifier)

            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_restricted_client_enforces_scope_and_pin_password_escalation(self) -> None:
        """Blocks normal access and requires password after three failed PIN proofs."""
        with TemporaryDirectory() as temp_dir:
            store = QuickUnlockStore(Path(temp_dir) / 'quick-unlock.json')
            salt, verifier = create_pin_verifier('1234')
            store.configure(salt, verifier)
            sent: list[IpcEvent] = []
            conn = cast(socket.socket, object())
            controller = SessionAccessController(
                require_auth=False,
                send_callback=lambda _conn, event: sent.append(event),
                lockout_timeout_callback=lambda: 30.0,
                failure_limit_callback=lambda: 6,
                live_consumer_available_callback=lambda: None,
                quick_unlock_store=store,
                resolve_target_callback=lambda target: {
                    'alice': 'alice-onion',
                    'bob': 'bob-onion',
                }.get(target, target),
                voice_target_callback=lambda msg_id: (
                    'alice-onion' if msg_id == 'alice-voice' else 'bob-onion'
                ),
                voice_delivery_callback=lambda msg_id: (
                    Delivery.LIVE if msg_id == 'alice-voice' else Delivery.DROP
                ),
            )
            controller.install_context(create_session_auth_context('profile-password'))
            restricted = controller.restrict(
                conn,
                RestrictClientCommand(
                    unlock_method=ClientUnlockMethod.PIN,
                    continued_live_target='alice',
                    live_while_locked=True,
                    accept_while_locked=LockedAcceptPolicy.NONE,
                    notification_privacy=NotificationPrivacy.ANONYMIZE,
                ),
            )
            self.assertEqual(getattr(restricted, 'salt'), salt)
            self.assertFalse(controller.authorize(GetContactsListCommand(), conn, True))
            self.assertFalse(
                controller.authorize(
                    BeginVoiceCommand('bob', Delivery.LIVE, 'voice-1', 'opus'),
                    conn,
                    True,
                )
            )
            self.assertTrue(
                controller.authorize(
                    BeginVoiceCommand('alice', Delivery.LIVE, 'voice-2', 'opus'),
                    conn,
                    True,
                )
            )
            self.assertFalse(
                controller.authorize(
                    BeginVoiceCommand('alice', Delivery.DROP, 'voice-3', 'opus'),
                    conn,
                    True,
                )
            )
            self.assertTrue(
                controller.authorize(
                    AppendVoiceChunkCommand('alice-voice', 0, 'YQ=='), conn, True
                )
            )

            for _ in range(3):
                controller.authorize(
                    ReauthorizeClientCommand(
                        method=ClientUnlockMethod.PIN,
                        proof='00' * 32,
                    ),
                    conn,
                    True,
                )
            failure = cast(QuickUnlockFailedEvent, sent[-1])
            self.assertIsInstance(failure, QuickUnlockFailedEvent)
            self.assertTrue(failure.password_required)
            assert failure.challenge is not None
            assert failure.salt is not None
            password_proof = build_session_auth_proof(
                'profile-password', failure.challenge, failure.salt
            )
            controller.authorize(
                ReauthorizeClientCommand(
                    method=ClientUnlockMethod.PROFILE_PASSWORD,
                    proof=password_proof,
                ),
                conn,
                True,
            )
            self.assertIsInstance(sent[-1], ClientReauthorizedEvent)
            self.assertTrue(controller.authorize(GetContactsListCommand(), conn, True))

    def test_restricted_password_retries_share_global_cooldown(self) -> None:
        """Applies the established auth failure limit to restricted passwords."""
        sent: list[IpcEvent] = []
        conn = cast(socket.socket, object())
        controller = SessionAccessController(
            require_auth=False,
            send_callback=lambda _conn, event: sent.append(event),
            lockout_timeout_callback=lambda: 30.0,
            failure_limit_callback=lambda: 3,
            live_consumer_available_callback=lambda: None,
        )
        controller.install_context(create_session_auth_context('profile-password'))
        controller.restrict(
            conn,
            RestrictClientCommand(unlock_method=ClientUnlockMethod.PROFILE_PASSWORD),
        )

        for _ in range(3):
            controller.authorize(
                ReauthorizeClientCommand(
                    method=ClientUnlockMethod.PROFILE_PASSWORD,
                    proof='00' * 32,
                ),
                conn,
                True,
            )

        self.assertIsInstance(sent[-1], LocalAuthRateLimitedEvent)

    def test_forgot_pin_issues_password_challenge_without_failed_attempt(self) -> None:
        """Switches proof methods explicitly and accepts the resulting challenge."""
        with TemporaryDirectory() as temp_dir:
            store = QuickUnlockStore(Path(temp_dir) / 'quick-unlock.json')
            pin_salt, verifier = create_pin_verifier('1234')
            store.configure(pin_salt, verifier)
            sent: list[IpcEvent] = []
            conn = cast(socket.socket, object())
            controller = SessionAccessController(
                require_auth=False,
                send_callback=lambda _conn, event: sent.append(event),
                lockout_timeout_callback=lambda: 30.0,
                failure_limit_callback=lambda: 3,
                live_consumer_available_callback=lambda: None,
                quick_unlock_store=store,
            )
            controller.install_context(create_session_auth_context('profile-password'))
            controller.restrict(
                conn,
                RestrictClientCommand(unlock_method=ClientUnlockMethod.PIN),
            )

            controller.authorize(
                ReauthorizeClientCommand(
                    method=ClientUnlockMethod.PROFILE_PASSWORD,
                    proof=None,
                ),
                conn,
                True,
            )
            challenge_event = cast(QuickUnlockFailedEvent, sent[-1])
            self.assertTrue(challenge_event.password_required)
            assert challenge_event.challenge is not None
            assert challenge_event.salt is not None
            proof = build_session_auth_proof(
                'profile-password',
                challenge_event.challenge,
                challenge_event.salt,
            )
            controller.authorize(
                ReauthorizeClientCommand(
                    method=ClientUnlockMethod.PROFILE_PASSWORD,
                    proof=proof,
                ),
                conn,
                True,
            )

            self.assertIsInstance(sent[-1], ClientReauthorizedEvent)

    def test_locked_media_scope_is_independent_of_notification_privacy(self) -> None:
        """G18: Alice Voice remains available while Bob Voice stays filtered."""
        for privacy in NotificationPrivacy:
            with self.subTest(privacy=privacy):
                conn = cast(socket.socket, object())
                controller = SessionAccessController(
                    require_auth=False,
                    send_callback=lambda _conn, _event: None,
                    lockout_timeout_callback=lambda: 30.0,
                    failure_limit_callback=lambda: 3,
                    live_consumer_available_callback=lambda: None,
                    resolve_target_callback=lambda target: f'{target}-onion',
                )
                controller.restrict(
                    conn,
                    RestrictClientCommand(
                        continued_live_target='alice',
                        live_while_locked=True,
                        notification_privacy=privacy,
                    ),
                )
                alice_start = VoiceIncomingStartedEvent(
                    alias='alice',
                    onion='alice-onion',
                    msg_id='alice-voice',
                    delivery=Delivery.LIVE,
                    codec='opus',
                    next_offset=0,
                )
                alice_chunk = VoiceChunkReceivedEvent(
                    alias='alice',
                    onion='alice-onion',
                    msg_id='alice-voice',
                    offset=0,
                    data='YQ==',
                    delivery=Delivery.LIVE,
                    codec='opus',
                )
                bob_chunk = VoiceChunkReceivedEvent(
                    alias='bob',
                    onion='bob-onion',
                    msg_id='bob-voice',
                    offset=0,
                    data='Yg==',
                    delivery=Delivery.LIVE,
                    codec='opus',
                )
                self.assertIs(
                    controller.filter_restricted_event(conn, alice_start), alice_start
                )
                self.assertIs(
                    controller.filter_restricted_event(conn, alice_chunk), alice_chunk
                )
                self.assertIsNone(controller.filter_restricted_event(conn, bob_chunk))

    def test_anonymized_call_handles_are_unique_actionable_and_expirable(self) -> None:
        """G19: two callers remain independently actionable without identity leakage."""
        conn = cast(socket.socket, object())
        controller = SessionAccessController(
            require_auth=False,
            send_callback=lambda _conn, _event: None,
            lockout_timeout_callback=lambda: 30.0,
            failure_limit_callback=lambda: 3,
            live_consumer_available_callback=lambda: None,
        )
        controller.restrict(
            conn,
            RestrictClientCommand(
                accept_while_locked=LockedAcceptPolicy.ALL,
                notification_privacy=NotificationPrivacy.ANONYMIZE,
            ),
        )
        alice = cast(
            IncomingConnectionEvent,
            controller.filter_restricted_event(
                conn, IncomingConnectionEvent(alias='alice', onion='alice-onion')
            ),
        )
        bob = cast(
            IncomingConnectionEvent,
            controller.filter_restricted_event(
                conn, IncomingConnectionEvent(alias='bob', onion='bob-onion')
            ),
        )
        self.assertEqual((alice.alias, alice.onion), ('unknown', None))
        self.assertEqual((bob.alias, bob.onion), ('unknown', None))
        self.assertIsNotNone(alice.action_handle)
        self.assertIsNotNone(bob.action_handle)
        self.assertNotEqual(alice.action_handle, bob.action_handle)

        accept = AcceptCommand(cast(str, alice.action_handle))
        self.assertTrue(controller.authorize(accept, conn, True))
        self.assertEqual(accept.target, 'alice-onion')
        expired = cast(
            PendingConnectionExpiredEvent,
            controller.filter_restricted_event(
                conn,
                PendingConnectionExpiredEvent(alias='bob', onion='bob-onion'),
            ),
        )
        self.assertEqual(expired.action_handle, bob.action_handle)
        reject = RejectCommand(cast(str, bob.action_handle))
        self.assertFalse(controller.authorize(reject, conn, True))

    def test_device_lifecycle_scope_requires_prior_authenticated_session(self) -> None:
        """G27: destructive locked controls are a narrow authenticated capability."""
        sent: list[IpcEvent] = []
        trusted = cast(socket.socket, object())
        untrusted = cast(socket.socket, object())
        controller = SessionAccessController(
            require_auth=False,
            send_callback=lambda _conn, event: sent.append(event),
            lockout_timeout_callback=lambda: 30.0,
            failure_limit_callback=lambda: 3,
            live_consumer_available_callback=lambda: None,
        )
        controller.mark_authenticated(trusted)
        trusted_event = controller.restrict(
            trusted,
            RestrictClientCommand(device_lifecycle=True),
        )
        untrusted_event = controller.restrict(
            untrusted,
            RestrictClientCommand(device_lifecycle=True),
        )
        self.assertTrue(getattr(trusted_event, 'device_lifecycle'))
        self.assertFalse(getattr(untrusted_event, 'device_lifecycle'))
        self.assertTrue(controller.authorize(SelfDestructCommand(), trusted, True))
        self.assertTrue(
            controller.authorize(PrepareProfileExitCommand(), trusted, True)
        )
        self.assertFalse(controller.authorize(SelfDestructCommand(), untrusted, True))

    def test_authenticate_session_command_uses_proof_field(self) -> None:
        """
        Verifies that authenticate session command uses proof field.

        Args:
            None

        Returns:
            None
        """

        cmd = IpcCommand.from_dict(
            {
                'command_type': 'authenticate_session',
                'proof': 'abc123',
            }
        )

        self.assertIsInstance(cmd, AuthenticateSessionCommand)
        typed_cmd = cast(AuthenticateSessionCommand, cmd)

        self.assertEqual(typed_cmd.proof, 'abc123')

    def test_runtime_auth_events_preserve_optional_challenge_payload(self) -> None:
        """
        Verifies that runtime auth events preserve optional challenge payload.

        Args:
            None

        Returns:
            None
        """

        challenge = 'ab' * Constants.SESSION_AUTH_CHALLENGE_BYTES
        salt = 'cd' * nacl.pwhash.argon2i.SALTBYTES

        auth_event = IpcEvent.from_dict(
            {
                'event_type': 'auth_required',
                'challenge': challenge,
                'salt': salt,
            }
        )
        invalid_event = IpcEvent.from_dict(
            {
                'event_type': 'invalid_password',
                'challenge': challenge,
                'salt': salt,
            }
        )

        self.assertIsInstance(auth_event, AuthRequiredEvent)
        typed_auth_event = cast(AuthRequiredEvent, auth_event)
        self.assertEqual(typed_auth_event.challenge, challenge)
        self.assertEqual(typed_auth_event.salt, salt)
        self.assertIsInstance(invalid_event, InvalidPasswordEvent)
        typed_invalid_event = cast(InvalidPasswordEvent, invalid_event)
        self.assertEqual(typed_invalid_event.challenge, challenge)
        self.assertEqual(typed_invalid_event.salt, salt)

    def test_local_auth_tracker_accepts_valid_session_proof(self) -> None:
        """
        Verifies that local auth tracker accepts valid session proof.

        Args:
            None

        Returns:
            None
        """

        tracker = LocalAuthTracker()
        context = create_session_auth_context(
            'correct horse battery staple',
            b'\x11' * nacl.pwhash.argon2i.SALTBYTES,
        )
        tracker.install_context(context)

        left, right = socket.socketpair()
        try:
            prompt = tracker.issue_session_challenge(right)

            self.assertIsNotNone(prompt)

            assert prompt is not None
            proof = build_session_auth_proof(
                'correct horse battery staple',
                prompt.challenge,
                prompt.salt,
            )
            result = tracker.verify_session_proof(right, proof)

            self.assertTrue(result.authenticated)
            self.assertFalse(result.should_disconnect)
            self.assertIsNone(result.retry_prompt)
        finally:
            left.close()
            right.close()

    def test_local_auth_tracker_rotates_challenge_and_disconnects_after_limit(
        self,
    ) -> None:
        """
        Verifies that local auth tracker rotates challenge and disconnects after limit.

        Args:
            None

        Returns:
            None
        """

        tracker = LocalAuthTracker()
        context = create_session_auth_context(
            'correct horse battery staple',
            b'\x22' * nacl.pwhash.argon2i.SALTBYTES,
        )
        tracker.install_context(context)

        left, right = socket.socketpair()
        try:
            prompt = tracker.issue_session_challenge(right)

            self.assertIsNotNone(prompt)

            for attempt in range(Constants.IPC_AUTH_FAILURE_LIMIT):
                result = tracker.verify_session_proof(right, 'deadbeef')

                self.assertFalse(result.authenticated)
                if attempt + 1 < Constants.IPC_AUTH_FAILURE_LIMIT:
                    self.assertFalse(result.should_disconnect)
                    self.assertIsNotNone(result.retry_prompt)
                else:
                    self.assertTrue(result.should_disconnect)
                    self.assertIsNone(result.retry_prompt)
        finally:
            left.close()
            right.close()

    def test_local_auth_lockout_survives_reconnects_until_cooldown_expires(
        self,
    ) -> None:
        """
        Verifies that local auth lockout survives reconnects until cooldown expires.

        Args:
            None

        Returns:
            None
        """

        tracker = LocalAuthTracker()
        first_left, first_right = socket.socketpair()
        second_left, second_right = socket.socketpair()

        try:
            with patch(
                'metor.core.daemon.managed.local_auth.time.monotonic',
                return_value=100.0,
            ):
                for _ in range(Constants.IPC_AUTH_FAILURE_LIMIT):
                    tracker.register_invalid_unlock(first_right, lockout_seconds=30.0)

            with patch(
                'metor.core.daemon.managed.local_auth.time.monotonic',
                return_value=110.0,
            ):
                retry_after = tracker.get_retry_after_seconds()

                self.assertIsNotNone(retry_after)
                self.assertGreaterEqual(cast(int, retry_after), 20)
                self.assertTrue(
                    tracker.register_invalid_unlock(
                        second_right,
                        lockout_seconds=30.0,
                    )
                )

            with patch(
                'metor.core.daemon.managed.local_auth.time.monotonic',
                return_value=131.0,
            ):
                self.assertIsNone(tracker.get_retry_after_seconds())
                self.assertFalse(
                    tracker.register_invalid_unlock(
                        second_right,
                        lockout_seconds=30.0,
                    )
                )
        finally:
            first_left.close()
            first_right.close()
            second_left.close()
            second_right.close()

    def test_local_auth_disconnect_limit_survives_reconnects_without_cooldown(
        self,
    ) -> None:
        """
        Verifies that local auth disconnect limit survives reconnects without cooldown.

        Args:
            None

        Returns:
            None
        """

        tracker = LocalAuthTracker()
        first_left, first_right = socket.socketpair()
        second_left, second_right = socket.socketpair()

        try:
            for _ in range(Constants.IPC_AUTH_FAILURE_LIMIT - 1):
                self.assertFalse(
                    tracker.register_invalid_unlock(first_right, lockout_seconds=0.0)
                )

            tracker.clear_connection(first_right)

            self.assertTrue(
                tracker.register_invalid_unlock(second_right, lockout_seconds=0.0)
            )
            self.assertIsNone(tracker.get_retry_after_seconds())
        finally:
            first_left.close()
            first_right.close()
            second_left.close()
            second_right.close()

    def test_local_auth_tracker_honors_custom_failure_limit(self) -> None:
        """
        Verifies that local auth tracker honors a configured failure limit override.

        Args:
            None

        Returns:
            None
        """

        tracker = LocalAuthTracker()
        context = create_session_auth_context(
            'correct horse battery staple',
            b'\x33' * nacl.pwhash.argon2i.SALTBYTES,
        )
        tracker.install_context(context)

        left, right = socket.socketpair()
        try:
            prompt = tracker.issue_session_challenge(right)

            self.assertIsNotNone(prompt)

            result = tracker.verify_session_proof(
                right,
                'deadbeef',
                failure_limit=1,
            )

            self.assertFalse(result.authenticated)
            self.assertTrue(result.should_disconnect)
            self.assertIsNone(result.retry_prompt)
        finally:
            left.close()
            right.close()


if __name__ == '__main__':
    unittest.main()
