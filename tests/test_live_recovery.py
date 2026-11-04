"""Bounded accepted LIVE recovery, consent and exact lifecycle race regressions."""

import socket
import threading
import unittest
from typing import cast
from unittest.mock import Mock, patch

from metor.core.api import ConnectionOrigin, DisconnectedEvent, IncomingConnectionEvent
from metor.core.daemon.managed.crypto import Crypto
from metor.core.daemon.managed.models import RejectIntent
from metor.core.daemon.managed.network.controller import ConnectionController
from metor.core.daemon.managed.network.controller.session.recovery import (
    _expire_accepted_recovery,
)
from metor.core.daemon.managed.network.listener import InboundListener
from metor.core.daemon.managed.network import NetworkManager
from metor.core.daemon.managed.network.handshake import HandshakeProtocol
from metor.core.daemon.managed.network.receiver import StreamReceiver
from metor.core.daemon.managed.network.router import MessageRouter
from metor.core.daemon.managed.network.state import (
    PendingConnectionReason,
    StateTracker,
)
from metor.core.daemon.managed.network.stream import TcpStreamReader
from metor.core.tor import TorManager
from metor.data import ContactManager, HistoryManager, MessageManager, SettingKey
from metor.data.profile import Config
from metor.utils import Constants


class _PeerSocket:
    """Records complete frames without starting a physical writer thread."""

    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.closed = False

    def sendall(self, frame: bytes) -> None:
        """Collects one bounded serialized frame."""
        self.frames.append(frame)

    def shutdown(self, how: int) -> None:
        """Implements socket retirement without physical I/O."""
        del how

    def close(self) -> None:
        """Records exact ownership retirement."""
        self.closed = True


