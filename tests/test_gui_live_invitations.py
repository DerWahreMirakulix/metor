"""Exact LIVE invitation actions across replacement, privacy and normal unlock."""

import socket
import time
import unittest

import test_gui_producers as support
from metor.client import FrontendProfileState
from metor.core.api import (
    AcceptCommand,
    RejectCommand,
    ClientRestrictedEvent,
    ClientReauthorizedEvent,
    ClientUnlockMethod,
    RestrictClientCommand,
    ReauthorizeClientCommand,
    NotificationPrivacy,
    IncomingConnectionEvent,
    IpcEvent,
    ConnectionRejectedEvent,
    NoPendingConnectionEvent,
    ClientAccessRestrictedEvent,
)


class PendingInvitationCoreTests(unittest.TestCase):
    """Exercises actual encrypted Core IPC with controlled socket-pair requests."""

    def setUp(self) -> None:
        """Starts isolated authenticated clients and no external call or audio."""
        self.h = support.GuiProducerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.state = self.h.daemon._transport_state

    def pending(self) -> socket.socket:
        """Installs a new exact pending request with a bounded test lifetime."""
        local, remote = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(remote.close)
        self.state.add_pending_connection(
            self.h.onion, local, b'', expiry_deadline=time.time() + 20
        )
        return local

    def test_snapshot_handle_is_recipient_owned_and_replacement_safe(self) -> None:
        """A stale or cross-client handle cannot decline a new request from the same peer."""
        first = self.pending()
        a = self.h.client.runtime_snapshot().pending[0].action_handle
        b = self.h.other.runtime_snapshot().pending[0].action_handle
        self.assertIsNotNone(a)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, self.state.pending_token(self.h.onion))
        self.assertIsInstance(
            self.h.other.request(RejectCommand(self.h.onion, a), IpcEvent),
            NoPendingConnectionEvent,
        )
        self.assertIs(self.state.pending_identity(self.h.onion)[0], first)
        self.state.pop_pending_connection(self.h.onion)
        second = self.pending()
        self.assertIsInstance(
            self.h.client.request(AcceptCommand(self.h.onion, a), IpcEvent),
            NoPendingConnectionEvent,
        )
        self.assertIs(self.state.pending_identity(self.h.onion)[0], second)
        current = self.h.client.runtime_snapshot().pending[0].action_handle
        result = self.h.client.request(RejectCommand(self.h.onion, current), IpcEvent)
        self.assertIsInstance(result, ConnectionRejectedEvent)
        self.assertIsNone(self.state.pending_identity(self.h.onion))

    def test_anonymous_denial_keeps_decline_and_normal_unlock_request_identity(
        self,
    ) -> None:
        """Configured unlock preserves exact invitation selection without revealing identity early."""
        self.h.client.request(
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                notification_privacy=NotificationPrivacy.ANONYMIZE,
            ),
            ClientRestrictedEvent,
        )
        original = self.pending()
        access = self.h.daemon._session_access
        recipient = next(iter(access._restricted))
        event = IncomingConnectionEvent(
            'secret peer', self.h.onion, self.state.pending_token(self.h.onion)
        )
        projected = access.filter_restricted_event(recipient, event)
        self.assertIsNone(projected.onion)
        self.assertEqual(projected.alias, 'unknown')
        handle = projected.action_handle
        self.assertIsNone(handle)
        self.assertIsInstance(
            self.h.client.request(AcceptCommand(self.h.onion), IpcEvent),
            ClientAccessRestrictedEvent,
        )
        self.assertIs(self.state.pending_identity(self.h.onion)[0], original)
        self.h.client.request(
            ReauthorizeClientCommand(ClientUnlockMethod.NONE), ClientReauthorizedEvent
        )
        snapshot = self.h.client.runtime_snapshot()
        handle = snapshot.pending[0].action_handle
        self.assertIsNotNone(handle)
        self.assertEqual(snapshot.pending[0].onion, self.h.onion)
        self.assertIsInstance(
            self.h.client.request(RejectCommand(self.h.onion, handle), IpcEvent),
            ConnectionRejectedEvent,
        )

    def test_late_source_projection_never_mints_replacement_authority(self) -> None:
        """An event captured before replacement cannot gain the replacement socket's handle."""
        self.pending()
        old = IncomingConnectionEvent(
            'peer', self.h.onion, self.state.pending_token(self.h.onion)
        )
        self.state.pop_pending_connection(self.h.onion)
        self.pending()
        recipient = next(iter(self.h.daemon._session_access.authenticated_recipients()))
        projected = self.h.daemon._session_access.filter_restricted_event(
            recipient, old
        )
        self.assertIsNone(projected.action_handle)
        self.assertIsNotNone(self.h.client.runtime_snapshot().pending[0].action_handle)

    def test_accepted_handle_navigates_only_the_exact_live_context(self) -> None:
        """Positive acceptance is discoverable after unlock and revoked by a later invitation."""
        from unittest.mock import patch
        from metor.core.api import ConnectedEvent

        self.pending()
        handle = self.h.client.runtime_snapshot().pending[0].action_handle
        with patch.object(self.h.daemon._network._receiver, 'start_receiving'):
            result = self.h.client.request(
                AcceptCommand(self.h.onion, handle), IpcEvent
            )
        self.assertIsInstance(result, ConnectedEvent)
        live = self.h.client.runtime_snapshot().live_contexts[0]
        self.assertEqual(live.invitation_handle, handle)
        self.assertIsNone(
            self.h.other.runtime_snapshot().live_contexts[0].invitation_handle
        )
        self.state.pop_any_connection(self.h.onion)
        replacement, remote = socket.socketpair()
        self.addCleanup(replacement.close)
        self.addCleanup(remote.close)
        self.state.add_active_connection(self.h.onion, replacement)
        self.assertIsNone(
            self.h.client.runtime_snapshot().live_contexts[0].invitation_handle
        )

    def test_late_expiry_does_not_revoke_the_replacement_handle(self) -> None:
        """An expired old request cannot invalidate a newly projected request from that peer."""
        from metor.core.api import PendingConnectionExpiredEvent

        self.pending()
        old_handle = self.h.client.runtime_snapshot().pending[0].action_handle
        self.state.pop_pending_connection(self.h.onion)
        replacement = self.pending()
        current = self.h.client.runtime_snapshot().pending[0].action_handle
        access = self.h.daemon._session_access
        recipient = next(
            conn
            for conn, handles in access._invitation_handles.items()
            if current in handles
        )
        expiry = access.filter_restricted_event(
            recipient, PendingConnectionExpiredEvent('peer', self.h.onion)
        )
        self.assertNotEqual(expiry.action_handle, current)
        self.assertNotEqual(old_handle, current)
        self.assertIs(self.state.pending_identity(self.h.onion)[0], replacement)
        self.assertIsInstance(
            self.h.client.request(RejectCommand(self.h.onion, current), IpcEvent),
            ConnectionRejectedEvent,
        )

    def test_other_client_acceptance_preserves_only_the_observed_request(self) -> None:
        """A GUI can open the invitation it saw even when a different local client accepted it.

        Args:
            None
        Returns:
            None
        """
        from unittest.mock import patch
        from metor.core.api import ConnectedEvent

        self.pending()
        observed = self.h.client.runtime_snapshot().pending[0].action_handle
        other = self.h.other.runtime_snapshot().pending[0].action_handle
        with patch.object(self.h.daemon._network._receiver, 'start_receiving'):
            result = self.h.other.request(AcceptCommand(self.h.onion, other), IpcEvent)
        self.assertIsInstance(result, ConnectedEvent)
        self.assertEqual(
            self.h.client.runtime_snapshot().live_contexts[0].invitation_handle,
            observed,
        )
        self.assertEqual(
            self.h.other.runtime_snapshot().live_contexts[0].invitation_handle, other
        )
        self.assertIsInstance(
            self.h.client.request(RejectCommand(self.h.onion, observed), IpcEvent),
            NoPendingConnectionEvent,
        )


