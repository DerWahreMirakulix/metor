"""Core call identity, bounded media, transport reuse, and compatibility boundaries."""

import base64
import socket
import threading
import time
import unittest
from typing import cast
from unittest.mock import Mock, patch

from metor.core.api import (
    CallAudioEvent,
    CallAudioSentEvent,
    CallReason,
    CallRejectedEvent,
    CallState,
    CallStateEvent,
    CancelCallCommand,
    HangupCallCommand,
    NotificationPrivacy,
    ReadCallAudioCommand,
)
from metor.core.daemon.managed.crypto import Crypto
from metor.core.daemon.managed.models import TorCommand
from metor.core.daemon.managed.network.calls import CallController
from metor.core.daemon.managed.network.handshake import HandshakeProtocol
from metor.core.daemon.managed.network.state import StateTracker
from metor.core.tor import TorManager
from metor.data import ContactManager
from metor.utils import Constants

_FIXTURE_TIMEOUT = 3.0


class CallProtocolTests(unittest.TestCase):
    """Exercises actual call owners and socket writers without acoustic hardware or Tor."""

    def setUp(self) -> None:
        """Creates an isolated Core owner and authenticated shared transport fixture."""
        self.local, self.remote = socket.socketpair()
        self.client, self.other = socket.socketpair()
        self.state = StateTracker()
        self.peer = 'peer.onion'
        self.state.add_active_connection(self.peer, self.local)
        self.contacts = Mock(spec=ContactManager)
        self.contacts.ensure_alias_for_onion.return_value = 'Peer'
        self.contacts.resolve_target_for_interaction.return_value = ('Peer', self.peer)
        self.tor = Mock(spec=TorManager)
        self.tor.onion = 'local.onion'
        self.crypto = Mock(spec=Crypto)
        self.events: list[object] = []
        self.stop = threading.Event()
        self.calls = CallController(
            cast(TorManager, self.tor),
            cast(ContactManager, self.contacts),
            cast(Crypto, self.crypto),
            self.state,
            self.events.append,
            self.stop,
        )
        self.remote.settimeout(_FIXTURE_TIMEOUT)
        self.addCleanup(self._cleanup)
        self.data = base64.b64encode(bytes(Constants.CALL_FRAME_BYTES)).decode('ascii')

    def _cleanup(self) -> None:
        """Revokes calls and socket ownership before disposing the fixture."""
        self.stop.set()
        self.calls.close()
        self.state.abort_all_sockets()
        self.local.close()
        self.remote.close()
        self.client.close()
        self.other.close()
        self.calls.monitor.join(_FIXTURE_TIMEOUT)

    def _incoming(self, call_id: str = 'call-one') -> None:
        """Creates an incoming request using the production signal admission path."""
        self.assertTrue(
            self.calls.process_frame(
                self.peer, self.local, f'CALL_OFFER {call_id} {Constants.CALL_CODEC} 0'
            )
        )
        self.call_id = next(
            item.info.call_id
            for item in self.calls.sessions.values()
            if item.wire_id == call_id and item.info.state is CallState.INCOMING
        )
        self.assertEqual(
            self.calls.sessions[self.call_id].info.state, CallState.INCOMING
        )

    def _active(self, call_id: str = 'call-one') -> None:
        """Explicitly accepts and consumes the corresponding peer acceptance frame."""
        self._incoming(call_id)
        result = self.calls.accept(self.call_id, self.client)
        self.assertIsInstance(result, CallStateEvent)
        self.assertTrue(result.call.owned)
        frame = self.remote.recv(Constants.CALL_MAX_FRAME_BYTES).decode().split()
        self.assertEqual(frame[:2], ['CALL_ACCEPT', call_id])
        self.assertGreaterEqual(int(frame[2]), 0)

    def test_incoming_call_needs_distinct_explicit_consent_and_exact_owner(
        self,
    ) -> None:
        """Approved LIVE transport alone never authorizes telephone audio."""
        self._incoming()
        self.assertIsInstance(
            self.calls.send_audio(self.call_id, self.client, 0, self.data),
            CallRejectedEvent,
        )
        self.assertFalse(
            self.calls.process_frame(
                self.peer, self.local, f'CALL_AUDIO call-one 0 0 {self.data}'
            )
        )
        self.calls.accept(self.call_id, self.client)
        self.assertTrue(self.calls.is_owned_active(self.call_id, self.client))
        self.assertFalse(self.calls.is_owned_active(self.call_id, self.other))
        self.assertIsInstance(
            self.calls.read_audio(self.call_id, self.other, 1), CallRejectedEvent
        )
        self.assertIsInstance(
            self.calls.send_audio(self.call_id, self.other, 0, self.data),
            CallRejectedEvent,
        )
        self.assertFalse(
            self.calls.authorize_call(
                self.other, HangupCallCommand(call_id=self.call_id)
            )
        )

    def test_hangup_revokes_call_audio_while_preserving_shared_chat(self) -> None:
        """Explicit hangup affects Call consent and leaves approved LIVE intact."""
        self._active()
        result = self.calls.control(self.call_id, self.client, CallReason.HUNG_UP)
        self.assertIsInstance(result, CallStateEvent)
        self.assertEqual(result.call.state, CallState.ENDED)
        self.assertIs(self.state.get_connection(self.peer), self.local)
        self.assertEqual(
            self.remote.recv(Constants.CALL_MAX_FRAME_BYTES),
            b'CALL_END call-one hung_up\n',
        )
        self.assertIsInstance(
            self.calls.read_audio(self.call_id, self.client, 1), CallRejectedEvent
        )
        self.assertFalse(
            self.calls.authorize_call(
                self.client, ReadCallAudioCommand(call_id=self.call_id)
            )
        )
        self.assertTrue(
            self.calls.process_frame(
                self.peer, self.local, f'CALL_AUDIO call-one 42 0 {self.data}'
            )
        )
        self.assertEqual(len(self.calls.sessions[self.call_id].frames), 0)

    def test_bounded_audio_discards_backlog_and_is_consumed_once(self) -> None:
        """Conversation audio has a small queue and no message replay or persistence."""
        self._active()
        for sequence in range(Constants.CALL_AUDIO_MAX_FRAMES * 3):
            self.assertTrue(
                self.calls.process_frame(
                    self.peer,
                    self.local,
                    f'CALL_AUDIO call-one {sequence} 0 {self.data}',
                )
            )
        self.assertEqual(
            len(self.calls.sessions[self.call_id].frames),
            Constants.CALL_AUDIO_MAX_FRAMES,
        )
        result = self.calls.read_audio(
            self.call_id, self.client, Constants.CALL_AUDIO_MAX_FRAMES
        )
        self.assertIsInstance(result, CallAudioEvent)
        self.assertEqual(
            [frame.sequence for frame in result.frames],
            list(
                range(
                    Constants.CALL_AUDIO_MAX_FRAMES * 2,
                    Constants.CALL_AUDIO_MAX_FRAMES * 3,
                )
            ),
        )
        self.assertEqual(self.calls.read_audio(self.call_id, self.client, 1).frames, [])
        self.calls.process_frame(
            self.peer, self.local, f'CALL_AUDIO call-one 30 0 {self.data}'
        )
        session = self.calls.sessions[self.call_id]
        frame = session.frames.pop()[1]
        session.frames.append(
            (time.monotonic() - Constants.CALL_AUDIO_EXPIRY_SEC, frame)
        )
        self.assertEqual(self.calls.read_audio(self.call_id, self.client, 1).frames, [])

    def test_mute_revokes_capture_and_preserves_receive_side(self) -> None:
        """Mute is maintained by Core, so a frontend cannot bypass it by sending PCM."""
        self._active()
        self.calls.mute(self.call_id, self.client, True)
        self.assertIsInstance(
            self.calls.send_audio(self.call_id, self.client, 0, self.data),
            CallAudioSentEvent,
        )
        self.assertTrue(self.calls.sessions[self.call_id].info.muted)
        self.calls.process_frame(
            self.peer, self.local, f'CALL_AUDIO call-one 0 0 {self.data}'
        )
        self.assertEqual(
            len(self.calls.read_audio(self.call_id, self.client, 1).frames), 1
        )
        self.assertTrue(
            self.calls.authorize_call(
                self.client, ReadCallAudioCommand(call_id=self.call_id)
            )
        )
        self.calls.mute(self.call_id, self.client, False)
        self.calls.send_audio(self.call_id, self.client, 1, self.data)
        self.assertTrue(
            self.remote.recv(Constants.CALL_MAX_FRAME_BYTES).startswith(
                b'CALL_AUDIO call-one 1 '
            )
        )

    def test_duplicate_offer_and_stale_socket_cannot_transfer_call_ownership(
        self,
    ) -> None:
        """Repeating one signal is inert and replacing transport never inherits consent."""
        self._active()
        self.assertTrue(
            self.calls.process_frame(
                self.peer, self.local, f'CALL_OFFER call-one {Constants.CALL_CODEC} 0'
            )
        )
        self.assertTrue(self.calls.is_owned_active(self.call_id, self.client))
        self.assertTrue(
            self.calls.process_frame(self.peer, self.other, 'CALL_END call-one hung_up')
        )
        self.assertTrue(self.calls.is_owned_active(self.call_id, self.client))
        self.calls.transport_lost(self.other)
        self.assertTrue(self.calls.is_owned_active(self.call_id, self.client))
        self.calls.transport_lost(self.local)
        self.assertEqual(
            self.calls.sessions[self.call_id].info.reason, CallReason.TRANSPORT_LOST
        )

    def test_client_loss_and_privacy_revoke_exact_call_without_chat_teardown(
        self,
    ) -> None:
        """Ended owner receives its masked terminal signal; other clients get no grant."""
        self._active()
        self.calls.disconnect_client(self.other)
        self.assertTrue(self.calls.is_owned_active(self.call_id, self.client))
        self.calls.disconnect_client(self.client)
        session = self.calls.sessions[self.call_id]
        event = CallStateEvent(call=session.info)
        masked = self.calls.project_event(self.client, event, NotificationPrivacy.OFF)
        self.assertTrue(masked.call.owned)
        self.assertEqual(masked.call.peer, '')
        self.assertEqual(masked.call.alias, '')
        self.assertEqual(masked.call.reason, CallReason.CLIENT_LOST)
        self.assertIsNone(
            self.calls.project_event(self.other, event, NotificationPrivacy.OFF)
        )
        self.assertIs(self.state.get_connection(self.peer), self.local)

    def test_expired_incoming_request_cannot_be_accepted(self) -> None:
        """Exact identity remains stale after timeout; the same peer gains no permission."""
        self._incoming()
        self.calls.sessions[self.call_id].deadline = time.monotonic()
        result = self.calls.accept(self.call_id, self.client)
        self.assertIsInstance(result, CallRejectedEvent)
        self.assertEqual(result.reason, CallReason.TIMEOUT)
        self.assertFalse(self.calls.is_owned_active(self.call_id, self.client))

    def test_legacy_peer_generation_fails_before_call_auth_or_audio(self) -> None:
        """Generation-three peers cannot interpret CALL as a chat or message fallback."""
        legacy_local, legacy_remote = socket.socketpair()
        self.addCleanup(legacy_remote.close)
        self.state.pop_any_connection(self.peer)
        self.tor.connect.return_value = legacy_local
        legacy_remote.sendall(
            f'{TorCommand.CHALLENGE.value} {"00" * Constants.TOR_HANDSHAKE_CHALLENGE_BYTES} 3 3\n'.encode()
        )
        self.calls.start(self.peer, 'legacy-call', self.client)
        deadline = time.monotonic() + _FIXTURE_TIMEOUT
        while (
            time.monotonic() < deadline
            and self.calls.sessions['legacy-call'].info.state is not CallState.ENDED
        ):
            self.stop.wait(Constants.CALL_FRAME_INTERVAL_SEC)
        self.assertEqual(
            self.calls.sessions['legacy-call'].info.reason, CallReason.UNSUPPORTED
        )
        self.crypto.sign_challenge.assert_not_called()
        legacy_remote.settimeout(_FIXTURE_TIMEOUT)
        self.assertEqual(legacy_remote.recv(Constants.CALL_MAX_FRAME_BYTES), b'')

    def test_call_auth_flag_is_distinct_from_live_and_async_drop(self) -> None:
        """Authentication selects a dedicated transport lifecycle rather than chat consent."""
        line = HandshakeProtocol.build_auth_line(
            'peer.onion', 'signature', is_call=True
        )
        self.assertTrue(line.endswith(' CALL\n'))
        self.assertEqual(HandshakeProtocol.parse_auth_line(line)[4:], (False, False))

    def test_old_accept_identity_cannot_authorize_a_repeated_offer_after_history_eviction(
        self,
    ) -> None:
        """The receiver mints a new public identity independently of a reused peer wire ID."""
        self._incoming()
        old_public_id = self.call_id
        self.calls.control(old_public_id, self.client, CallReason.REJECTED)
        self.remote.recv(Constants.CALL_MAX_FRAME_BYTES)
        self.calls.sessions.clear()
        self.assertTrue(
            self.calls.process_frame(
                self.peer, self.local, f'CALL_OFFER call-one {Constants.CALL_CODEC} 0'
            )
        )
        self.assertFalse(self.calls.sessions)
        self.remote.recv(Constants.CALL_MAX_FRAME_BYTES)

        replacement, replacement_peer = socket.socketpair()
        self.addCleanup(replacement_peer.close)
        self.state.pop_any_connection(self.peer)
        self.state.retire_connection(self.local)
        self.state.add_active_connection(self.peer, replacement)
        self.assertTrue(
            self.calls.process_frame(
                self.peer, replacement, f'CALL_OFFER call-one {Constants.CALL_CODEC} 0'
            )
        )
        current = next(iter(self.calls.sessions.values()))
        self.assertNotEqual(current.info.call_id, old_public_id)
        self.assertIsInstance(
            self.calls.accept(old_public_id, self.client), CallRejectedEvent
        )
        self.assertEqual(current.info.state, CallState.INCOMING)

    def test_wire_audio_delayed_before_arrival_is_discarded_without_ending_call(
        self,
    ) -> None:
        """Peer-relative timing discards delayed TCP backlog before it reaches local output."""
        self._active()
        session = self.calls.sessions[self.call_id]
        session.peer_clock_offset = (
            time.monotonic() - Constants.CALL_AUDIO_EXPIRY_SEC * 3
        )
        self.assertTrue(
            self.calls.process_frame(
                self.peer, self.local, f'CALL_AUDIO call-one 0 0 {self.data}'
            )
        )
        self.assertEqual(self.calls.read_audio(self.call_id, self.client, 1).frames, [])
        self.assertTrue(self.calls.is_owned_active(self.call_id, self.client))
        fresh_tick = int(
            (time.monotonic() - session.peer_clock_offset)
            * Constants.CALL_TIMESTAMP_SCALE
        )
        self.assertTrue(
            self.calls.process_frame(
                self.peer, self.local, f'CALL_AUDIO call-one 1 {fresh_tick} {self.data}'
            )
        )
        self.assertEqual(
            len(self.calls.read_audio(self.call_id, self.client, 1).frames), 1
        )

    def test_cancellation_withdrawal_wins_remote_acceptance_at_final_admission(
        self,
    ) -> None:
        """Acceptance between cancellation admission and termination cannot leave audio active."""
        self.calls.start(self.peer, 'cancel-race', self.client)
        self.assertTrue(
            self.remote.recv(Constants.CALL_MAX_FRAME_BYTES).startswith(
                b'CALL_OFFER cancel-race '
            )
        )
        self.assertEqual(
            self.calls.sessions['cancel-race'].info.state, CallState.OUTGOING
        )
        original_finish = self.calls.finish

        def accepted_before_finish(*args: object, **kwargs: object) -> bool:
            """Deliver the remote acceptance immediately before the final owner/state check."""
            self.assertTrue(
                self.calls.process_frame(
                    self.peer, self.local, 'CALL_ACCEPT cancel-race 0'
                )
            )
            self.assertTrue(
                self.calls.authorize_call(
                    self.client, CancelCallCommand(call_id='cancel-race')
                )
            )
            self.assertFalse(
                self.calls.authorize_call(
                    self.other, CancelCallCommand(call_id='cancel-race')
                )
            )
            return original_finish(*args, **kwargs)

        with patch.object(self.calls, 'finish', side_effect=accepted_before_finish):
            result = self.calls.control(
                'cancel-race', self.client, CallReason.CANCELLED
            )
        self.assertIsInstance(result, CallStateEvent)
        self.assertEqual(result.call.state, CallState.ENDED)
        self.assertEqual(result.call.reason, CallReason.HUNG_UP)
        self.assertEqual(
            self.remote.recv(Constants.CALL_MAX_FRAME_BYTES),
            b'CALL_END cancel-race hung_up\n',
        )
        self.assertIs(self.state.get_connection(self.peer), self.local)
        self.assertFalse(
            self.calls.authorize_call(
                self.client, CancelCallCommand(call_id='cancel-race')
            )
        )
