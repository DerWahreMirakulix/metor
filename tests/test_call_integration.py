"""Telephone consent and duplex media through real protected Core IPC and peer streams.

Only Tor dialing is replaced by socket pairs. Production signing, peer handshake,
listener, stream reader, writers, call lifecycle and SDK dispatch remain active.
PCM is synthetic; this does not establish physical headset or public Tor support.
"""

import atexit
import base64
import hashlib
import socket
import threading
import time
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from metor.client import MetorClient, build_session_auth_proof
from metor.core.api import (
    AcceptCallCommand,
    AcceptCommand,
    AddContactCommand,
    CallAudioEvent,
    CallAudioSentEvent,
    CallInfo,
    CallReason,
    CallRejectedEvent,
    CallState,
    CallStateEvent,
    ClientAccessRestrictedEvent,
    ClientRestrictedEvent,
    ClientUnlockMethod,
    ConnectCommand,
    ConnectedEvent,
    Delivery,
    DisconnectCommand,
    GetGuiPreferencesCommand,
    GuiPreferencesEvent,
    IncomingConnectionEvent,
    IpcEvent,
    LockCommand,
    MessageReceivedEvent,
    NotificationPrivacy,
    RestrictClientCommand,
    SendMessageCommand,
    SetGuiPreferencesCommand,
    TextAcceptedEvent,
    TextContent,
)
from metor.core.daemon.managed.engine import Daemon
from metor.core.daemon.managed.local_auth import create_session_auth_context
from metor.core.daemon.managed.models import SessionState
from metor.core.daemon.managed.models import TorCommand
from metor.core.key import KeyManager
from metor.data import ContactManager, HistoryManager, MessageManager, SettingKey
from metor.data.blob import EncryptedBlobStore
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.utils import Constants


@dataclass
class _Peer:
    """One isolated encrypted profile with its public client and loopback Tor port."""

    daemon: Daemon
    client: MetorClient
    tor: Mock
    onion: str
    contacts: ContactManager


