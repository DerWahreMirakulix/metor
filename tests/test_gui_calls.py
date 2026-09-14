"""Exact incoming-call actions across replacement, privacy and normal unlock."""

import socket
import time
import unittest

import test_gui_producers as support
from metor.core.api import (
    AcceptCommand,
    RejectCommand,
    ClientRestrictedEvent,
    ClientReauthorizedEvent,
    ClientUnlockMethod,
    RestrictClientCommand,
    ReauthorizeClientCommand,
    NotificationPrivacy,
    LockedAcceptPolicy,
    IncomingConnectionEvent,
    IpcEvent,
    ConnectionRejectedEvent,
    NoPendingConnectionEvent,
    ClientAccessRestrictedEvent,
)


class PendingCallCoreTests(unittest.TestCase):
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
        """Configured unlock preserves exact call selection without revealing identity early."""
        self.h.client.request(
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                notification_privacy=NotificationPrivacy.ANONYMIZE,
                accept_while_locked=LockedAcceptPolicy.NONE,
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
        self.assertIsNotNone(handle)
        self.assertIsInstance(
            self.h.client.request(AcceptCommand(handle, handle), IpcEvent),
            ClientAccessRestrictedEvent,
        )
        self.assertIs(self.state.pending_identity(self.h.onion)[0], original)
        self.h.client.request(
            ReauthorizeClientCommand(ClientUnlockMethod.NONE), ClientReauthorizedEvent
        )
        snapshot = self.h.client.runtime_snapshot()
        self.assertEqual(snapshot.pending[0].action_handle, handle)
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
        """Positive acceptance is discoverable after unlock and revoked by a later call."""
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
        self.assertEqual(live.call_handle, handle)
        self.assertIsNone(self.h.other.runtime_snapshot().live_contexts[0].call_handle)
        self.state.pop_any_connection(self.h.onion)
        replacement, remote = socket.socketpair()
        self.addCleanup(replacement.close)
        self.addCleanup(remote.close)
        self.state.add_active_connection(self.h.onion, replacement)
        self.assertIsNone(self.h.client.runtime_snapshot().live_contexts[0].call_handle)

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
            conn for conn, handles in access._call_handles.items() if current in handles
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
        """A GUI can open the call it saw even when a different local client accepted it.

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
            self.h.client.runtime_snapshot().live_contexts[0].call_handle, observed
        )
        self.assertEqual(
            self.h.other.runtime_snapshot().live_contexts[0].call_handle, other
        )
        self.assertIsInstance(
            self.h.client.request(RejectCommand(self.h.onion, observed), IpcEvent),
            NoPendingConnectionEvent,
        )


class CallPresentationTests(unittest.TestCase):
    """Tests explicit GUI intentions with DTOs, without socket or toolkit mocks as evidence."""

    def setUp(self) -> None:
        """Creates an inert GUI with a captured public command submission boundary."""
        from unittest.mock import Mock
        from metor.client import FrontendLaunchContext
        from metor.core.api import RuntimeSnapshotEvent
        from metor.ui.gui.runtime import GuiController
        from metor.ui.gui.state import Route

        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
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
        self.calls = self.gui.calls

    def snapshot(self, *, pending=(), accepted=()) -> None:
        """Publishes a fresh content-free snapshot through the public model."""
        from metor.core.api import RuntimeSnapshotEvent

        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', 'self', pending=list(pending), live_contexts=list(accepted)
        )
        self.calls.poll()

    def test_accept_stays_elsewhere_and_open_requires_current_accepted_handle(
        self,
    ) -> None:
        """Accept and Open are separate actions; neither issues an outgoing call."""
        from metor.core.api import ConnectedEvent, LiveContextEntry, Delivery
        from metor.ui.gui.state import Route
        from metor.ui.gui.state.mailbox import Update

        self.calls.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.assertTrue(self.calls.perform('one', 'accept'))
        self.work()
        self.assertIsInstance(self.gui.client.request.call_args.args[0], AcceptCommand)
        self.calls.install(Update(0, self.operation, ConnectedEvent('Bob', 'bob')))
        live = LiveContextEntry(
            'Bob', 'bob', True, 'connected', context_generation=1, call_handle='one'
        )
        self.snapshot(accepted=[live])
        self.assertEqual(self.gui.state.route, Route('V08', 'alice'))
        self.assertTrue(self.calls.perform('one', 'open'))
        self.snapshot(accepted=[live])
        self.assertEqual(self.gui.state.route, Route('V09', 'bob', Delivery.LIVE))
        self.assertEqual(self.gui.client.request.call_count, 1)

    def test_multiple_call_arrival_preserves_target_and_expired_open_never_calls_back(
        self,
    ) -> None:
        """Arrival leaves the selected button's handle intact; stale Open is inert."""
        self.calls.observe(IncomingConnectionEvent('Bob', 'bob', 'one'))
        self.calls.observe(IncomingConnectionEvent('Carol', 'carol', 'two'))
        self.assertEqual(self.calls.selected, 'one')
        self.assertEqual(self.gui.state.route.peer, 'alice')
        self.assertTrue(self.calls.perform('one', 'decline'))
        self.work()
        command = self.gui.client.request.call_args.args[0]
        self.assertEqual((command.target, command.action_handle), ('bob', 'one'))
        self.snapshot()
        self.assertFalse(self.calls.perform('one', 'open'))
        self.assertEqual(self.gui.client.request.call_count, 1)

    def test_locked_off_and_anonymize_sanitize_before_retaining_call_metadata(
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
        self.calls.observe(
            IncomingConnectionEvent('Private Alias', 'private-peer', 'one')
        )
        self.assertFalse(self.calls.entries)
        security._policy = replace(
            security._policy, notifications_locked=NotificationPrivacy.ANONYMIZE
        )
        self.calls.observe(
            IncomingConnectionEvent('Private Alias', 'private-peer', 'two')
        )
        entry = self.calls.entries['two']
        self.assertIsNone(entry.peer)
        self.assertEqual(entry.label, 'Incoming Live')
        self.assertTrue(self.calls.perform('two', 'open'))
        self.assertIsNone(self.work)
        self.assertIn('Unlock', self.gui.state.status)