class InvitationPresentationTests(unittest.TestCase):
    """Tests explicit GUI intentions with DTOs, without socket or toolkit mocks as evidence."""

    def setUp(self) -> None:
        """Creates an inert GUI with a captured public command submission boundary."""
        from unittest.mock import Mock
        from metor.client import FrontendLaunchContext
        from metor.core.api import RuntimeSnapshotEvent
        from metor.ui.gui.runtime import GuiController
        from metor.ui.gui.state import Route

        self.gui = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture', True, False, False
                    )
                ),
            ),
            simulator=True,
        )
        self.gui.state.covered = False
        self.gui.state.route = Route('V08', 'alice')
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', 'self')
        self.gui.client = Mock()
        self.work = None
        self.operation = ''

        def submit(operation, work):
            self.operation, self.work = operation, work
            return True

        self.gui.submit = submit
        self.invitations = self.gui.live_invitations

    def snapshot(self, *, pending=(), accepted=()) -> None:
        """Publishes a fresh content-free snapshot through the public model."""
        from metor.core.api import RuntimeSnapshotEvent

        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', 'self', pending=list(pending), live_contexts=list(accepted)
        )
        self.invitations.poll()

    def test_incoming_waits_for_explicit_notification_or_sidebar_intent(self) -> None:
        """Arrival creates a reachable request without interrupting the current chat."""
        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.assertFalse(self.invitations.visible)
        self.assertTrue(self.invitations.show_peer('bob'))
        self.assertTrue(self.invitations.visible)
        self.assertEqual(self.invitations.presentation, 'chooser')
        self.assertEqual(self.gui.state.route.peer, 'alice')
        self.gui.client.request.assert_not_called()
        self.invitations.dismiss()
        self.invitations.show('one')
        self.assertEqual(self.invitations.presentation, 'banner')
        self.assertTrue(self.invitations.visible)
        self.gui.client.request.assert_not_called()

    def test_pending_sidebar_membership_ends_with_rejection(self) -> None:
        """Only explicit inbound invitation facts add pending sidebar rows."""
        from metor.core.api import (
            ConnectionOrigin,
            Delivery,
            PendingConnectionEntry,
            PendingConnectionReasonCode,
        )
        from metor.ui.gui.runtime import conversation_rows

        self.snapshot(
            pending=[
                PendingConnectionEntry(
                    'Bob',
                    'bob',
                    ConnectionOrigin.INCOMING,
                    PendingConnectionReasonCode.USER_ACCEPT,
                    action_handle='one',
                ),
                PendingConnectionEntry(
                    'Carol',
                    'carol',
                    ConnectionOrigin.GRACE_RECONNECT,
                    PendingConnectionReasonCode.CONSUMER_ABSENT,
                    action_handle='recovery',
                ),
            ]
        )
        self.assertFalse(self.invitations.visible)
        self.assertEqual(
            [item.peer for item in conversation_rows(self.gui, Delivery.LIVE)], ['bob']
        )
        self.snapshot()
        self.assertEqual(conversation_rows(self.gui, Delivery.LIVE), [])

    def test_ended_transcript_is_local_but_durable_pending_stays_reachable(
        self,
    ) -> None:
        """Ended metadata cannot restore cleared transcripts; pending receipts remain listed."""
        from metor.core.api import (
            Delivery,
            LiveContextEntry,
            MessageReceivedEvent,
            TextContent,
        )
        from metor.ui.gui.runtime import conversation_rows

        ended = LiveContextEntry(
            'Bob', 'bob', True, 'disconnected', context_generation=1
        )
        self.snapshot(accepted=[ended])
        self.assertEqual(conversation_rows(self.gui, Delivery.LIVE), [])
        self.gui.transcript.install(
            MessageReceivedEvent(
                'Bob',
                Delivery.LIVE,
                TextContent('kept'),
                onion='bob',
                msg_id='kept',
            )
        )
        self.assertEqual(
            [item.peer for item in conversation_rows(self.gui, Delivery.LIVE)], ['bob']
        )
        self.gui.transcript.discard('bob', Delivery.LIVE)
        self.assertEqual(conversation_rows(self.gui, Delivery.LIVE), [])
        ended.pending_outbound_count = 1
        self.snapshot(accepted=[ended])
        self.assertEqual(
            [item.peer for item in conversation_rows(self.gui, Delivery.LIVE)], ['bob']
        )

    def test_accept_stays_elsewhere_and_open_requires_current_accepted_handle(
        self,
    ) -> None:
        """Accept and Open are separate actions; neither issues an outgoing connection."""
        from metor.core.api import ConnectedEvent, LiveContextEntry, Delivery
        from metor.ui.gui.state import Route
        from metor.ui.gui.state.mailbox import Update

        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.assertTrue(self.invitations.perform('one', 'accept'))
        self.work()
        self.assertIsInstance(self.gui.client.request.call_args.args[0], AcceptCommand)
        self.invitations.install(
            Update(0, self.operation, ConnectedEvent('Bob', 'bob'))
        )
        live = LiveContextEntry(
            'Bob',
            'bob',
            True,
            'connected',
            context_generation=1,
            invitation_handle='one',
        )
        self.snapshot(accepted=[live])
        self.assertEqual(self.gui.state.route, Route('V08', 'alice'))
        self.assertFalse(self.invitations.visible)
        self.assertEqual(self.invitations.pending_handles(), ())
        self.assertTrue(self.invitations.perform('one', 'open'))
        self.assertEqual(self.gui.state.route, Route('V09', 'bob', Delivery.LIVE))
        self.assertEqual(self.gui.client.request.call_count, 1)

    def test_accept_and_open_navigates_on_exact_success_before_snapshot(self) -> None:
        """A successful explicit Open cannot depend on a second invitation refresh."""
        from metor.core.api import ConnectedEvent, Delivery
        from metor.ui.gui.state import Route
        from metor.ui.gui.state.mailbox import Update

        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.assertTrue(self.invitations.perform('one', 'open'))
        self.work()
        self.invitations.install(
            Update(0, self.operation, ConnectedEvent('Bob', 'bob'))
        )
        self.assertEqual(self.gui.state.route, Route('V09', 'bob', Delivery.LIVE))
        self.assertFalse(self.invitations.visible)
        self.assertEqual(self.invitations.pending_handles(), ())
        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.assertFalse(self.invitations.visible)
        self.assertEqual(self.gui.client.request.call_count, 1)

    def test_accept_retires_only_resolved_request_from_multiple_invitation_selector(
        self,
    ) -> None:
        """Already accepted chats never remain in the pending invitation pager."""
        from metor.core.api import ConnectedEvent
        from metor.ui.gui.state.mailbox import Update

        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.invitations.observe(IncomingConnectionEvent('Carol', 'carol', 'two'))
        self.assertTrue(self.invitations.perform('one', 'accept'))
        self.invitations.install(
            Update(0, self.operation, ConnectedEvent('Bob', 'bob'))
        )
        self.assertEqual(self.invitations.pending_handles(), ('two',))
        self.assertEqual(self.invitations.selected, 'two')

    def test_open_acceptance_preserves_a_later_explicit_navigation(self) -> None:
        """An asynchronous success cannot pull the user back after they leave."""
        from metor.core.api import ConnectedEvent
        from metor.ui.gui.state import Route
        from metor.ui.gui.state.mailbox import Update

        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.assertTrue(self.invitations.perform('one', 'open'))
        self.gui.state.route = Route('V12')
        self.invitations.install(
            Update(0, self.operation, ConnectedEvent('Bob', 'bob'))
        )
        self.assertEqual(self.gui.state.route, Route('V12'))
        self.assertFalse(self.invitations.visible)

    def test_unknown_open_requires_the_original_accepted_handle(self) -> None:
        """A lost response waits for exact acceptance rather than a replacement chat."""
        from metor.core.api import Delivery, LiveContextEntry
        from metor.ui.gui.state import Route
        from metor.ui.gui.state.mailbox import Update

        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.assertTrue(self.invitations.perform('one', 'open'))
        self.invitations.install(Update(0, self.operation))
        self.assertEqual(self.gui.state.route, Route('V08', 'alice'))
        self.snapshot(
            accepted=[
                LiveContextEntry(
                    'Bob',
                    'bob',
                    True,
                    'connected',
                    context_generation=1,
                    invitation_handle='one',
                )
            ]
        )
        self.assertEqual(self.gui.state.route, Route('V09', 'bob', Delivery.LIVE))
        self.assertFalse(self.invitations.visible)

    def test_multiple_invitation_arrival_preserves_target_and_expired_open_never_calls_back(
        self,
    ) -> None:
        """Arrival leaves the selected button's handle intact; stale Open is inert."""
        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.invitations.observe(IncomingConnectionEvent('Carol', 'carol', 'two'))
        self.assertEqual(self.invitations.selected, 'one')
        self.assertEqual(self.gui.state.route.peer, 'alice')
        self.assertTrue(self.invitations.perform('one', 'decline'))
        self.work()
        command = self.gui.client.request.call_args.args[0]
        self.assertEqual((command.target, command.action_handle), ('bob', 'one'))
        self.snapshot()
        self.assertFalse(self.invitations.perform('one', 'open'))
        self.assertEqual(self.gui.client.request.call_count, 1)

    def test_replaced_peer_request_has_one_prompt_and_old_controls_are_inert(
        self,
    ) -> None:
        """A new handle immediately retires the same peer's previous invitation."""
        from metor.core.api import PendingConnectionExpiredEvent

        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'old'))
        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'current'))
        self.assertEqual(self.invitations.pending_handles(), ('current',))
        self.assertEqual(self.invitations.selected, 'current')
        self.assertFalse(self.invitations.perform('old', 'accept'))
        self.invitations.observe(
            PendingConnectionExpiredEvent('Bob', 'bob', action_handle='old')
        )
        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'old'))
        self.assertEqual(self.invitations.pending_handles(), ('current',))
        self.assertTrue(self.invitations.perform('current', 'accept'))
        self.work()
        command = self.gui.client.request.call_args.args[0]
        self.assertEqual((command.target, command.action_handle), ('bob', 'current'))

    def test_older_snapshot_cannot_restore_a_replaced_prompt(self) -> None:
        """An in-flight earlier read cannot reverse a newer same-peer request event."""
        from metor.core.api import (
            ConnectionOrigin,
            PendingConnectionEntry,
            PendingConnectionReasonCode,
            RuntimeSnapshotEvent,
        )

        self.invitations.observe(
            IncomingConnectionEvent('Bob', 'bob', 'old', revision=1)
        )
        self.invitations.observe(
            IncomingConnectionEvent('Bob', 'bob', 'current', revision=2)
        )
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            'self',
            revision=1,
            pending=[
                PendingConnectionEntry(
                    'Bob',
                    'bob',
                    ConnectionOrigin.INCOMING,
                    PendingConnectionReasonCode.USER_ACCEPT,
                    action_handle='old',
                )
            ],
        )
        self.invitations.poll()
        self.assertEqual(self.invitations.pending_handles(), ('current',))
        self.assertEqual(self.invitations.selected, 'current')
        self.assertFalse(self.invitations.perform('old', 'open'))

    def test_replacement_preserves_inflight_action_without_reviving_its_prompt(
        self,
    ) -> None:
        """The old action result resolves only its handle, leaving the new request current."""
        from metor.ui.gui.state.mailbox import Update

        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'old'))
        self.assertTrue(self.invitations.perform('old', 'accept'))
        original_operation = self.operation
        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'current'))
        self.assertEqual(self.invitations._operation[1], 'old')
        self.invitations.install(
            Update(0, original_operation, ConnectionRejectedEvent('Bob', 'bob'))
        )
        self.assertEqual(self.invitations.entries['old'].phase, 'replaced')
        self.assertEqual(self.invitations.pending_handles(), ('current',))
        self.assertTrue(self.invitations.perform('current', 'accept'))
        self.work()
        self.assertEqual(
            self.gui.client.request.call_args.args[0].action_handle, 'current'
        )

    def test_replaced_open_success_cannot_navigate_or_hide_the_current_request(
        self,
    ) -> None:
        """A late old success cannot change the replacement request's chosen surface."""
        from metor.core.api import ConnectedEvent
        from metor.ui.gui.state.mailbox import Update

        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'old'))
        self.assertTrue(self.invitations.perform('old', 'open'))
        operation = self.operation
        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'current'))
        self.invitations.show('current')
        origin = self.gui.state.route
        self.invitations.install(Update(0, operation, ConnectedEvent('Bob', 'bob')))
        self.assertEqual(self.gui.state.route, origin)
        self.assertTrue(self.invitations.visible)
        self.assertEqual(self.invitations.selected, 'current')
        self.assertEqual(self.invitations.entries['old'].phase, 'replaced')

    def test_late_duplicate_result_preserves_the_current_action(self) -> None:
        """An unrelated old operation result never steals a newer request's correlation."""
        from metor.ui.gui.state.mailbox import Update

        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'old'))
        self.assertTrue(self.invitations.perform('old', 'accept'))
        original = self.operation
        self.invitations.observe(IncomingConnectionEvent('Carol', 'carol', 'current'))
        self.invitations.install(
            Update(0, original, ConnectionRejectedEvent('Bob', 'bob'))
        )
        self.assertTrue(self.invitations.perform('current', 'accept'))
        current = self.invitations._operation
        self.invitations.install(
            Update(0, original, ConnectionRejectedEvent('Bob', 'bob'))
        )
        self.assertEqual(self.invitations._operation, current)

    def test_anonymous_labels_do_not_coalesce_distinct_peer_authority(self) -> None:
        """A shared anonymous label is never treated as a canonical peer identity."""
        self.invitations.observe(
            IncomingConnectionEvent('Live chat invitation', None, 'a')
        )
        self.invitations.observe(
            IncomingConnectionEvent('Live chat invitation', None, 'b')
        )
        self.assertEqual(self.invitations.pending_handles(), ('a', 'b'))

    def test_recovery_snapshot_does_not_reopen_dismissed_invitation_surface(
        self,
    ) -> None:
        """Transport recovery remains outside the pending invitation presentation."""
        from metor.core.api import (
            ConnectionOrigin,
            PendingConnectionEntry,
            PendingConnectionReasonCode,
        )

        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.invitations.dismiss()
        self.snapshot(
            pending=[
                PendingConnectionEntry(
                    'Bob',
                    'bob',
                    ConnectionOrigin.GRACE_RECONNECT,
                    PendingConnectionReasonCode.CONSUMER_ABSENT,
                    action_handle='recovery',
                )
            ]
        )
        self.assertFalse(self.invitations.visible)
        self.assertIsNone(self.invitations.selected)
        self.assertNotIn('recovery', self.invitations.entries)
        self.invitations.show()
        self.assertFalse(self.invitations.visible)

    def test_ended_invitations_are_skipped_and_cannot_reopen_the_surface(self) -> None:
        """Expired history never remains as a close-only LIVE invitation page."""
        self.invitations.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.snapshot()
        self.assertFalse(self.invitations.visible)
        self.invitations.show('one')
        self.assertFalse(self.invitations.visible)
        self.invitations.observe(IncomingConnectionEvent('Carol', 'carol', 'two'))
        self.assertEqual(self.invitations.selected, 'two')
        self.invitations.show('one')
        self.assertFalse(self.invitations.visible)
        self.invitations.show('two')
        self.assertTrue(self.invitations.visible)
        self.invitations.step(-1)
        self.assertEqual(self.invitations.selected, 'two')

    def test_locked_off_and_anonymize_sanitize_before_retaining_invitation_metadata(
        self,
    ) -> None:
        """Even a delayed event cannot inject identity into an anonymous covered surface."""
        from dataclasses import replace

        self.gui.state.covered = True
        security = self.gui.security
        security.restriction = ClientRestrictedEvent(ClientUnlockMethod.NONE)
        security._policy = replace(
            security._policy, notifications_locked=NotificationPrivacy.OFF
        )
        self.invitations.observe(
            IncomingConnectionEvent('Private Alias', 'private-peer', 'one')
        )
        self.assertFalse(self.invitations.entries)
        security._policy = replace(
            security._policy, notifications_locked=NotificationPrivacy.ANONYMIZE
        )
        self.invitations.observe(
            IncomingConnectionEvent('Private Alias', 'private-peer', 'two')
        )
        self.assertFalse(self.invitations.entries)
        self.assertFalse(self.invitations.perform('two', 'open'))
        self.assertIsNone(self.work)