class CallIntegrationTests(unittest.TestCase):
    """Verify actual dispatch and authenticated peer framing without external media."""

    def setUp(self) -> None:
        """Start two encrypted managed runtimes and independent authenticated clients."""
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patcher = patch.object(Constants, 'DATA', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.condition = threading.Condition()
        self.events: dict[str, list[IpcEvent]] = {'sender': [], 'receiver': []}
        self.peer_threads: list[threading.Thread] = []
        self.sockets: list[socket.socket] = []
        self.call_ids: dict[tuple[str, str], str] = {}
        self.sender = self._peer('sender')
        self.receiver = self._peer('receiver')
        self.sender.contacts.ensure_alias_for_onion(self.receiver.onion)
        self.receiver.contacts.ensure_alias_for_onion(self.sender.onion)
        self.sender.tor.connect.side_effect = lambda target: self._dial(
            self.receiver, target
        )
        self.receiver.tor.connect.side_effect = lambda target: self._dial(
            self.sender, target
        )
        self.other = self._client(self.sender.daemon)
        self.addCleanup(self._close_streams)

    def _observe(self, side: str, event: IpcEvent) -> None:
        """Wake assertion barriers on real asynchronous SDK events."""
        with self.condition:
            self.events[side].append(event)
            self.condition.notify_all()

    def _client(self, daemon: Daemon, side: str | None = None) -> MetorClient:
        """Authenticate over the real IPC server using one-use password proofs."""
        provider = Mock()
        provider.get_session_auth_proof.side_effect = lambda challenge, salt: (
            build_session_auth_proof('test-password', challenge, salt)
        )
        provider.get_master_password.return_value = None
        port = daemon._ipc.port
        assert port is not None
        client = MetorClient(
            port,
            auth_provider=provider,
            timeout=Constants.DEFAULT_IPC_TIMEOUT,
            on_event=(lambda event: self._observe(side, event)) if side else None,
        )
        self.addCleanup(client.disconnect)
        self.assertIsNotNone(client.bootstrap())
        self.assertTrue(client.register_live_consumer())
        return client

    def _peer(self, name: str) -> _Peer:
        """Compose real encrypted persistence, identity and managed dispatch."""
        profile = ProfileManager(name)
        profile.initialize()
        keys = KeyManager(profile, 'test-password')
        keys.generate_keys()
        public = keys.get_metor_key()[-Constants.TOR_V3_PUBLIC_KEY_BYTES :]
        version = b'\x03'
        checksum = hashlib.sha3_256(b'.onion checksum' + public + version).digest()[:2]
        onion = base64.b32encode(public + checksum + version).decode('ascii').lower()
        key = keys.get_database_key()
        assert key is not None
        self.addCleanup(SqlManager.close_connection, profile.paths.get_db_file())
        contacts = ContactManager(profile, key)
        blobs = EncryptedBlobStore(
            self.root / f'{name}-persistent', self.root / f'{name}-temporary', key
        )
        self.addCleanup(blobs.close)
        tor = Mock(onion=onion)
        tor.is_running.return_value = True
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            daemon = Daemon(
                profile,
                keys,
                tor,
                contacts,
                HistoryManager(profile, key),
                MessageManager(profile, key),
                blobs,
                session_auth=create_session_auth_context('test-password'),
                require_session_auth=True,
            )
        atexit.unregister(daemon.stop)
        self.addCleanup(daemon.stop)
        daemon._ipc.start()
        return _Peer(daemon, self._client(daemon, name), tor, onion, contacts)

    def _dial(self, destination: _Peer, target: str) -> socket.socket:
        """Substitute only dialing while preserving production peer authentication."""
        self.assertEqual(target, destination.onion)
        local, remote = socket.socketpair()
        self.sockets.extend((local, remote))
        destination.daemon._transport_state.add_unauthenticated_connection(remote)
        network = destination.daemon._network
        assert network is not None
        worker = threading.Thread(
            target=network._listener._handle_incoming,
            args=(remote,),
            daemon=True,
        )
        self.peer_threads.append(worker)
        worker.start()
        return local

    def _close_streams(self) -> None:
        """Close the test network and confirm production listener workers exit."""
        for connection in self.sockets:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        for worker in self.peer_threads:
            worker.join(Constants.DEFAULT_IPC_TIMEOUT)
            self.assertFalse(worker.is_alive())

    def _wait_state(self, side: str, call_id: str, state: CallState) -> CallInfo:
        """Wait for a real publication and verify the current public SDK projection."""
        call_id = self.call_ids.get((side, call_id), call_id)
        with self.condition:
            self.assertTrue(
                self.condition.wait_for(
                    lambda: any(
                        isinstance(event, CallStateEvent)
                        and event.call.call_id == call_id
                        and event.call.state is state
                        for event in self.events[side]
                    ),
                    timeout=Constants.DEFAULT_IPC_TIMEOUT,
                ),
                f'{side} did not publish {state.value}',
            )
        peer = self.sender if side == 'sender' else self.receiver
        result = peer.client.get_calls()
        assert result is not None
        current = next(call for call in result.calls if call.call_id == call_id)
        self.assertIs(current.state, state)
        return current

    def _incoming(self, side: str, label: str) -> str:
        """Discover Core's local request identity independently of its wire identity."""
        peer = self.sender if side == 'sender' else self.receiver
        incoming: list[CallInfo] = []

        def ready() -> bool:
            """Read current metadata without granting consent or reading media."""
            result = peer.client.get_calls()
            assert result is not None
            incoming[:] = [
                call for call in result.calls if call.state is CallState.INCOMING
            ]
            return bool(incoming)

        with self.condition:
            self.assertTrue(
                self.condition.wait_for(ready, timeout=Constants.DEFAULT_IPC_TIMEOUT)
            )
        self.assertEqual(len(incoming), 1)
        self.call_ids[(side, label)] = incoming[0].call_id
        return incoming[0].call_id

    def _identity(self, client: MetorClient, label: str) -> str:
        """Resolve one client-local test identity without depending on transport IDs."""
        side = 'sender' if client is self.sender.client else 'receiver'
        return self.call_ids.get((side, label), label)

    def _active_call(self, call_id: str) -> None:
        """Issue exactly one call request and one explicit call acceptance."""
        self.assertIsInstance(
            self.sender.client.start_call(self.receiver.onion, call_id), CallStateEvent
        )
        incoming_id = self._incoming('receiver', call_id)
        self.assertIsInstance(
            self.receiver.client.accept_call(incoming_id), CallStateEvent
        )
        self.assertTrue(self._wait_state('sender', call_id, CallState.ACTIVE).owned)
        self.assertTrue(self._wait_state('receiver', call_id, CallState.ACTIVE).owned)

    def _read_frame(self, client: MetorClient, call_id: str) -> CallAudioEvent:
        """Consume a fresh real peer frame without introducing retransmission."""
        deadline = time.monotonic() + Constants.DEFAULT_IPC_TIMEOUT
        while time.monotonic() < deadline:
            result = client.read_call_audio(self._identity(client, call_id))
            self.assertIsInstance(result, CallAudioEvent)
            assert isinstance(result, CallAudioEvent)
            if result.frames:
                return result
            threading.Event().wait(Constants.CALL_FRAME_INTERVAL_SEC / 4)
        self.fail('No fresh peer audio frame received.')

    def _duplex(self, call_id: str, sequence: int) -> None:
        """Send simultaneous synthetic PCM in both directions through Core IPC."""
        barrier = threading.Barrier(2)
        payloads = (b'\x01\x02', b'\x03\x04')
        clients = (self.sender.client, self.receiver.client)
        outcomes: list[IpcEvent | None] = []

        def send(client: MetorClient, sample: bytes) -> None:
            """Synchronize simultaneous audio admission independently of playback."""
            barrier.wait(Constants.DEFAULT_IPC_TIMEOUT)
            data = base64.b64encode(sample * (Constants.CALL_FRAME_BYTES // 2)).decode()
            outcomes.append(
                client.send_call_audio(self._identity(client, call_id), sequence, data)
            )

        workers = [
            threading.Thread(target=send, args=(client, sample))
            for client, sample in zip(clients, payloads, strict=True)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(Constants.DEFAULT_IPC_TIMEOUT)
            self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(
            all(isinstance(result, CallAudioSentEvent) for result in outcomes)
        )
        for client, remote_sample in zip(clients, reversed(payloads), strict=True):
            received = self._read_frame(client, call_id)
            self.assertEqual(received.frames[0].sequence, sequence)
            self.assertEqual(
                base64.b64decode(received.frames[0].data),
                remote_sample * (Constants.CALL_FRAME_BYTES // 2),
            )

    def _discard_delayed_wire_audio(self, call_id: str, sequence: int) -> None:
        """Delay actual peer processing and verify TCP backlog is never replayed."""
        network = self.receiver.daemon._network
        assert network is not None
        controller = network.calls
        original = controller.process_frame
        entered, release, processed = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def paused(
            onion: str, connection: socket.socket, line: str, borrowed: bool = True
        ) -> bool:
            """Hold one encoded audio frame before the production admission checks."""
            is_audio = line.startswith(TorCommand.CALL_AUDIO.value + ' ')
            if is_audio:
                entered.set()
                self.assertTrue(release.wait(Constants.DEFAULT_IPC_TIMEOUT))
            accepted = original(onion, connection, line, borrowed)
            if is_audio:
                processed.set()
            return accepted

        try:
            with patch.object(controller, 'process_frame', side_effect=paused):
                data = base64.b64encode(b'\0' * Constants.CALL_FRAME_BYTES).decode()
                self.assertIsInstance(
                    self.sender.client.send_call_audio(call_id, sequence, data),
                    CallAudioSentEvent,
                )
                self.assertTrue(entered.wait(Constants.DEFAULT_IPC_TIMEOUT))
                threading.Event().wait(
                    Constants.CALL_AUDIO_EXPIRY_SEC + Constants.CALL_FRAME_INTERVAL_SEC
                )
                release.set()
                self.assertTrue(processed.wait(Constants.DEFAULT_IPC_TIMEOUT))
        finally:
            release.set()
        received = self.receiver.client.read_call_audio(
            self._identity(self.receiver.client, call_id)
        )
        self.assertIsInstance(received, CallAudioEvent)
        assert isinstance(received, CallAudioEvent)
        self.assertEqual(received.frames, [])
        self._wait_state('receiver', call_id, CallState.ACTIVE)

    def test_direct_call_consent_duplex_and_restricted_exact_owner(self) -> None:
        """Call acceptance authorizes duplex audio without creating a LIVE chat."""
        call_id = 'direct-call'
        self.assertIsInstance(
            self.sender.client.start_call(self.receiver.onion, call_id), CallStateEvent
        )
        incoming_id = self._incoming('receiver', call_id)
        data = base64.b64encode(b'\0' * Constants.CALL_FRAME_BYTES).decode()
        self.assertIsInstance(
            self.sender.client.send_call_audio(call_id, 0, data), CallRejectedEvent
        )
        self.assertIsInstance(
            self.receiver.client.accept_call(incoming_id), CallStateEvent
        )
        self._wait_state('sender', call_id, CallState.ACTIVE)
        self.assertIsInstance(self.other.read_call_audio(call_id), CallRejectedEvent)
        self._duplex(call_id, 0)
        self._discard_delayed_wire_audio(call_id, 1)
        for peer in (self.sender, self.receiver):
            snapshot = peer.client.runtime_snapshot()
            assert snapshot is not None
            self.assertEqual(snapshot.live_contexts, [])
            self.assertEqual(snapshot.pending, [])
            retained = peer.client.list_retained_messages()
            assert retained is not None
            self.assertEqual(retained.messages, [])

        self.sender.client.mute_call(call_id, True)
        self.sender.client.request(
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                notification_privacy=NotificationPrivacy.ANONYMIZE,
            ),
            ClientRestrictedEvent,
        )
        restricted = self.sender.client.get_calls()
        assert restricted is not None
        active = next(call for call in restricted.calls if call.call_id == call_id)
        self.assertEqual((active.peer, active.alias), ('', ''))
        self.assertTrue(active.owned)
        self.assertTrue(active.muted)
        self.assertIsInstance(
            self.sender.client.request(
                SendMessageCommand(
                    target=self.receiver.onion,
                    delivery=Delivery.LIVE,
                    content=TextContent('forbidden'),
                    msg_id='locked-text',
                ),
                IpcEvent,
            ),
            ClientAccessRestrictedEvent,
        )
        self.assertIsInstance(
            self.sender.client.mute_call(call_id, False), CallStateEvent
        )
        self._duplex(call_id, 2)
        self.assertIsInstance(self.sender.client.hangup_call(call_id), CallStateEvent)
        ended = self._wait_state('receiver', call_id, CallState.ENDED)
        self.assertIs(ended.reason, CallReason.HUNG_UP)

        self.receiver.client.start_call(self.sender.onion, 'later-call')
        later_id = self._incoming('sender', 'later-call')
        self.assertIsInstance(
            self.sender.client.request(AcceptCallCommand(later_id), IpcEvent),
            ClientAccessRestrictedEvent,
        )
        self.assertIsInstance(self.other.reject_call(later_id), CallStateEvent)
        self._wait_state('receiver', 'later-call', CallState.ENDED)

    def test_borrowed_live_call_hangup_and_rejection_preserve_chat(self) -> None:
        """Call rejection and hangup leave an independently accepted chat usable."""
        self.sender.client.request(ConnectCommand(self.receiver.onion), IpcEvent)
        with self.condition:
            self.assertTrue(
                self.condition.wait_for(
                    lambda: any(
                        isinstance(event, IncomingConnectionEvent)
                        for event in self.events['receiver']
                    ),
                    timeout=Constants.DEFAULT_IPC_TIMEOUT,
                )
            )
        self.receiver.client.request(AcceptCommand(self.sender.onion), ConnectedEvent)
        deadline = time.monotonic() + Constants.DEFAULT_IPC_TIMEOUT
        while time.monotonic() < deadline:
            snapshot = self.sender.client.runtime_snapshot()
            if snapshot and any(
                context.session_state == SessionState.CONNECTED.value
                for context in snapshot.live_contexts
            ):
                break
            threading.Event().wait(Constants.CALL_FRAME_INTERVAL_SEC)
        else:
            self.fail('The explicit LIVE chat was not accepted.')

        self.sender.client.start_call(self.receiver.onion, 'rejected-call')
        rejected_id = self._incoming('receiver', 'rejected-call')
        self.receiver.client.reject_call(rejected_id)
        self._wait_state('sender', 'rejected-call', CallState.ENDED)
        self._active_call('borrowed-call')
        self._duplex('borrowed-call', 0)
        self.sender.client.hangup_call('borrowed-call')
        self._wait_state('receiver', 'borrowed-call', CallState.ENDED)
        for peer in (self.sender, self.receiver):
            snapshot = peer.client.runtime_snapshot()
            assert snapshot is not None
            self.assertTrue(
                any(
                    context.session_state == SessionState.CONNECTED.value
                    for context in snapshot.live_contexts
                )
            )
        self.sender.client.request(
            SendMessageCommand(
                target=self.receiver.onion,
                delivery=Delivery.LIVE,
                content=TextContent('chat remains usable'),
                msg_id='after-hangup',
                local_acceptance=True,
            ),
            TextAcceptedEvent,
        )
        with self.condition:
            self.assertTrue(
                self.condition.wait_for(
                    lambda: any(
                        isinstance(event, MessageReceivedEvent)
                        and event.msg_id == 'after-hangup'
                        for event in self.events['receiver']
                    ),
                    timeout=Constants.DEFAULT_IPC_TIMEOUT,
                )
            )

        self._active_call('chat-ending-call')
        self.sender.client.request(DisconnectCommand(self.receiver.onion), IpcEvent)
        deadline = time.monotonic() + Constants.DEFAULT_IPC_TIMEOUT
        while time.monotonic() < deadline:
            snapshots = (
                self.sender.client.runtime_snapshot(),
                self.receiver.client.runtime_snapshot(),
            )
            if all(
                snapshot is not None
                and all(
                    context.session_state != SessionState.CONNECTED.value
                    for context in snapshot.live_contexts
                )
                for snapshot in snapshots
            ):
                break
            threading.Event().wait(Constants.CALL_FRAME_INTERVAL_SEC)
        else:
            self.fail('Ending chat did not revoke LIVE permission on both peers.')
        self._duplex('chat-ending-call', 0)
        self.sender.client.hangup_call('chat-ending-call')
        ended = self._wait_state('receiver', 'chat-ending-call', CallState.ENDED)
        self.assertIs(ended.reason, CallReason.HUNG_UP)

    def test_cancel_after_remote_acceptance_ends_owned_call_and_releases_transport(
        self,
    ) -> None:
        """A delayed cancellation remains an exact-owner withdrawal after acceptance raced it."""
        call_id = 'accepted-cancel-race'
        self._active_call(call_id)
        self._duplex(call_id, 0)
        self.sender.client.request(
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                notification_privacy=NotificationPrivacy.ANONYMIZE,
            ),
            ClientRestrictedEvent,
        )
        result = self.sender.client.cancel_call(call_id)
        self.assertIsInstance(result, CallStateEvent)
        assert isinstance(result, CallStateEvent)
        self.assertIs(result.call.state, CallState.ENDED)
        self.assertIs(result.call.reason, CallReason.HUNG_UP)
        self.assertEqual((result.call.peer, result.call.alias), ('', ''))
        self.assertIs(
            self._wait_state('receiver', call_id, CallState.ENDED).reason,
            CallReason.HUNG_UP,
        )
        for peer in (self.sender, self.receiver):
            calls = peer.daemon._network.calls
            with calls.lock:
                ended = next(
                    session
                    for session in calls.sessions.values()
                    if session.wire_id == call_id
                )
                self.assertFalse(ended.frames)
                self.assertFalse(calls.keeps_transport(ended.connection))
                deadline = time.monotonic() + Constants.DEFAULT_IPC_TIMEOUT
            while ended.connection.fileno() >= 0 and time.monotonic() < deadline:
                threading.Event().wait(Constants.CALL_FRAME_INTERVAL_SEC)
            self.assertEqual(ended.connection.fileno(), -1)

    def test_owner_loss_and_hard_profile_lock_release_call_resources(self) -> None:
        """Client loss and hard runtime lock revoke consent and release peer streams."""
        self._active_call('client-lost-call')
        self.sender.client.disconnect()
        ended = self._wait_state('receiver', 'client-lost-call', CallState.ENDED)
        self.assertIs(ended.reason, CallReason.CLIENT_LOST)
        self.sender.client = self._client(self.sender.daemon, 'sender')
        self._active_call('profile-lock-call')
        self.sender.client._ipc.send_command(LockCommand())
        ended = self._wait_state('receiver', 'profile-lock-call', CallState.ENDED)
        self.assertIs(ended.reason, CallReason.PROFILE_LOCKED)
        for peer in (self.sender, self.receiver):
            calls = peer.daemon._network.calls if peer.daemon._network else None
            if calls is not None:
                with calls.lock:
                    self.assertTrue(
                        all(not session.frames for session in calls.sessions.values())
                    )

    def test_locked_acceptance_requires_protected_opt_in_and_exact_call(self) -> None:
        """Untrusted restriction flags cannot create protected Call acceptance policy."""
        self.receiver.client.request(
            AddContactCommand(alias='saved-caller', onion=self.sender.onion), IpcEvent
        )
        self.assertIn('saved-caller', self.receiver.contacts.get_all_contacts())
        self.receiver.daemon._pm.config.set(SettingKey.AUTO_ACCEPT_CONTACTS, True)
        self.receiver.client.request(
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                notification_privacy=NotificationPrivacy.ANONYMIZE,
                accept_calls_locked=True,
            ),
            ClientRestrictedEvent,
        )
        self.sender.client.start_call(self.receiver.onion, 'locked-disabled')
        denied_id = self._incoming('receiver', 'locked-disabled')
        data = base64.b64encode(b'\0' * Constants.CALL_FRAME_BYTES).decode()
        self.assertIsInstance(
            self.sender.client.send_call_audio('locked-disabled', 0, data),
            CallRejectedEvent,
        )
        self.assertIsInstance(
            self.receiver.client.request(AcceptCallCommand(denied_id), IpcEvent),
            ClientAccessRestrictedEvent,
        )
        self.receiver.client.reject_call(denied_id)
        self._wait_state('sender', 'locked-disabled', CallState.ENDED)

        self.receiver.client.disconnect()
        self.receiver.client = self._client(self.receiver.daemon, 'receiver')
        preferences = self.receiver.client.request(
            GetGuiPreferencesCommand(), GuiPreferencesEvent
        )
        assert preferences is not None
        self.assertFalse(preferences.preferences.accept_calls_locked)
        updated = self.receiver.client.request(
            SetGuiPreferencesCommand(
                expected_revision=preferences.preferences_revision,
                preferences=replace(preferences.preferences, accept_calls_locked=True),
            ),
            GuiPreferencesEvent,
        )
        assert updated is not None
        self.assertTrue(updated.preferences.accept_calls_locked)
        self.receiver.client.request(
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                notification_privacy=NotificationPrivacy.ANONYMIZE,
                accept_calls_locked=True,
            ),
            ClientRestrictedEvent,
        )
        self.sender.client.start_call(self.receiver.onion, 'locked-enabled')
        accepted_id = self._incoming('receiver', 'locked-enabled')
        accepted = self.receiver.client.accept_call(accepted_id)
        self.assertIsInstance(accepted, CallStateEvent)
        assert isinstance(accepted, CallStateEvent)
        self.assertEqual((accepted.call.peer, accepted.call.alias), ('', ''))
        self.assertTrue(accepted.call.owned)
        self._wait_state('sender', 'locked-enabled', CallState.ACTIVE)
        self._duplex('locked-enabled', 0)
        snapshot = self.sender.client.runtime_snapshot()
        assert snapshot is not None
        self.assertEqual(snapshot.live_contexts, [])
        self.assertEqual(snapshot.pending, [])
        self.receiver.client.hangup_call(accepted_id)
        self._wait_state('sender', 'locked-enabled', CallState.ENDED)
        self.assertIsInstance(
            self.receiver.client.request(AcceptCallCommand(denied_id), IpcEvent),
            CallRejectedEvent,
        )


if __name__ == '__main__':
    unittest.main()