class LiveRecoveryTests(unittest.TestCase):
    """Exercise production controller/listener boundaries with controlled clocks."""

    def setUp(self) -> None:
        """Builds one real state/controller and bounds all spawned test work."""
        self.state = StateTracker()
        self.stop = threading.Event()
        self.addCleanup(self.state.abort_all_sockets)
        self.addCleanup(self.stop.set)
        self.config = Mock()
        self.settings = {
            SettingKey.MAX_CONCURRENT_CONNECTIONS: 32,
            SettingKey.MAX_CONNECT_RETRIES: 0,
            SettingKey.LIVE_RECONNECT_DELAY: 15,
            SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT: 15,
            SettingKey.MAX_UNSEEN_LIVE_MSGS: -1,
        }
        self.config.get_int.side_effect = lambda key: self.settings.get(key, 0)
        self.config.get_float.return_value = 10.0
        self.config.get_bool.side_effect = lambda key: (
            key is SettingKey.FALLBACK_TO_DROP
        )
        self.contacts = Mock()
        self.contacts.resolve_target.return_value = ('Peer', 'peer')
        self.contacts.resolve_target_for_interaction.return_value = ('Peer', 'peer')
        self.contacts.ensure_alias_for_onion.return_value = 'Peer'
        self.contacts.get_all_contacts.return_value = []
        self.contacts.cleanup_orphans.return_value = []
        self.tor = Mock()
        self.tor.onion = 'self'
        self.history = Mock()
        self.messages = Mock()
        self.messages.get_pending_live_outbox.return_value = []
        self.router = Mock()
        self.events: list[object] = []
        with patch(
            'metor.core.daemon.managed.network.controller.base.threading.Thread'
        ):
            self.controller = ConnectionController(
                cast(TorManager, self.tor),
                cast(ContactManager, self.contacts),
                cast(HistoryManager, self.history),
                cast(MessageManager, self.messages),
                cast(Crypto, Mock()),
                self.state,
                cast(MessageRouter, self.router),
                self.events.append,
                lambda: True,
                self.stop,
                cast(Config, self.config),
            )
        self.receiver = Mock()
        self.controller.set_receiver(cast(StreamReceiver, self.receiver))
        fallback_patch = patch.object(
            self.controller, '_convert_unacked_live_to_drops', return_value=True
        )
        self.fallback = fallback_patch.start()
        self.addCleanup(fallback_patch.stop)

    def active(self) -> tuple[_PeerSocket, int]:
        """Creates an independently accepted logical context."""
        conn = _PeerSocket()
        self.assertTrue(
            self.state.add_active_connection('peer', cast(socket.socket, conn))
        )
        generation = self.state.get_live_context_generation('peer')
        assert generation is not None
        return conn, generation

    def lose(self, conn: _PeerSocket) -> None:
        """Delivers transport loss while holding the expiry worker for explicit testing."""
        with patch(
            'metor.core.daemon.managed.network.controller.session.recovery.threading.Thread'
        ):
            self.controller.disconnect('peer', False, True, cast(socket.socket, conn))

    def listener(self) -> InboundListener:
        """Builds authenticated admission over the same canonical state."""
        return InboundListener(
            cast(TorManager, self.tor),
            cast(ContactManager, self.contacts),
            cast(HistoryManager, self.history),
            cast(Crypto, Mock()),
            self.state,
            cast(MessageRouter, self.router),
            cast(StreamReceiver, self.receiver),
            self.events.append,
            lambda: True,
            lambda: True,
            lambda _payload: None,
            self.controller._enqueue_live_reconnect,
            self.stop,
            cast(Config, self.config),
            operation_lock=self.controller._operation_lock,
        )

    def admit(self, conn: _PeerSocket, recover: bool = True) -> None:
        """Admits one candidate after the production authenticated handshake boundary."""
        stream = Mock()
        stream.get_buffer.return_value = b''
        with patch('metor.core.daemon.managed.network.listener.threading.Thread'):
            self.listener()._handle_live_incoming(
                cast(socket.socket, conn),
                cast(TcpStreamReader, stream),
                'peer',
                recover,
            )

    def test_default_retry_begins_inside_grace_and_keeps_context(self) -> None:
        """Default 15-second retry cannot wait past the 15-second consent deadline."""
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            delays: list[float] = []
            with (
                patch.object(
                    self.controller,
                    '_sleep_live_reconnect_delay',
                    side_effect=delays.append,
                ),
                patch(
                    'metor.core.daemon.managed.network.controller.reconnect.time.sleep'
                ),
                patch.object(
                    self.controller,
                    'connect_to',
                    side_effect=lambda *args, **kwargs: self.stop.set(),
                ) as connect,
            ):
                self.controller._live_reconnect_worker()
            self.assertEqual(delays, [5.0])
            connect.assert_called_once_with(
                'peer',
                origin=ConnectionOrigin.AUTO_RECONNECT,
                expected_context_generation=generation,
            )
        self.assertTrue(conn.closed)
        self.assertFalse(
            any(isinstance(event, DisconnectedEvent) for event in self.events)
        )
        self.fallback.assert_not_called()

    def test_authenticated_recovery_inside_grace_autoaccepts_same_scope(self) -> None:
        """Recovery needs no new invitation and keeps drafts' logical ownership."""
        with patch('time.monotonic', return_value=100.0):
            old, generation = self.active()
            self.lose(old)
            new = _PeerSocket()
            self.admit(new)
            self.assertEqual(self.state.get_live_context_generation('peer'), generation)
            self.assertIsNone(self.state.accepted_live_recovery_deadline('peer'))
        self.assertEqual(new.frames, [b'/accepted\n'])
        self.assertFalse(
            any(isinstance(event, IncomingConnectionEvent) for event in self.events)
        )

    def test_grace_expiry_ends_scope_and_honors_fallback(self) -> None:
        """Grace expiry is permanent; no recovery hint can extend that consent."""
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            deadline = self.state.accepted_live_recovery_deadline('peer')
        assert deadline is not None
        with patch('time.monotonic', return_value=deadline):
            _expire_accepted_recovery(
                self.controller, 'Peer', 'peer', generation, deadline
            )
            self.admit(_PeerSocket())
        self.assertIsNone(self.state.accepted_live_context_generation('peer'))
        self.assertFalse(self.state.has_scheduled_auto_reconnect('peer'))
        self.fallback.assert_called_once_with('Peer', 'peer')
        self.assertEqual(
            sum(isinstance(event, DisconnectedEvent) for event in self.events), 1
        )
        self.assertFalse(self.state.is_connected_or_pending('peer'))

    def test_expiry_with_fallback_disabled_retains_pending_live(self) -> None:
        """Existing fallback=False leaves durable publication for explicit retry/fallback."""
        self.config.get_bool.return_value = False
        self.config.get_bool.side_effect = None
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.state.add_unacked_message('peer', 'message', 'content', 'timestamp')
            self.lose(conn)
            deadline = self.state.accepted_live_recovery_deadline('peer')
        assert deadline is not None
        with patch('time.monotonic', return_value=deadline):
            _expire_accepted_recovery(
                self.controller, 'Peer', 'peer', generation, deadline
            )
        self.fallback.assert_not_called()
        self.assertTrue(self.state.has_unacked_messages('peer'))

    def test_zero_retry_delay_disables_work_but_preserves_incoming_grace(self) -> None:
        """Automatic work remains opt-in through the existing setting."""
        self.settings[SettingKey.LIVE_RECONNECT_DELAY] = 0
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            self.assertFalse(self.state.has_scheduled_auto_reconnect('peer'))
            self.assertEqual(self.controller._live_reconnect_queue, [])
            self.admit(_PeerSocket())
            self.assertEqual(self.state.get_live_context_generation('peer'), generation)

    def test_repeated_failure_does_not_renew_grace(self) -> None:
        """Every retry shares the first loss deadline."""
        with patch('time.monotonic', return_value=100.0):
            conn, _generation = self.active()
            self.lose(conn)
            deadline = self.state.accepted_live_recovery_deadline('peer')
        self.tor.connect.side_effect = ConnectionError('unavailable')
        with patch('time.monotonic', return_value=110.0):
            self.controller.connect_to('peer', ConnectionOrigin.AUTO_RECONNECT)
        self.assertEqual(self.state.accepted_live_recovery_deadline('peer'), deadline)
        self.assertTrue(self.state.has_scheduled_auto_reconnect('peer'))
        self.fallback.assert_not_called()

    def test_old_timer_cannot_end_recovered_or_replacement_scope(self) -> None:
        """A recovered route and a later independent chat invalidate prior expiry work."""
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            deadline = self.state.accepted_live_recovery_deadline('peer')
            recovered = _PeerSocket()
            self.admit(recovered)
        assert deadline is not None
        with patch('time.monotonic', return_value=deadline):
            _expire_accepted_recovery(
                self.controller, 'Peer', 'peer', generation, deadline
            )
        self.assertIs(self.state.get_connection('peer'), recovered)
        self.fallback.assert_not_called()

    def test_explicit_end_fences_sleeping_recovery_and_late_peer_hint(self) -> None:
        """End revokes the exact logical context and prevents stale workers reopening it."""
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            self.assertTrue(
                self.controller.disconnect_qualified('peer', generation, None)
            )
            self.controller.connect_to(
                'peer',
                ConnectionOrigin.AUTO_RECONNECT,
                expected_context_generation=generation,
            )
            candidate = _PeerSocket()
            self.admit(candidate)
        self.tor.connect.assert_not_called()
        self.assertEqual(candidate.frames, [b'/reject manual self\n'])
        self.assertIsNone(self.state.accepted_live_context_generation('peer'))

    def test_remote_manual_end_during_retunnel_revokes_scope(self) -> None:
        """The accepted socket's old origin never turns a remote End into recovery."""
        conn, _generation = self.active()
        self.state.mark_retunnel_started('peer')
        self.controller.disconnect(
            'peer',
            False,
            False,
            cast(socket.socket, conn),
            origin=ConnectionOrigin.RETUNNEL,
        )
        self.assertIsNone(self.state.accepted_live_context_generation('peer'))
        self.assertFalse(self.state.is_retunneling('peer'))

    def test_remote_manual_reject_ends_recovering_scope(self) -> None:
        """An explicit peer rejection revokes recovery permission."""
        with patch('time.monotonic', return_value=100.0):
            conn, _generation = self.active()
            self.lose(conn)
            outbound = _PeerSocket()
            self.state.add_outbound_attempt('peer', ConnectionOrigin.AUTO_RECONNECT)
            self.state.bind_outbound_socket('peer', cast(socket.socket, outbound))
            self.controller.reject(
                'peer',
                False,
                cast(socket.socket, outbound),
                ConnectionOrigin.AUTO_RECONNECT,
                RejectIntent.MANUAL,
            )
        self.assertIsNone(self.state.accepted_live_context_generation('peer'))
        self.assertFalse(self.state.has_scheduled_auto_reconnect('peer'))

    def test_mutual_initial_connect_still_autoaccepts_without_recovery_scope(
        self,
    ) -> None:
        """Mutual user Connect grants consent independently of recovery permission."""
        self.state.add_outbound_attempt('peer')
        candidate = _PeerSocket()
        self.admit(candidate, False)
        self.assertEqual(candidate.frames, [b'/accepted\n'])
        self.assertIsNotNone(self.state.accepted_live_context_generation('peer'))
        self.assertFalse(
            any(isinstance(event, IncomingConnectionEvent) for event in self.events)
        )

    def test_unaccepted_recovery_hint_has_no_autoaccept_authority(self) -> None:
        """An authenticated RECOVER flag alone never supplies initial consent."""
        candidate = _PeerSocket()
        self.admit(candidate)
        self.assertEqual(candidate.frames, [b'/pending\n'])
        self.assertIsNone(self.state.accepted_live_context_generation('peer'))
        self.assertTrue(
            any(isinstance(event, IncomingConnectionEvent) for event in self.events)
        )

    def test_shutdown_clears_disconnected_scope_and_restart_does_not_restore_it(
        self,
    ) -> None:
        """Recovery permission stays volatile and terminates with the daemon."""
        with patch('time.monotonic', return_value=100.0):
            conn, _generation = self.active()
            self.lose(conn)
            deadline = self.state.accepted_live_recovery_deadline('peer')
        assert deadline is not None
        with patch('time.monotonic', return_value=deadline):
            self.stop.set()
            self.controller.disconnect_all()
        self.assertIsNone(self.state.accepted_live_context_generation('peer'))
        self.assertFalse(self.state.has_unrevoked_live_context('peer'))
        self.assertIsNone(StateTracker().accepted_live_context_generation('peer'))

    def test_cancelled_outbound_socket_cannot_admit_a_late_acceptance(self) -> None:
        """A peer acceptance received after exact Cancel cannot recreate a context."""
        local, remote = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(remote.close)
        self.state.add_outbound_attempt('peer')
        self.state.bind_outbound_socket('peer', local)
        self.state.pop_outbound_socket('peer')
        receiver = StreamReceiver(
            cast(ContactManager, self.contacts),
            cast(HistoryManager, self.history),
            self.state,
            cast(MessageRouter, self.router),
            self.events.append,
            self.controller.disconnect,
            self.controller.reject,
            cast(Config, self.config),
        )
        receiver._receiver_target('peer', local, b'/accepted\n', True)
        self.assertIsNone(self.state.get_connection('peer'))
        self.assertIsNone(self.state.accepted_live_context_generation('peer'))
        self.assertEqual(self.events, [])

    def test_deferred_consumer_acceptance_cannot_extend_expired_grace(self) -> None:
        """An expired recovery candidate never becomes a fresh accepted conversation."""
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            candidate = _PeerSocket()
            self.state.add_pending_connection(
                'peer',
                cast(socket.socket, candidate),
                b'',
                PendingConnectionReason.CONSUMER_ABSENT,
                ConnectionOrigin.GRACE_RECONNECT,
                expected_context_generation=generation,
            )
            deadline = self.state.accepted_live_recovery_deadline('peer')
        assert deadline is not None
        with patch('time.monotonic', return_value=deadline):
            self.controller.accept('peer', ConnectionOrigin.GRACE_RECONNECT)
        self.assertTrue(candidate.closed)
        self.assertEqual(candidate.frames, [])
        self.assertIsNone(self.state.accepted_live_context_generation('peer'))
        self.assertIsNone(self.state.get_connection('peer'))

    def test_expired_outbound_receiver_cannot_reschedule_legacy_recovery(self) -> None:
        """Retired waiting transport cleanup stays inert after terminal grace expiry."""
        local, remote = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(remote.close)
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            self.state.add_outbound_attempt('peer', ConnectionOrigin.AUTO_RECONNECT)
            self.state.bind_outbound_socket('peer', local)
            deadline = self.state.accepted_live_recovery_deadline('peer')
        assert deadline is not None
        with patch('time.monotonic', return_value=deadline):
            _expire_accepted_recovery(
                self.controller, 'Peer', 'peer', generation, deadline
            )
            event_count = len(self.events)
            receiver = StreamReceiver(
                cast(ContactManager, self.contacts),
                cast(HistoryManager, self.history),
                self.state,
                cast(MessageRouter, self.router),
                self.events.append,
                self.controller.disconnect,
                self.controller.reject,
                cast(Config, self.config),
            )
            receiver._receiver_target(
                'peer', local, b'', True, ConnectionOrigin.AUTO_RECONNECT
            )
        self.assertEqual(len(self.events), event_count)
        self.assertFalse(self.state.has_live_reconnect_grace('peer'))
        self.assertFalse(self.state.has_scheduled_auto_reconnect('peer'))

    def test_fresh_manual_attempt_after_grace_survives_old_timer(self) -> None:
        """Explicit Retry finalizes an expired scope before admitting its new attempt."""
        local, remote = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(remote.close)
        remote.sendall(
            HandshakeProtocol.build_challenge_line(
                '11' * Constants.TOR_HANDSHAKE_CHALLENGE_BYTES
            ).encode()
        )
        self.tor.connect.return_value = local
        cast(Mock, self.controller._crypto).sign_challenge.return_value = 'signature'
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            deadline = self.state.accepted_live_recovery_deadline('peer')
        assert deadline is not None
        with patch('time.monotonic', return_value=deadline):
            self.controller.connect_to('peer')
            attempt_id = self.state.get_outbound_attempt_id('peer')
            _expire_accepted_recovery(
                self.controller, 'Peer', 'peer', generation, deadline
            )
        self.assertIsNotNone(attempt_id)
        self.assertEqual(self.state.get_outbound_attempt_id('peer'), attempt_id)
        self.assertTrue(self.state.is_current_outbound_socket('peer', local))
        self.receiver.start_receiving.assert_called_once()

    def test_dismissal_waits_for_expired_scope_cleanup_and_never_resurrects(
        self,
    ) -> None:
        """An elapsed zero-retry scope still fences removal until terminal cleanup commits."""
        self.settings[SettingKey.LIVE_RECONNECT_DELAY] = 0
        network = NetworkManager.__new__(NetworkManager)
        network._state = self.state
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            deadline = self.state.accepted_live_recovery_deadline('peer')
        assert deadline is not None
        with patch('time.monotonic', return_value=deadline):
            self.state.mark_live_reconnect_grace('peer', 0.0)
            self.assertIsNone(self.state.accepted_live_context_generation('peer'))
            self.assertTrue(network.is_connected_or_recovering('peer'))
            self.assertFalse(self.state.forget_ended_live_context('peer'))
            _expire_accepted_recovery(
                self.controller, 'Peer', 'peer', generation, deadline
            )
            self.assertFalse(network.is_connected_or_recovering('peer'))
            self.assertTrue(self.state.forget_ended_live_context('peer'))
            event_count = len(self.events)
            _expire_accepted_recovery(
                self.controller, 'Peer', 'peer', generation, deadline
            )
        self.assertIsNone(self.state.known_live_context_generation('peer'))
        self.assertEqual(len(self.events), event_count)

    def test_consumer_callback_cannot_accept_replaced_user_invitation(self) -> None:
        """A deferred callback cannot apply old consent to a new request from the peer."""
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            old, replacement = _PeerSocket(), _PeerSocket()
            self.state.add_pending_connection(
                'peer',
                cast(socket.socket, old),
                b'',
                PendingConnectionReason.CONSUMER_ABSENT,
                ConnectionOrigin.GRACE_RECONNECT,
                expected_context_generation=generation,
            )

            def replace_during_alias_lookup(_onion: str) -> str:
                """Installs a fresh invitation at the enclosing callback's I/O boundary."""
                self.state.pop_pending_connection('peer')
                self.state.revoke_accepted_live_context('peer')
                self.state.add_pending_connection(
                    'peer',
                    cast(socket.socket, replacement),
                    b'',
                    PendingConnectionReason.USER_ACCEPT,
                    ConnectionOrigin.INCOMING,
                )
                return 'Peer'

            self.contacts.ensure_alias_for_onion.side_effect = (
                replace_during_alias_lookup
            )
            event_count = len(self.events)
            self.controller.on_live_consumer_available()
        self.assertIsNone(self.state.get_connection('peer'))
        identity = self.state.pending_identity('peer')
        assert identity is not None
        self.assertIs(identity[0], replacement)
        self.assertIs(
            self.state.get_pending_connection_reason('peer'),
            PendingConnectionReason.USER_ACCEPT,
        )
        self.assertEqual(replacement.frames, [])
        self.assertIsNone(self.state.accepted_live_context_generation('peer'))
        self.assertEqual(len(self.events), event_count)

    def test_consumer_callback_accepts_exact_deferred_recovery(self) -> None:
        """A returning consumer activates the original authorized pending transport."""
        with patch('time.monotonic', return_value=100.0):
            conn, generation = self.active()
            self.lose(conn)
            candidate = _PeerSocket()
            self.state.add_pending_connection(
                'peer',
                cast(socket.socket, candidate),
                b'',
                PendingConnectionReason.CONSUMER_ABSENT,
                ConnectionOrigin.GRACE_RECONNECT,
                expected_context_generation=generation,
            )
            self.controller.on_live_consumer_available()
            self.assertEqual(self.state.get_live_context_generation('peer'), generation)
        self.assertIs(self.state.get_connection('peer'), candidate)
        self.assertEqual(candidate.frames, [b'/accepted\n'])

    def test_consumer_callback_preserves_deferred_contact_autoaccept(self) -> None:
        """Deferred contact consent can create its initial context when a consumer returns."""
        candidate = _PeerSocket()
        self.state.add_pending_connection(
            'peer',
            cast(socket.socket, candidate),
            b'',
            PendingConnectionReason.CONSUMER_ABSENT,
            ConnectionOrigin.AUTO_ACCEPT_CONTACT,
        )
        self.controller.on_live_consumer_available()
        self.assertIs(self.state.get_connection('peer'), candidate)
        self.assertEqual(candidate.frames, [b'/accepted\n'])
        self.assertIsNotNone(self.state.accepted_live_context_generation('peer'))
