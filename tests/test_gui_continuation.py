"""Restricted media grants and privacy projections through actual Core IPC."""

import socket
import time
import unittest

import test_gui_producers as support
from metor.client import FrontendProfileState
from metor.core.api import (
    ClientRestrictedEvent,
    ClientUnlockMethod,
    GetRestrictedClientStateCommand,
    NotificationPrivacy,
    RestrictClientCommand,
    RestrictedClientStateEvent,
)


class ContinuedCoreTests(unittest.TestCase):
    """Uses temporary encrypted profiles and controlled socket pairs, never a microphone."""

    def setUp(self) -> None:
        """Starts independently authenticated local clients for one isolated Core.

        Args:
            None
        Returns:
            None
        """
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.state = self.h.daemon._transport_state

    def active(self) -> int:
        """Installs one controlled active logical context.

        Args:
            None
        Returns:
            int: Core-issued generation for that context.
        """
        local, remote = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(remote.close)
        self.state.add_active_connection(self.h.onion, local)
        return self.state.get_live_context_generation(self.h.onion)

    def query(self) -> RestrictedClientStateEvent:
        """Reads the requesting client's current restricted projection.

        Args:
            None
        Returns:
            RestrictedClientStateEvent: Actual public Core projection.
        """
        return self.h.client.request(
            GetRestrictedClientStateCommand(), RestrictedClientStateEvent
        )

    def test_off_preserves_exact_continuation_but_replacement_revokes_it(self) -> None:
        """Notification Off and media continuation are independent immutable grants.

        Args:
            None
        Returns:
            None
        """
        generation = self.active()
        result = self.h.client.request(
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                continued_live_target=self.h.onion,
                live_while_locked=True,
                notification_privacy=NotificationPrivacy.OFF,
                continued_live_context_generation=generation,
            ),
            ClientRestrictedEvent,
        )
        self.assertEqual(result.continued_live_context_generation, generation)
        projected = self.query()
        self.assertTrue(projected.restricted)
        self.assertEqual(projected.continued_live_target, self.h.onion)
        self.assertEqual(projected.session_state, 'connected')
        self.assertEqual(projected.pending, [])
        self.state.pop_any_connection(self.h.onion)
        self.assertNotEqual(self.active(), generation)
        revoked = self.query()
        self.assertIsNone(revoked.continued_live_target)
        self.assertIsNone(revoked.continued_live_context_generation)
        other = self.h.other.request(
            GetRestrictedClientStateCommand(), RestrictedClientStateEvent
        )
        self.assertFalse(other.restricted)
        self.assertIsNone(other.continued_live_target)

    def test_authorized_recovery_preserves_grant_but_manual_call_does_not(self) -> None:
        """Logical recovery differs from a new call while the old peer identity is retained.

        Args:
            None
        Returns:
            None
        """
        from metor.core.api import ConnectionOrigin

        generation = self.active()
        self.h.client.request(
            RestrictClientCommand(
                continued_live_target=self.h.onion,
                live_while_locked=True,
                continued_live_context_generation=generation,
            ),
            ClientRestrictedEvent,
        )
        self.state.pop_any_connection(self.h.onion)
        self.state.mark_scheduled_auto_reconnect(self.h.onion)
        self.assertEqual(self.query().continued_live_context_generation, generation)
        self.state.clear_scheduled_auto_reconnect(self.h.onion)
        self.state.add_outbound_attempt(self.h.onion, ConnectionOrigin.MANUAL)
        self.assertIsNone(self.query().continued_live_target)

    def test_stale_foreground_hint_never_grants_a_later_call(self) -> None:
        """The peer identity alone cannot promote a replacement logical context at lock.

        Args:
            None
        Returns:
            None
        """
        original = self.active()
        self.state.pop_any_connection(self.h.onion)
        self.active()
        result = self.h.client.request(
            RestrictClientCommand(
                continued_live_target=self.h.onion,
                live_while_locked=True,
                continued_live_context_generation=original,
            ),
            ClientRestrictedEvent,
        )
        self.assertIsNone(result.continued_live_target)
        self.assertIsNone(self.query().continued_live_target)

    def test_anonymous_pending_refresh_contains_no_identity_or_classification(
        self,
    ) -> None:
        """Covered reconciliation can discover a current call without exposing its peer.

        Args:
            None
        Returns:
            None
        """
        from metor.core.api import ConnectionOrigin, PendingConnectionReasonCode
        from metor.core.daemon.managed.network.state import PendingConnectionReason

        local, remote = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(remote.close)
        self.state.add_pending_connection(
            self.h.onion,
            local,
            b'',
            reason=PendingConnectionReason.CONSUMER_ABSENT,
            expiry_deadline=time.time() + 20,
        )
        self.h.client.request(
            RestrictClientCommand(notification_privacy=NotificationPrivacy.ANONYMIZE),
            ClientRestrictedEvent,
        )
        pending = self.query().pending
        self.assertEqual(len(pending), 1)
        self.assertIsNone(pending[0].onion)
        self.assertEqual(pending[0].alias, 'unknown')
        self.assertEqual(pending[0].reason, PendingConnectionReasonCode.USER_ACCEPT)
        self.assertEqual(pending[0].origin, ConnectionOrigin.INCOMING)
        self.assertIsNotNone(pending[0].action_handle)
        self.assertNotIn(self.h.onion, self.query().to_json())
        from metor.core.api import InboxNotificationEvent, Delivery

        access = self.h.daemon._session_access
        recipient = next(iter(access._restricted))
        source = InboxNotificationEvent(
            'Secret Alias',
            self.h.onion,
            delivery=Delivery.DROP,
            source_id='secret-message-id',
        )
        projected = access.filter_restricted_event(recipient, source)
        self.assertEqual(projected.alias, 'unknown')
        self.assertIsNone(projected.onion)
        self.assertIsNone(projected.source_id)
        self.assertEqual(projected.delivery, Delivery.DROP)
        self.assertNotIn('Secret Alias', projected.to_json())
        self.assertEqual(source.alias, 'Secret Alias')

    def test_context_qualifier_is_strict(self) -> None:
        """Booleans, zero and negative qualifiers cannot become a logical context.

        Args:
            None
        Returns:
            None
        """
        for invalid in (True, 0, -1):
            with self.assertRaises(ValueError):
                RestrictClientCommand(continued_live_context_generation=invalid)


