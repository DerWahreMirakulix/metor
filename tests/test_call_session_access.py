"""Exact Call consent and lock-cycle authorization using real Core state owners."""

import socket
import threading
import unittest
from typing import cast
from unittest.mock import Mock, patch

from metor.core.api import (
    AcceptCallCommand,
    AcceptCommand,
    BeginVoiceCommand,
    CallInfo,
    CallReason,
    CallState,
    CallStateEvent,
    ClientUnlockMethod,
    ClientRestrictedEvent,
    Delivery,
    GetContactsListCommand,
    HangupCallCommand,
    IpcCommand,
    IpcEvent,
    MuteCallCommand,
    NotificationPrivacy,
    ReadCallAudioCommand,
    RestrictClientCommand,
    SendCallAudioCommand,
    StartCallCommand,
)
from metor.core.daemon.managed.engine.session_access import SessionAccessController
from metor.core.daemon.managed.network.calls import CallController
from metor.core.daemon.managed.network.calls.models import CallSession


class CallSessionAccessTests(unittest.TestCase):
    """Exercises actual authorization/projection without opening audio or network sockets."""

    def setUp(self) -> None:
        """Creates an isolated Call owner with its monitor intentionally controlled."""
        self.client = cast(socket.socket, object())
        self.other = cast(socket.socket, object())
        self.sent: list[IpcEvent] = []
        with patch('threading.Thread.start'):
            self.calls = CallController(
                Mock(), Mock(), Mock(), Mock(), lambda _event: None, threading.Event()
            )
        self.addCleanup(self.calls.close)
        self.protected_acceptance = False
        self.access = SessionAccessController(
            require_auth=False,
            send_callback=lambda _conn, event: self.sent.append(event),
            lockout_timeout_callback=lambda: 30.0,
            failure_limit_callback=lambda: 3,
            live_consumer_available_callback=lambda: None,
            call_lock_acceptance_callback=lambda: self.protected_acceptance,
            call_authorization_callback=self.calls.authorize_call,
            call_event_projection_callback=self.calls.project_event,
        )
        self.access.mark_authenticated(self.client)
        self.access.mark_authenticated(self.other)

    def _add(self, call_id: str, state: CallState, *, owned: bool) -> CallSession:
        """Installs one exact Core-owned session, never inferred from peer identity."""
        session = CallSession(
            CallInfo(call_id=call_id, peer='alice-onion', alias='Alice', state=state),
            owner=self.client if owned else None,
        )
        self.calls.sessions[call_id] = session
        return session

    def _media(self, call_id: str) -> tuple[IpcCommand, ...]:
        """Returns every restricted continuing audio/control operation to inspect."""
        return (
            ReadCallAudioCommand(call_id=call_id),
            SendCallAudioCommand(call_id=call_id, sequence=0, data='YQ=='),
            MuteCallCommand(call_id=call_id, muted=True),
            HangupCallCommand(call_id=call_id),
        )

    def test_owned_accepted_call_continues_without_chat_or_message_rights(self) -> None:
        """The exact already accepted call survives app-lock, including its mute state."""
        session = self._add('accepted', CallState.ACTIVE, owned=True)
        session.info.muted = True
        self.access.restrict(self.client, RestrictClientCommand())
        for command in self._media('accepted'):
            with self.subTest(command=command.command_type):
                self.assertTrue(self.access.authorize(command, self.client, True))
        for command in (
            GetContactsListCommand(),
            AcceptCommand('alice'),
            StartCallCommand(target='alice', call_id='new'),
            AcceptCallCommand(call_id='new'),
            BeginVoiceCommand('alice', Delivery.LIVE, 'voice', 'opus'),
            BeginVoiceCommand('alice', Delivery.DROP, 'voice', 'opus'),
        ):
            with self.subTest(command=command.command_type):
                self.assertFalse(self.access.authorize(command, self.client, True))
        self.assertTrue(session.info.muted)
        self.access.restrict(self.other, RestrictClientCommand())
        for command in self._media('accepted'):
            self.assertFalse(self.access.authorize(command, self.other, True))

    def test_end_destroys_media_permission_for_same_peer_and_later_call(self) -> None:
        """A retained identity cannot authorize a terminal or replacement conversation."""
        old = self._add('old', CallState.ACTIVE, owned=True)
        self.access.restrict(self.client, RestrictClientCommand())
        self.calls.finish(old, CallReason.HUNG_UP)
        self._add('next', CallState.INCOMING, owned=False)
        for call_id in ('old', 'next', 'unknown'):
            for command in self._media(call_id):
                self.assertFalse(self.access.authorize(command, self.client, True))
        self.assertFalse(
            self.access.authorize(AcceptCallCommand(call_id='next'), self.client, True)
        )

    def test_locked_acceptance_is_an_explicit_call_only_policy(self) -> None:
        """Enabling new Call acceptance creates neither LIVE nor message media rights."""
        self._add('incoming', CallState.INCOMING, owned=False)
        self.protected_acceptance = True
        self.access.restrict(
            self.client,
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE, accept_calls_locked=True
            ),
        )
        self.assertTrue(
            self.access.authorize(
                AcceptCallCommand(call_id='incoming'), self.client, True
            )
        )
        self.assertFalse(
            self.access.authorize(AcceptCommand('alice'), self.client, True)
        )
        for command in self._media('incoming'):
            self.assertFalse(self.access.authorize(command, self.client, True))
        self.assertFalse(
            self.access.authorize(
                BeginVoiceCommand('alice', Delivery.LIVE, 'voice', 'opus'),
                self.client,
                True,
            )
        )

    def test_caller_cannot_enable_locked_acceptance_without_protected_policy(
        self,
    ) -> None:
        """A permissive restriction request is bounded by protected policy and prior auth."""
        self._add('incoming', CallState.INCOMING, owned=False)
        command = AcceptCallCommand(call_id='incoming')
        result = self.access.restrict(
            self.client, RestrictClientCommand(accept_calls_locked=True)
        )
        assert isinstance(result, ClientRestrictedEvent)
        self.assertFalse(result.accept_calls_locked)
        self.assertFalse(self.access.authorize(command, self.client, True))
        self.protected_acceptance = True
        result = self.access.restrict(
            self.client, RestrictClientCommand(accept_calls_locked=True)
        )
        assert isinstance(result, ClientRestrictedEvent)
        self.assertTrue(result.accept_calls_locked)
        self.assertTrue(self.access.authorize(command, self.client, True))
        self.protected_acceptance = False
        # The approved cycle is immutable; a later cycle re-evaluates Core policy.
        self.assertTrue(self.access.authorize(command, self.client, True))
        self.access.restrict(
            self.client, RestrictClientCommand(accept_calls_locked=True)
        )
        self.assertFalse(self.access.authorize(command, self.client, True))
        anonymous = cast(socket.socket, object())
        self.protected_acceptance = True
        self.access.restrict(anonymous, RestrictClientCommand(accept_calls_locked=True))
        self.assertFalse(self.access.authorize(command, anonymous, True))

    def test_privacy_masks_identity_and_preserves_only_owned_terminal_signal_when_off(
        self,
    ) -> None:
        """Content-free state uses recipient ownership even when original event owned is false."""
        session = self._add('owned', CallState.ACTIVE, owned=True)
        incoming = self._add('incoming', CallState.INCOMING, owned=False)
        self.access.restrict(
            self.client,
            RestrictClientCommand(notification_privacy=NotificationPrivacy.OFF),
        )
        event = CallStateEvent(call=session.info)
        projected = self.access.filter_restricted_event(self.client, event)
        self.assertIsInstance(projected, CallStateEvent)
        assert isinstance(projected, CallStateEvent)
        self.assertTrue(projected.call.owned)
        self.assertEqual((projected.call.peer, projected.call.alias), ('', ''))
        self.assertEqual(session.info.peer, 'alice-onion')
        self.assertIsNone(
            self.access.filter_restricted_event(
                self.client, CallStateEvent(call=incoming.info)
            )
        )
        self.calls.finish(session, CallReason.TRANSPORT_LOST)
        terminal = self.access.filter_restricted_event(self.client, event)
        assert isinstance(terminal, CallStateEvent)
        self.assertEqual(terminal.call.state, CallState.ENDED)
        self.assertTrue(terminal.call.owned)
        listed = self.calls.list_for_client(self.client, NotificationPrivacy.OFF)
        self.assertEqual([entry.call_id for entry in listed], ['owned'])
        self.assertEqual((listed[0].peer, listed[0].alias), ('', ''))

    def test_obsolete_restriction_permissions_fail_strict_wire_decoding(self) -> None:
        """The incompatible API cannot silently revive former locked LIVE authority."""
        for name, value in (
            ('live_while_locked', True),
            ('continued_live_target', 'alice'),
            ('accept_while_locked', 'all'),
        ):
            with self.subTest(name=name), self.assertRaises(TypeError):
                IpcCommand.from_dict({'command_type': 'restrict_client', name: value})
