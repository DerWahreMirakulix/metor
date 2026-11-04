"""Actual TCP peer lifecycles behind the GUI, Terminal and CLI contracts.

Two encrypted managed runtimes retain production IPC, Ed25519 handshake, framing,
outbox, persistence and media ownership. Only Tor process/SOCKS routing is replaced
by local TCP. Synthetic PCM proves byte handoff, not physical audio playback.
"""

import base64
from collections.abc import Callable
import socket
import threading
import time
import unittest

from metor.client import MetorClient
from metor.core.api import (
    AcceptCommand,
    AddContactCommand,
    CallAudioEvent,
    CallAudioSentEvent,
    CallInfo,
    CallReason,
    CallRejectedEvent,
    CallState,
    CallStateEvent,
    ConnectCommand,
    ConnectedEvent,
    ContactAddedEvent,
    Delivery,
    DisconnectCommand,
    DropQueuedEvent,
    GetMessageOutcomeCommand,
    GetMessagesCommand,
    IpcEvent,
    LiveContextEntry,
    MarkReadCommand,
    MessageDirectionCode,
    MessageOutcomeEvent,
    MessagesDataEvent,
    MessageStatusCode,
    RegisterVoiceOwnerCommand,
    RetunnelCommand,
    SendMessageCommand,
    TextAcceptedEvent,
    TextContent,
    UnreadMessagesEvent,
    VoiceChunkAcceptedEvent,
    VoiceCommittedEvent,
    VoiceDataEvent,
    VoiceFinalizedEvent,
    VoiceOwnerRegisteredEvent,
    VoiceReleasedEvent,
    VoiceStartedEvent,
)
from metor.shared import Constants

# Local Package Imports
from frontend_e2e_runtime import EncryptedFrontendRuntime, FIXTURE_WAIT_SECONDS