class ContinuedGuiTests(unittest.TestCase):
    """Exercises production GUI locking/capture against Core with a finite synthetic microphone."""

    def setUp(self) -> None:
        """Builds one eligible foreground with protected GUI preferences.

        Args:
            None
        Returns:
            None
        """
        from unittest.mock import Mock
        from metor.client import FrontendLaunchContext
        from metor.core.api import Delivery, GuiPreferences, GuiPreferencesEvent
        from metor.ui.gui.runtime import GuiController
        from metor.ui.gui.state import Route

        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        local, remote = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(remote.close)
        self.h.daemon._transport_state.add_active_connection(self.h.onion, local)
        self.gui = GuiController(
            FrontendLaunchContext(
                'voice-owned',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'voice-owned', True, False, False
                    )
                ),
            )
        )
        self.addCleanup(self.gui.close)
        self.gui.client = self.h.client
        self.gui.state.snapshot = self.h.client.runtime_snapshot()
        self.gui.state.capabilities = frozenset(self.h.client.init_event.capabilities)
        self.gui.voice_owner.token = self.h.owner
        self.gui.state.covered = False
        self.gui.state.route = Route('V09', self.h.onion, Delivery.LIVE)
        self.gui.state.preferences = GuiPreferencesEvent(
            self.gui.state.snapshot.profile_instance_id,
            preferences=GuiPreferences(
                keep_live_locked=True,
                unlock_method=ClientUnlockMethod.NONE,
                notifications_locked=NotificationPrivacy.OFF,
            ),
        )

    def lock(self) -> None:
        """Waits only for real same-client Core restriction confirmation.

        Args:
            None
        Returns:
            None
        """
        self.assertTrue(self.gui.security.lock())
        deadline = time.monotonic() + 5
        while self.gui.security.restriction is None and time.monotonic() < deadline:
            self.gui.poll()
            time.sleep(0.01)
        self.assertIsNotNone(self.gui.security.restriction)
        self.assertTrue(self.gui.state.covered)
        self.assertIsNone(self.gui.state.snapshot)

    def test_locked_capture_finalizes_accepted_prefix_without_drop_review(self) -> None:
        """The same public producer and exact context work with notifications Off.

        Args:
            None
        Returns:
            None
        """
        import threading
        from test_gui_capture import FiniteMicrophone
        from metor.core.api import Delivery
        from metor.ui.gui.runtime.voice import PressSource

        drained = threading.Event()
        microphone = FiniteMicrophone([b'\x00\x01' * 320])
        microphone.on_empty = drained.set
        self.gui.voice.configure(microphone, headset_confirmed=True)
        self.lock()
        self.assertIsNotNone(self.gui.security.continuation.scope)
        self.assertTrue(self.gui.voice.down(PressSource.PHYSICAL))
        binding = self.gui.voice.press.binding
        self.assertTrue(drained.wait(5))
        self.gui.voice.up(PressSource.PHYSICAL)
        self.assertTrue(self.gui.voice.worker.done.wait(10))
        self.gui.poll()
        turn = self.gui.voice.live_turns[binding.msg_id]
        self.assertTrue(turn.finalized)
        self.assertEqual(turn.size_bytes, 640)
        self.assertEqual(turn.actual_delivery, Delivery.LIVE)
        self.assertFalse(self.gui.voice.reviews)
        self.assertFalse(self.gui.calls.entries)
        self.assertTrue(microphone.stopped)

    def test_lock_from_settings_never_promotes_background_context(self) -> None:
        """The same preference cannot select a background LIVE peer implicitly.

        Args:
            None
        Returns:
            None
        """
        from metor.ui.gui.state import Route

        self.gui.state.route = Route('V17')
        self.lock()
        self.assertIsNone(self.gui.security.continuation.scope)
        self.assertIsNone(self.gui.security.continuation.requested)

    def test_core_maintenance_finishes_revoked_context_with_owner_still_connected(
        self,
    ) -> None:
        """A terminal context end freezes the accepted prefix without waiting for GUI detach.

        Args:
            None
        Returns:
            None
        """
        import base64
        import json
        from metor.core.api import Delivery
        from metor.data import MessageDirection, SettingKey

        generation = self.gui.state.snapshot.live_contexts[0].context_generation
        self.h.daemon._pm.config.set(SettingKey.FALLBACK_TO_DROP, False)
        self.h.client.begin_voice(
            self.h.onion,
            Delivery.LIVE,
            'revoked',
            'pcm_s16le_16000_mono',
            owner_token=self.h.owner,
            context_generation=generation,
        )
        self.h.client.append_voice(
            'revoked',
            0,
            base64.b64encode(b'\x00\x01' * 320).decode('ascii'),
            owner_token=self.h.owner,
        )
        self.h.daemon._transport_state.pop_any_connection(self.h.onion)
        self.h.daemon._command_dispatcher.retry_voice_cleanup()
        record = self.h.messages.get_voice_payload(
            self.h.onion, 'revoked', MessageDirection.OUT
        )
        self.assertEqual(json.loads(record.payload)['size_bytes'], 640)
        self.assertTrue(json.loads(record.payload)['finalized'])
        self.assertIsNone(self.h.repository.get('revoked'))