_POLL_SECONDS: float = Constants.CALL_FRAME_INTERVAL_SEC
_PCM_BYTES: bytes = b'\x12\x34' * (Constants.CALL_FRAME_BYTES // 2)
_VOICE_CODEC: str = 'pcm_s16le_16000_mono'


class FrontendPeerE2eTests(unittest.TestCase):
    """Observe real peer outcomes solely through the typed client contract."""

    def setUp(self) -> None:
        """Start two independently authorized profiles and actual inbound TCP listeners."""
        self.runtime = self.enterContext(EncryptedFrontendRuntime())
        assert self.runtime.peer is not None
        self.peer = self.runtime.peer
        self.sender = self.runtime.client(live_consumer=True)
        self.receiver = self.peer.client(live_consumer=True)

    def wait_for(self, predicate: Callable[[], bool], description: str) -> None:
        """Boundedly await a public projection instead of guessing worker completion."""
        deadline = time.monotonic() + FIXTURE_WAIT_SECONDS
        pause = threading.Event()
        while time.monotonic() < deadline:
            if predicate():
                return
            pause.wait(_POLL_SECONDS)
        self.fail(description)

    def outcome(
        self, client: MetorClient, target: str, identity: str
    ) -> MessageOutcomeEvent:
        """Read a stable, body-free outgoing receipt through actual protected IPC."""
        result = client.request(
            GetMessageOutcomeCommand(target, identity, MessageDirectionCode.OUT),
            MessageOutcomeEvent,
        )
        self.assertIsInstance(result, MessageOutcomeEvent)
        assert isinstance(result, MessageOutcomeEvent)
        return result

    def send(self, identity: str, delivery: Delivery, body: str) -> None:
        """Confirm local admission separately from asynchronous remote acceptance."""
        result = self.sender.request(
            SendMessageCommand(
                self.peer.onion,
                delivery,
                TextContent(body),
                identity,
                local_acceptance=delivery is Delivery.LIVE,
            ),
            DropQueuedEvent if delivery is Delivery.DROP else TextAcceptedEvent,
        )
        if delivery is Delivery.DROP:
            self.assertIsInstance(result, DropQueuedEvent)
            assert isinstance(result, DropQueuedEvent)
            self.assertEqual(result.onion, self.peer.onion)
        else:
            self.assertIsInstance(result, TextAcceptedEvent)
            assert isinstance(result, TextAcceptedEvent)
            self.assertEqual((result.msg_id, result.delivery), (identity, delivery))
        self.wait_for(
            lambda: (
                self.outcome(self.sender, self.peer.onion, identity).status
                in (MessageStatusCode.DELIVERED, MessageStatusCode.READ)
            ),
            'The real peer did not durably accept the text.',
        )

    def archive(self, client: MetorClient, target: str) -> MessagesDataEvent:
        """Inspect durable DROP history without consuming it or reading SQL directly."""
        result = client.request(GetMessagesCommand(target), MessagesDataEvent)
        self.assertIsInstance(result, MessagesDataEvent)
        assert isinstance(result, MessagesDataEvent)
        return result

    def live_context(self, client: MetorClient, target: str) -> LiveContextEntry | None:
        """Read current logical LIVE permission independently of physical streams."""
        snapshot = client.runtime_snapshot()
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        return next(
            (context for context in snapshot.live_contexts if context.onion == target),
            None,
        )

    def connect_live(self) -> tuple[int, int]:
        """Require a fresh exact invitation and explicit acceptance by the peer."""
        self.assertIsNotNone(
            self.sender.request(ConnectCommand(self.peer.onion), IpcEvent)
        )
        self.wait_for(
            lambda: bool(self.receiver.runtime_snapshot().pending),
            'No actual LIVE invitation arrived.',
        )
        snapshot = self.receiver.runtime_snapshot()
        assert snapshot is not None
        self.assertEqual(len(snapshot.pending), 1)
        request = snapshot.pending[0]
        self.assertEqual(request.onion, self.runtime.onion)
        self.assertIsInstance(
            self.receiver.request(
                AcceptCommand(request.onion, request.action_handle), ConnectedEvent
            ),
            ConnectedEvent,
        )

        def connected() -> bool:
            """Require both public logical contexts to be fully accepted."""
            local = self.live_context(self.sender, self.peer.onion)
            remote = self.live_context(self.receiver, self.runtime.onion)
            return (
                local is not None
                and remote is not None
                and local.session_state == remote.session_state == 'connected'
            )

        self.wait_for(connected, 'Accepted LIVE did not become usable on both peers.')
        local = self.live_context(self.sender, self.peer.onion)
        remote = self.live_context(self.receiver, self.runtime.onion)
        assert local is not None and remote is not None
        assert local.context_generation is not None
        assert remote.context_generation is not None
        return local.context_generation, remote.context_generation

    def call(self, client: MetorClient, identity: str) -> CallInfo:
        """Read exact current call identity without acquiring media permission."""
        result = client.get_calls()
        self.assertIsNotNone(result)
        assert result is not None
        found = next((call for call in result.calls if call.call_id == identity), None)
        self.assertIsNotNone(found)
        assert found is not None
        return found

    def accept_call(self, identity: str) -> str:
        """Start one request and grant one independent explicit remote Call consent."""
        self.assertIsInstance(
            self.sender.start_call(self.peer.onion, identity), CallStateEvent
        )
        incoming: list[CallInfo] = []

        def offered() -> bool:
            """Resolve Core's separate receiver-local request identity."""
            calls = self.receiver.get_calls()
            assert calls is not None
            incoming[:] = [
                call for call in calls.calls if call.state is CallState.INCOMING
            ]
            return bool(incoming)

        self.wait_for(offered, 'The actual peer never received the Call offer.')
        self.assertEqual(len(incoming), 1)
        remote_id = incoming[0].call_id
        self.assertIsInstance(self.receiver.accept_call(remote_id), CallStateEvent)
        self.wait_for(
            lambda: (
                self.call(self.sender, identity).state is CallState.ACTIVE
                and self.call(self.receiver, remote_id).state is CallState.ACTIVE
            ),
            'The independently accepted Call did not become active.',
        )
        self.assertTrue(self.call(self.sender, identity).owned)
        self.assertTrue(self.call(self.receiver, remote_id).owned)
        return remote_id

    def audio(self, identity: str, remote_id: str) -> None:
        """Move one fresh synthetic frame through actual IPC and authenticated TCP."""
        self.assertIsInstance(
            self.sender.send_call_audio(
                identity, 0, base64.b64encode(_PCM_BYTES).decode()
            ),
            CallAudioSentEvent,
        )
        frames: list[bytes] = []

        def received() -> bool:
            """Consume bounded fresh frames only through the exact-owner SDK call."""
            result = self.receiver.read_call_audio(remote_id)
            self.assertIsInstance(result, CallAudioEvent)
            assert isinstance(result, CallAudioEvent)
            frames.extend(base64.b64decode(frame.data) for frame in result.frames)
            return bool(frames)

        self.wait_for(received, 'No fresh actual peer Call frame arrived.')
        self.assertEqual(frames, [_PCM_BYTES])

    def test_drop_before_live_duplicate_receipt_and_read_are_immediate(self) -> None:
        """DROP needs no chat consent; repeated IDs never duplicate durable rows or unread."""
        for client in (self.sender, self.receiver):
            snapshot = client.runtime_snapshot()
            assert snapshot is not None
            self.assertEqual(snapshot.live_contexts, [])
            self.assertEqual(snapshot.pending, [])
        self.send('before-live-drop', Delivery.DROP, 'First DROP, no previous LIVE')
        self.send('before-live-drop', Delivery.DROP, 'First DROP, no previous LIVE')
        self.send('second-drop', Delivery.DROP, 'Second DROP on the same contact')
        rows = self.archive(self.receiver, self.runtime.onion).messages
        self.assertEqual(
            {row.msg_id for row in rows}, {'before-live-drop', 'second-drop'}
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.delivery is Delivery.DROP for row in rows))
        self.assertTrue(all(row.status is MessageStatusCode.UNREAD for row in rows))
        result = self.receiver.request(
            MarkReadCommand(self.runtime.onion, Delivery.DROP), UnreadMessagesEvent
        )
        self.assertIsInstance(result, UnreadMessagesEvent)
        assert isinstance(result, UnreadMessagesEvent)
        self.assertEqual(len(result.messages), 2)
        # Read receipts are disabled by default, and offline consumption is local.
        # Delivery acknowledgement must never be fabricated into remote Read.
        for identity in ('before-live-drop', 'second-drop'):
            self.assertIs(
                self.outcome(self.sender, self.peer.onion, identity).status,
                MessageStatusCode.DELIVERED,
            )
        self.send('before-live-drop', Delivery.DROP, 'First DROP, no previous LIVE')
        self.assertEqual(
            len(self.archive(self.receiver, self.runtime.onion).messages), 2
        )
        self.assertTrue(
            all(
                row.status is MessageStatusCode.READ
                for row in self.archive(self.receiver, self.runtime.onion).messages
            )
        )
        for client in (self.sender, self.receiver):
            snapshot = client.runtime_snapshot()
            assert snapshot is not None
            self.assertEqual(snapshot.live_contexts, [])
            self.assertEqual(snapshot.pending, [])

    def test_live_voice_drop_and_retunnel_preserve_chat_without_phantom_calls(
        self,
    ) -> None:
        """Explicit Voice handoff, DROP in LIVE, and route replacement keep one chat usable."""
        local_generation, _remote_generation = self.connect_live()
        owner = self.sender.request(
            RegisterVoiceOwnerCommand(), VoiceOwnerRegisteredEvent
        )
        assert owner is not None
        identity = 'live-synthetic-voice'
        self.assertIsInstance(
            self.sender.begin_voice(
                self.peer.onion,
                Delivery.LIVE,
                identity,
                _VOICE_CODEC,
                owner_token=owner.owner_token,
                context_generation=local_generation,
            ),
            VoiceStartedEvent,
        )
        self.assertIsInstance(
            self.sender.append_voice(
                identity,
                0,
                base64.b64encode(_PCM_BYTES).decode(),
                owner_token=owner.owner_token,
            ),
            VoiceChunkAcceptedEvent,
        )
        self.assertIsInstance(
            self.sender.finalize_voice(identity, owner_token=owner.owner_token),
            VoiceFinalizedEvent,
        )
        self.assertIsInstance(
            self.sender.commit_voice(
                self.peer.onion,
                identity,
                owner_token=owner.owner_token,
                context_generation=local_generation,
            ),
            VoiceCommittedEvent,
        )
        self.wait_for(
            lambda: any(
                item.msg_id == identity and item.finalized
                for item in self.receiver.list_retained_messages().messages
            ),
            'The committed Voice did not arrive finalized at the actual peer.',
        )
        received = self.receiver.get_voice_chunk(
            self.runtime.onion, identity, MessageDirectionCode.IN, 0, len(_PCM_BYTES)
        )
        self.assertIsInstance(received, VoiceDataEvent)
        assert isinstance(received, VoiceDataEvent)
        self.assertEqual(base64.b64decode(received.data), _PCM_BYTES)
        self.assertTrue(received.complete)
        self.assertIs(received.delivery, Delivery.LIVE)
        self.assertIsInstance(
            self.receiver.release_voice(self.runtime.onion, identity),
            VoiceReleasedEvent,
        )
        self.send('after-live-voice', Delivery.LIVE, 'LIVE still sends after Voice')
        self.send('drop-during-live', Delivery.DROP, 'Explicit DROP while LIVE')
        self.assertEqual(
            [
                row.msg_id
                for row in self.archive(self.receiver, self.runtime.onion).messages
            ],
            ['drop-during-live'],
        )
        self.assertEqual(
            self.live_context(self.sender, self.peer.onion).context_generation,
            local_generation,
        )
        self.assertIsNotNone(
            self.sender.request(
                RetunnelCommand(self.peer.onion, local_generation), IpcEvent
            )
        )
        self.wait_for(
            lambda: (
                (context := self.live_context(self.sender, self.peer.onion)) is not None
                and context.session_state == 'connected'
                and not context.route_changing
            ),
            'Retunnel did not restore the actual peer route.',
        )
        self.send('after-voice-retunnel', Delivery.LIVE, 'Text after route replacement')
        for client in (self.sender, self.receiver):
            snapshot = client.runtime_snapshot()
            assert snapshot is not None
            self.assertEqual(snapshot.pending, [])
            self.assertEqual(client.get_calls().calls, [])

    def test_first_voice_drop_is_local_until_commit_then_readable_without_live(
        self,
    ) -> None:
        """A fresh peer needs no prior text/LIVE; finalized drafts never publish implicitly."""
        self.assertIsInstance(
            self.sender.request(
                AddContactCommand('VoiceReceiver', self.peer.onion), ContactAddedEvent
            ),
            ContactAddedEvent,
        )
        owner = self.sender.request(
            RegisterVoiceOwnerCommand(), VoiceOwnerRegisteredEvent
        )
        assert owner is not None
        identity = 'first-voice-drop'
        self.assertIsInstance(
            self.sender.begin_voice(
                self.peer.onion,
                Delivery.DROP,
                identity,
                _VOICE_CODEC,
                owner_token=owner.owner_token,
            ),
            VoiceStartedEvent,
        )
        self.assertIsInstance(
            self.sender.append_voice(
                identity,
                0,
                base64.b64encode(_PCM_BYTES).decode(),
                owner_token=owner.owner_token,
            ),
            VoiceChunkAcceptedEvent,
        )
        self.assertIsInstance(
            self.sender.finalize_voice(identity, owner_token=owner.owner_token),
            VoiceFinalizedEvent,
        )
        retained = self.receiver.list_retained_messages()
        assert retained is not None
        self.assertEqual(retained.messages, [])
        self.assertIsInstance(
            self.sender.commit_voice(
                self.peer.onion, identity, owner_token=owner.owner_token
            ),
            VoiceCommittedEvent,
        )
        self.wait_for(
            lambda: (
                self.outcome(self.sender, self.peer.onion, identity).status
                is MessageStatusCode.DELIVERED
            ),
            'The first explicit Voice DROP did not reach the fresh actual peer.',
        )
        prefix_size = len(_PCM_BYTES) // 2
        prefix = self.receiver.get_voice_chunk(
            self.runtime.onion, identity, MessageDirectionCode.IN, 0, prefix_size
        )
        self.assertIsInstance(prefix, VoiceDataEvent)
        assert isinstance(prefix, VoiceDataEvent)
        self.assertFalse(prefix.complete)
        self.assertEqual(base64.b64decode(prefix.data), _PCM_BYTES[:prefix_size])
        suffix = self.receiver.get_voice_chunk(
            self.runtime.onion,
            identity,
            MessageDirectionCode.IN,
            prefix.next_offset,
            len(_PCM_BYTES),
        )
        self.assertIsInstance(suffix, VoiceDataEvent)
        assert isinstance(suffix, VoiceDataEvent)
        self.assertTrue(suffix.complete)
        self.assertEqual(base64.b64decode(suffix.data), _PCM_BYTES[prefix_size:])
        self.assertIs(suffix.delivery, Delivery.DROP)
        self.assertIsInstance(
            self.receiver.release_voice(self.runtime.onion, identity),
            VoiceReleasedEvent,
        )
        archive = self.archive(self.receiver, self.runtime.onion)
        self.assertEqual(len(archive.messages), 1)
        self.assertIs(archive.messages[0].status, MessageStatusCode.READ)
        for client in (self.sender, self.receiver):
            snapshot = client.runtime_snapshot()
            assert snapshot is not None
            self.assertEqual(snapshot.live_contexts, [])
            self.assertEqual(snapshot.pending, [])
            self.assertEqual(client.get_calls().calls, [])

    def test_ending_live_keeps_exact_call_then_transport_loss_revokes_consent(
        self,
    ) -> None:
        """CALL survives intentional chat end; loss ends media and reconnect cannot reaccept it."""
        local_generation, _remote_generation = self.connect_live()
        identity = 'borrowed-real-tcp-call'
        remote_id = self.accept_call(identity)
        observer = self.runtime.client()
        self.assertIsInstance(observer.read_call_audio(identity), CallRejectedEvent)
        self.assertIsNotNone(
            self.sender.request(
                DisconnectCommand(self.peer.onion, local_generation), IpcEvent
            )
        )
        self.wait_for(
            lambda: all(
                (context := self.live_context(client, target)) is None
                or context.session_state != 'connected'
                for client, target in (
                    (self.sender, self.peer.onion),
                    (self.receiver, self.runtime.onion),
                )
            ),
            'Intentional chat end left LIVE permission active.',
        )
        self.assertIs(self.call(self.sender, identity).state, CallState.ACTIVE)
        self.assertIs(self.call(self.receiver, remote_id).state, CallState.ACTIVE)
        self.audio(identity, remote_id)
        self.send('drop-with-call-only', Delivery.DROP, 'DROP during independent CALL')
        self.assertEqual(
            len(self.archive(self.receiver, self.runtime.onion).messages), 1
        )

        # Fault injection ends the actual retained socket, never a fabricated IPC event.
        network = self.runtime.daemon._network
        assert network is not None
        with network.calls.lock:
            connection = network.calls.sessions[identity].connection
        connection.shutdown(socket.SHUT_RDWR)
        self.wait_for(
            lambda: (
                self.call(self.sender, identity).state is CallState.ENDED
                and self.call(self.receiver, remote_id).state is CallState.ENDED
            ),
            'Lost actual peer stream did not terminate both accepted calls.',
        )
        self.assertIs(
            self.call(self.sender, identity).reason, CallReason.TRANSPORT_LOST
        )
        self.assertIs(
            self.call(self.receiver, remote_id).reason, CallReason.TRANSPORT_LOST
        )
        self.assertIsInstance(
            self.sender.send_call_audio(
                identity, 1, base64.b64encode(_PCM_BYTES).decode()
            ),
            CallRejectedEvent,
        )
        self.assertIsInstance(self.receiver.accept_call(remote_id), CallRejectedEvent)
        self.connect_live()
        self.send('after-call-loss', Delivery.LIVE, 'Fresh chat after ended Call')
        for client in (self.sender, self.receiver):
            calls = client.get_calls()
            assert calls is not None
            self.assertTrue(all(call.state is CallState.ENDED for call in calls.calls))
