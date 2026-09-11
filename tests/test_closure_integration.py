"""Closure regressions using real local streams, daemon dispatch and profile stores.

Tor startup/network dialing is controlled; no production profile or peer is used.
"""

# ruff: noqa: E402
import atexit
import base64
import json
import hashlib
import os
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import test_acceptance_repair_contract as support
from metor.application.frontend import create_local_frontend_host
from metor.client import MetorClient
from metor.client.ipc import IpcClient, IpcDisconnectedError, IpcRequestLimitError
from metor.client.session import MetorRequestRejectedError
from metor.client.lifecycle import ProfileRuntimeCoordinator, ProfileSwitchError
from metor.core.api import (
    IpcEvent,
    AckEvent,
    Delivery,
    FallbackSuccessEvent,
    GetRuntimeSnapshotCommand,
    RuntimeSnapshotEvent,
    VoiceFinalizedEvent,
    RestrictClientCommand,
    ClientRestrictedEvent,
    ClientUnlockMethod,
    NotificationPrivacy,
    VoiceIncomingStartedEvent,
    LockedAcceptPolicy,
    IncomingConnectionEvent,
    RejectCommand,
    RuntimeStateChangedEvent,
    DisconnectCommand,
    DisconnectedEvent,
)
from metor.core.key import KeyManager
from metor.core.daemon.managed.engine import Daemon, DaemonLifecycle
from metor.core.daemon.managed.quick_unlock import (
    QuickUnlockStore,
    QuickUnlockStorageError,
)
from metor.core.daemon.managed.network.router.fallback import FallbackRouter
from metor.core.daemon.managed.writer import BoundedSocketWriter
from metor.core.daemon.managed.local_auth import SessionAuthContext
from metor.core.daemon.managed.network.voice import VoiceTransferManager
from metor.core.daemon.managed.network.state import StateTracker
from metor.core.daemon.managed.network.router.admission import FrameAdmission
from metor.data import HistoryManager, SettingKey, MessageDirection
from metor.data.blob import BlobLifecycle, EncryptedBlobStore
from metor.utils import Constants


class ClosureStreamTests(unittest.TestCase):
    """Barriers control socket ownership, not arbitrary scheduling sleeps."""

    def listener(self) -> tuple[socket.socket, IpcClient, socket.socket]:
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(2)
        server.settimeout(2)
        self.addCleanup(server.close)
        client = IpcClient(server.getsockname()[1], 1, lambda e: None, lambda: None)
        self.addCleanup(client.stop)
        self.assertTrue(client.connect())
        peer, _ = server.accept()
        peer.settimeout(1)
        self.addCleanup(peer.close)
        return server, client, peer

    def test_old_send_wait_cleanup_and_overflow_cannot_touch_replacement(self) -> None:
        """F03: an explicit lease binds every exchange phase despite reused IDs."""
        server, client, peer = self.listener()
        old = client.begin_request('same-id')
        with self.assertRaises(IpcRequestLimitError):
            client.begin_request('same-id')
        entered = threading.Event()
        failures = []

        def send_old() -> None:
            entered.set()
            try:
                client.send_command(
                    GetRuntimeSnapshotCommand(request_id='same-id'), old
                )
            except IpcDisconnectedError:
                failures.append('old-send')

        client._send_lock.acquire()
        worker = threading.Thread(target=send_old)
        worker.start()
        self.assertTrue(entered.wait(1))
        replacements: list[bool] = []
        connector = threading.Thread(
            target=lambda: replacements.append(client.connect())
        )
        connector.start()
        connector.join(2)
        self.assertEqual(replacements, [True])
        replacement, _ = server.accept()
        replacement.settimeout(0.1)
        self.addCleanup(replacement.close)
        current = client.begin_request('same-id')
        client._send_lock.release()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, ['old-send'])
        client.end_request('same-id', old)
        client._notify_disconnect(old.generation, sock=peer)
        self.assertIs(client._request_owners['same-id'], current)
        with self.assertRaises(IpcDisconnectedError):
            client.wait_for_response('same-id', old)
        with self.assertRaises(socket.timeout):
            replacement.recv(1)
        response = AckEvent(msg_id='fresh', request_id='same-id')
        replacement.sendall((response.to_json() + '\n').encode())
        self.assertEqual(client.wait_for_response('same-id', current), response)
        client.end_request('same-id', current)

    def test_full_callback_queue_has_unlosable_disconnect_control(self) -> None:
        """F03: a held callback cannot lose loss notification or strand waiters."""
        server, client, peer = self.listener()
        entered, release, lost = threading.Event(), threading.Event(), threading.Event()
        delivered = []

        def callback(event: IpcEvent) -> None:
            entered.set()
            self.assertTrue(release.wait(3))
            delivered.append(event)

        losses = []
        client._on_event = callback
        client._on_disconnect = lambda: (losses.append('lost'), lost.set())
        lease = client.begin_request('pending')
        worker = client._event_thread
        payload = (AckEvent(msg_id='async').to_json() + '\n').encode()
        peer.sendall(payload)
        self.assertTrue(entered.wait(1))
        peer.sendall(payload * (Constants.MAX_CLIENT_EVENT_QUEUE + 1))
        with self.assertRaises(IpcDisconnectedError):
            client.wait_for_response('pending', lease)
        release.set()
        self.assertTrue(lost.wait(3))
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(losses, ['lost'])
        self.assertEqual(len(delivered), Constants.MAX_CLIENT_EVENT_QUEUE + 1)
        self.assertTrue(client.connect())
        replacement, _ = server.accept()
        replacement.close()

    def test_final_frame_drains_before_eof_and_timeout_closes_descriptor(self) -> None:
        """F04: real queued frames retain order and bounded final close ownership."""
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        right.settimeout(2)
        entered, release, exited = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def claim() -> bool:
            entered.set()
            return release.wait(2)

        writer = BoundedSocketWriter(
            left, capacity=8, byte_capacity=1024, on_exit=lambda writer: exited.set()
        )
        writer.enqueue(b'first\n', claim=claim)
        self.assertTrue(entered.wait(1))
        writer.finish(b'DISCONNECT\n', timeout=1)
        release.set()
        received = bytearray()
        while block := right.recv(1024):
            received.extend(block)
        self.assertEqual(received, b'first\nDISCONNECT\n')
        self.assertTrue(exited.wait(1))
        self.assertEqual(left.fileno(), -1)

    def test_blocked_final_drain_deadline_retires_actual_writer_registry(self) -> None:
        """F04: a non-reading peer cannot retain its descriptor/worker past timeout."""
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
        state = StateTracker()
        entered = threading.Event()

        def claimed() -> bool:
            entered.set()
            return True

        state.send_frame(left, b'x' * Constants.MAX_STREAM_BYTES, claimed)
        writer = state._socket_writers[left]
        self.assertTrue(entered.wait(1))
        with patch.object(Constants, 'SOCKET_WRITER_FLUSH_TIMEOUT_SEC', 0.1):
            state.finish_connection(left, b'final-control')
        self.assertTrue(writer._closed.wait(2))
        writer._thread.join(2)
        self.assertFalse(writer._thread.is_alive())
        self.assertEqual(left.fileno(), -1)
        self.assertNotIn(left, state._socket_writers)


class ClosureDaemonTests(unittest.TestCase):
    """Actual IPC commands compose SQL receipts, media, lifecycle and snapshots."""

    def setUp(self) -> None:
        self.fixture = support.AcceptanceRepairContractTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.daemons = []

    def daemon(
        self, sender: bool = True, session_auth: SessionAuthContext | None = None
    ) -> Daemon:
        f = self.fixture
        pm = f.sender_pm if sender else f.receiver_pm
        tor = Mock()
        tor.onion = f.sender_onion if sender else f.receiver_onion
        tor.is_running.return_value = True
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            daemon = Daemon(
                pm,
                KeyManager(pm),
                tor,
                f.sender_contacts if sender else f.receiver_contacts,
                HistoryManager(pm),
                f.sender_messages if sender else f.receiver_messages,
                f.sender_blobs if sender else f.receiver_blobs,
                session_auth=session_auth,
                require_session_auth=session_auth is not None,
            )
        atexit.unregister(daemon.stop)
        self.addCleanup(daemon.stop)
        daemon._ipc.start()
        self.daemons.append(daemon)
        return daemon

    def client(
        self, daemon: Daemon, events: list[IpcEvent] | None = None
    ) -> MetorClient:
        client = MetorClient(
            daemon._ipc.port,
            timeout=2,
            on_event=(events if events is not None else []).append,
        )
        self.addCleanup(client.disconnect)
        self.assertTrue(client.connect())
        self.assertIsNotNone(client.bootstrap())
        return client

    def test_dynamic_public_host_and_real_snapshot(self) -> None:
        """F07/V01: no static-port fixture; host result bootstraps actual daemon."""
        daemon = self.daemon()
        host = create_local_frontend_host(self.fixture.sender_pm, False)
        interactions = Mock()
        result = host.bootstrap(interactions)
        self.assertIsNone(self.fixture.sender_pm.get_static_port())
        self.assertEqual(result.port, daemon._ipc.port)
        self.assertGreater(result.port, 0)
        interactions.confirm_daemon_start.assert_not_called()
        client = self.client(daemon)
        snapshot = client.runtime_snapshot()
        self.assertIsInstance(snapshot, RuntimeSnapshotEvent)
        self.assertEqual(snapshot.profile, 'sender')
        self.assertEqual(snapshot.onion, self.fixture.sender_onion)
        self.assertIsNotNone(snapshot.epoch)
        self.assertIsNotNone(snapshot.revision)
        with self.assertRaises(ValueError):
            result.config.get_int('daemon.max_ipc_clients')
        with self.assertRaises(ValueError):
            result.config.set_client_value('daemon.max_ipc_clients', 1)
        with self.assertRaises(ValueError):
            result.config.set_ui_value('ui.terminal.chat_limit', -1)
        result.config.set_ui_value('ui.terminal.prompt_sign', '>')
        self.assertEqual(
            result.config.get_namespace_str('ui.terminal.prompt_sign'), '>'
        )

    def test_actual_finalize_fallback_progress_then_terminal_result(self) -> None:
        """F03/F05: real producer emits fallback before finalization under one ID."""
        daemon = self.daemon()
        events = []
        client = self.client(daemon, events)
        self.fixture.sender_pm.config.set(SettingKey.FALLBACK_TO_DROP, True)
        peer = self.fixture.receiver_alias
        self.assertIsNotNone(
            client.begin_voice(peer, Delivery.LIVE, 'fallback', 'opus')
        )
        self.assertIsNotNone(
            client.append_voice(
                'fallback', 0, base64.b64encode(b'exact bytes').decode()
            )
        )
        final = client.finalize_voice('fallback', 30)
        self.assertIsInstance(final, VoiceFinalizedEvent)
        self.assertEqual(final.delivery, Delivery.DROP)
        delivered = threading.Event()
        original = client._on_event
        client._on_event = lambda event: (original(event), delivered.set())
        client._ipc.dispatch_async_event(AckEvent(msg_id='barrier'))
        self.assertTrue(delivered.wait(2))
        self.assertEqual(sum(isinstance(e, FallbackSuccessEvent) for e in events), 1)
        self.assertFalse(any(isinstance(e, VoiceFinalizedEvent) for e in events))

    def test_restricted_broadcast_uses_turn_provenance_not_current_peer(self) -> None:
        """F02: actual restriction dispatch and broadcast deny a new same-peer call."""
        daemon = self.daemon()
        events = []
        client = self.client(daemon, events)
        state = daemon._transport_state
        local, peer = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(peer.close)
        onion = self.fixture.receiver_onion
        state.add_active_connection(onion, local)
        self.assertIsNotNone(
            client.begin_voice(onion, Delivery.LIVE, 'old-turn', 'opus')
        )
        restriction = client.request(
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                continued_live_target=onion,
                live_while_locked=True,
                notification_privacy=NotificationPrivacy.SHOW_ALL,
            ),
            ClientRestrictedEvent,
        )
        self.assertIsNotNone(restriction)
        self.assertIsNotNone(
            client.append_voice('old-turn', 0, base64.b64encode(b'authorized').decode())
        )
        old_context = state.get_live_context_generation(onion)
        state.pop_any_connection(onion)
        replacement, replacement_peer = socket.socketpair()
        self.addCleanup(replacement.close)
        self.addCleanup(replacement_peer.close)
        state.add_active_connection(onion, replacement)
        self.assertNotEqual(old_context, state.get_live_context_generation(onion))
        other = self.client(daemon)
        self.assertIsNotNone(
            other.begin_voice(onion, Delivery.LIVE, 'new-turn', 'opus')
        )
        recipient = next(iter(daemon._session_access._restricted))
        event = VoiceIncomingStartedEvent(
            alias='peer',
            onion=onion,
            msg_id='new-turn',
            delivery=Delivery.LIVE,
            codec='opus',
            next_offset=0,
        )
        self.assertIsNone(
            daemon._session_access.filter_restricted_event(recipient, event)
        )
        daemon._broadcast_ipc_event(event)
        with self.assertRaises(MetorRequestRejectedError):
            client.append_voice('old-turn', 10, base64.b64encode(b'denied').decode())
        self.assertFalse(any(isinstance(e, VoiceIncomingStartedEvent) for e in events))

    def test_exact_anonymous_pending_replacement_and_duplicate_handle(self) -> None:
        """F02: actual dispatch token cannot authorize a replacement pending socket."""
        daemon = self.daemon()
        events = []
        client = self.client(daemon, events)
        client.request(
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.NONE,
                notification_privacy=NotificationPrivacy.ANONYMIZE,
                accept_while_locked=LockedAcceptPolicy.ALL,
            ),
            ClientRestrictedEvent,
        )
        onion = self.fixture.receiver_onion
        one, peer = socket.socketpair()
        two, peer_two = socket.socketpair()
        for sock in (one, peer, two, peer_two):
            self.addCleanup(sock.close)
        state = daemon._transport_state
        state.add_pending_connection(onion, one, b'', expiry_deadline=time.time() + 20)
        recipient = next(iter(daemon._session_access._restricted))
        event = IncomingConnectionEvent(alias='peer', onion=onion)
        first = daemon._session_access.filter_restricted_event(recipient, event)
        duplicate = daemon._session_access.filter_restricted_event(recipient, event)
        self.assertEqual(first.action_handle, duplicate.action_handle)
        self.assertIsNotNone(first.action_handle)
        state.pop_pending_connection(onion)
        state.add_pending_connection(onion, two, b'', expiry_deadline=time.time() + 20)
        client.send_command(RejectCommand(first.action_handle))
        # Same stream barrier confirms rejection dispatch has completed.
        with self.assertRaises(MetorRequestRejectedError):
            client.request(RestrictClientCommand(), ClientRestrictedEvent)
        self.assertIs(state.pending_identity(onion)[0], two)

    def test_release_failure_attempts_all_resources_and_retries_stop(self) -> None:
        """F06: actual normal exit fails truthfully, then stop retries all releases."""
        daemon = self.daemon()
        client = self.client(daemon)
        key = daemon._km
        blobs = daemon._blob_store
        with (
            patch(
                'metor.core.daemon.managed.engine.lifecycle.SqlManager.close_connection',
                side_effect=OSError('injected'),
            ) as db,
            patch.object(
                key, 'clear_sensitive_state', wraps=key.clear_sensitive_state
            ) as clear,
            patch.object(blobs, 'close', wraps=blobs.close) as close,
        ):
            with self.assertRaises(MetorRequestRejectedError):
                client.prepare_profile_exit()
            self.assertEqual(daemon._last_runtime_release.failed, ('database',))
            self.assertEqual(daemon._lifecycle, DaemonLifecycle.LOCKING)
            daemon.stop()
            daemon.stop()
            self.assertGreaterEqual(db.call_count, 3)
            self.assertGreaterEqual(clear.call_count, 3)
            self.assertGreaterEqual(close.call_count, 3)
            self.assertFalse(daemon._stop_completed)
            self.assertFalse(daemon._session_access.authenticated_recipients())
        daemon.stop()
        self.assertTrue(daemon._stop_completed)

    def test_external_stop_waits_for_domain_before_claiming_release(self) -> None:
        """F06: external stop cannot invert dispatch's domain/release order."""
        daemon = self.daemon()
        attempted = threading.Event()
        finished = threading.Event()

        def stop() -> None:
            attempted.set()
            daemon.stop()
            finished.set()

        with daemon._domain_operation_lock:
            worker = threading.Thread(target=stop)
            worker.start()
            self.assertTrue(attempted.wait(1))
            self.assertFalse(finished.wait(0.05))
            self.assertTrue(daemon._release_lock.acquire(timeout=1))
            daemon._release_lock.release()
        worker.join(3)
        self.assertTrue(finished.is_set())
        self.assertTrue(daemon._stop_completed)

    def test_inbound_commit_then_raise_reconciles_begin_chunk_and_end(self) -> None:
        """F05: real receipt commits retain bytes and authorize ACKs, never RAM alone."""
        f = self.fixture
        voice = f._voice(sender=False)
        local, peer = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(peer.close)
        peer.settimeout(2)
        queue = f.receiver_messages.queue_message
        update = f.receiver_messages.update_inbound_voice_metadata

        def queue_then_raise(**kwargs: object) -> None:
            self.assertTrue(queue(**kwargs))
            raise OSError('committed begin')

        def update_then_raise(*args: object) -> None:
            self.assertTrue(update(*args))
            raise OSError('committed update')

        with patch.object(f.receiver_messages, 'queue_message', queue_then_raise):
            self.assertIs(
                voice.receive_begin(
                    local,
                    f.sender_onion,
                    {'id': 'inbound-commit', 'codec': 'opus'},
                    Delivery.LIVE,
                ),
                FrameAdmission.ACCEPTED,
            )
        with patch.object(
            f.receiver_messages, 'update_inbound_voice_metadata', update_then_raise
        ):
            self.assertIs(
                voice.receive_chunk(
                    local,
                    f.sender_onion,
                    {
                        'id': 'inbound-commit',
                        'offset': 0,
                        'data': base64.b64encode(b'recoverable').decode(),
                    },
                ),
                FrameAdmission.ACCEPTED,
            )
            self.assertIs(
                voice.receive_end(
                    local,
                    f.sender_onion,
                    {
                        'id': 'inbound-commit',
                        'size': 11,
                        'duration_ms': 20,
                    },
                ),
                FrameAdmission.ACCEPTED,
            )
        record = f.receiver_messages.get_inbound_voice(f.sender_onion, 'inbound-commit')
        metadata = json.loads(record.payload)
        self.assertTrue(metadata['finalized'])
        self.assertEqual(
            f.receiver_blobs.read(metadata['chunk_ids'][0], BlobLifecycle.TEMPORARY),
            b'recoverable',
        )

    def test_no_pending_fallback_does_not_take_unfinalized_drop_draft(self) -> None:
        """F05: other-peer no-op fallback cannot sweep draft ownership."""
        f = self.fixture
        voice = f._voice(sender=True)
        voice.begin(f.receiver_alias, Delivery.DROP, 'draft', 'opus')
        voice.append('draft', 0, base64.b64encode(b'one').decode())
        turn = voice._outbound['draft']
        ids = tuple(turn.chunk_ids)
        router = FallbackRouter(
            f.sender_contacts,
            HistoryManager(f.sender_pm),
            f.sender_messages,
            voice._state,
            lambda e: None,
            f.sender_pm.config,
            promote_voice_callback=voice.promote_fallback,
        )
        unrelated = f.sender_contacts.ensure_alias_for_onion('c' * 56)
        self.assertFalse(router.force_fallback(unrelated)[0])
        self.assertIs(voice._outbound['draft'], turn)
        self.assertFalse(turn.finalized)
        self.assertEqual(f.sender_blobs.read(ids[0], BlobLifecycle.TEMPORARY), b'one')
        voice.append('draft', 3, base64.b64encode(b'two').decode())
        self.assertEqual(turn.size_bytes, 6)

    def test_explicit_partial_fallback_retry_same_process_and_restart(self) -> None:
        """F05: canonical committed selection repairs partial media without new IDs."""
        f = self.fixture
        state = f._voice(sender=True)._state
        local, peer = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(peer.close)
        state.add_active_connection(f.receiver_onion, local)
        for restart in (False, True):
            with self.subTest(restart=restart):
                voice = f._voice(sender=True, state=state)
                msg_id = f'partial-{restart}'
                voice.begin(f.receiver_alias, Delivery.LIVE, msg_id, 'opus')
                voice.append(msg_id, 0, base64.b64encode(b'one').decode())
                voice.append(msg_id, 3, base64.b64encode(b'two').decode())
                voice.finalize(msg_id, 60)
                turn = voice._outbound[msg_id]
                ids = (turn.blob_id, *turn.chunk_ids)

                def router(manager: VoiceTransferManager) -> FallbackRouter:
                    return FallbackRouter(
                        f.sender_contacts,
                        HistoryManager(f.sender_pm),
                        f.sender_messages,
                        state,
                        lambda e: None,
                        f.sender_pm.config,
                        promote_voice_callback=manager.promote_fallback,
                    )

                before = f.sender_messages.get_voice_payload(
                    f.receiver_onion, msg_id, MessageDirection.OUT
                )
                self.assertFalse(
                    router(voice).force_fallback(
                        f.receiver_alias, [msg_id, 'invalid-new-id']
                    )[0]
                )
                self.assertEqual(
                    before,
                    f.sender_messages.get_voice_payload(
                        f.receiver_onion, msg_id, MessageDirection.OUT
                    ),
                )
                promote = f.sender_blobs.promote
                calls = []

                def partial(blob_id: str) -> None:
                    calls.append(blob_id)
                    if len(calls) == 2:
                        raise OSError('injected partial promotion')
                    promote(blob_id)

                with patch.object(f.sender_blobs, 'promote', side_effect=partial):
                    self.assertFalse(
                        router(voice).force_fallback(f.receiver_alias, [msg_id])[0]
                    )
                committed = f.sender_messages.get_voice_payload(
                    f.receiver_onion, msg_id, MessageDirection.OUT
                )
                self.assertEqual(committed.delivery, Delivery.DROP)
                self.assertTrue(json.loads(committed.payload)['fallback_committed'])
                self.assertTrue(f.sender_blobs.exists(ids[0], BlobLifecycle.PERSISTENT))
                if restart:
                    voice = f._voice(sender=True, state=state)
                self.assertTrue(
                    router(voice).force_fallback(f.receiver_alias, [msg_id])[0]
                )
                self.assertEqual(
                    b''.join(
                        f.sender_blobs.read(i, BlobLifecycle.PERSISTENT)
                        for i in ids[1:]
                    ),
                    b'onetwo',
                )
                self.assertEqual(
                    sum(
                        row[4] == msg_id
                        for row in f.sender_messages.get_pending_outbox()
                    ),
                    1,
                )

    def test_ambiguous_append_commit_reconciles_before_blob_rollback(self) -> None:
        """F05: commit-then-raise never deletes canonical retained chunk bytes."""
        f = self.fixture
        voice = f._voice(sender=True)
        voice.begin(f.receiver_alias, Delivery.DROP, 'ambiguous', 'opus')
        update = f.sender_messages.update_retained_bytes

        def committed_then_error(
            onion: str, msg_id: str, size_bytes: int, payload: str
        ) -> bool:
            self.assertTrue(update(onion, msg_id, size_bytes, payload))
            raise OSError('commit outcome initially unknown')

        with patch.object(
            f.sender_messages, 'update_retained_bytes', side_effect=committed_then_error
        ):
            voice.append('ambiguous', 0, base64.b64encode(b'recoverable').decode())
        record = f.sender_messages.get_voice_payload(
            f.receiver_onion, 'ambiguous', MessageDirection.OUT
        )
        chunk = json.loads(record.payload)['chunk_ids'][0]
        self.assertEqual(
            f.sender_blobs.read(chunk, BlobLifecycle.TEMPORARY), b'recoverable'
        )
        self.assertEqual(voice._outbound['ambiguous'].size_bytes, 11)

    def test_actual_profile_switch_a_b_a_preserves_text_voice_off_and_on(self) -> None:
        """V01: actual coordinator, clients, dispatch and stores; controlled Tor only."""
        f = self.fixture
        for fallback in (False, True):
            with self.subTest(fallback=fallback):
                # Reopen encrypted objects with the same isolated test keys after lock.
                root = Path(f._temp.name)
                f.sender_blobs = EncryptedBlobStore(
                    root / 'sender-persistent', root / 'sender-temporary', b's' * 32
                )
                f.receiver_blobs = EncryptedBlobStore(
                    root / 'receiver-persistent', root / 'receiver-temporary', b'r' * 32
                )
                f.sender_pm.config.set(SettingKey.FALLBACK_TO_DROP, fallback)
                source = self.daemon()
                client = self.client(source)
                local, peer = socket.socketpair()
                self.addCleanup(local.close)
                self.addCleanup(peer.close)
                source._transport_state.add_active_connection(f.receiver_onion, local)
                text_id, voice_id = f'text-{fallback}', f'voice-{fallback}'
                client.send_text(
                    f.receiver_alias, Delivery.LIVE, 'pending text', text_id
                )
                self.assertIsNotNone(
                    client.begin_voice(
                        f.receiver_alias, Delivery.LIVE, voice_id, 'opus'
                    )
                )
                client.append_voice(
                    voice_id, 0, base64.b64encode(b'pending voice').decode()
                )
                client.finalize_voice(voice_id, 50)
                targets = []

                def factory(profile: str) -> MetorClient:
                    if profile == 'sender':
                        f.sender_blobs = EncryptedBlobStore(
                            root / 'sender-persistent',
                            root / 'sender-temporary',
                            b's' * 32,
                        )
                    target = self.daemon(sender=profile == 'sender')
                    targets.append(target)
                    candidate = MetorClient(target._ipc.port, timeout=2)
                    self.addCleanup(candidate.disconnect)
                    return candidate

                coordinator = ProfileRuntimeCoordinator(client, factory)
                result = coordinator.switch('receiver')
                self.assertEqual(result.current_snapshot.profile, 'receiver')
                self.assertEqual(source._lifecycle, DaemonLifecycle.LOCKED)
                source.stop()
                result = coordinator.switch('sender')
                self.assertEqual(result.current_snapshot.profile, 'sender')
                self.assertFalse(targets[-1]._transport_state.get_active_onions())
                retained = f.sender_messages.get_voice_payload(
                    f.receiver_onion, voice_id, MessageDirection.OUT
                )
                self.assertEqual(
                    retained.delivery, Delivery.DROP if fallback else Delivery.LIVE
                )
                rows = (
                    f.sender_messages.get_pending_outbox()
                    if fallback
                    else f.sender_messages.get_pending_live_outbox()
                )
                identities = (
                    {row[4] for row in rows}
                    if fallback
                    else {row.msg_id for row in rows}
                )
                self.assertTrue({text_id, voice_id} <= identities)
                # A real locked target fails bootstrap without publishing a candidate.
                failed = self.daemon(sender=False)
                self.assertTrue(failed._lock_runtime())
                coordinator._client_factory = lambda _: MetorClient(
                    failed._ipc.port, timeout=1
                )
                current = coordinator.client
                with self.assertRaises(ProfileSwitchError) as error:
                    coordinator.switch('locked-target')
                self.assertTrue(error.exception.source_released)
                self.assertIs(coordinator.client, current)
                for daemon in self.daemons:
                    daemon.stop()

    def test_actual_snapshot_waits_for_store_mutation_before_publication(self) -> None:
        """V01: real aggregate/store boundary excludes a mutate/restore window."""
        daemon = self.daemon()
        client = self.client(daemon)
        initial = client.runtime_snapshot()
        entered, release, finished = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def mutate() -> None:
            with daemon._domain_operation_lock:
                self.fixture.sender_pm.config.set(SettingKey.FALLBACK_TO_DROP, True)
                public = bytes(range(32))
                onion = (
                    base64.b32encode(
                        public
                        + hashlib.sha3_256(
                            b'.onion checksum' + public + b'\x03'
                        ).digest()[:2]
                        + b'\x03'
                    )
                    .decode()
                    .lower()
                )
                self.assertTrue(
                    self.fixture.sender_contacts.add_contact(
                        'saved-peer', onion
                    ).success
                )
                entered.set()
                self.assertTrue(release.wait(2))
                self.fixture.sender_pm.config.set(SettingKey.FALLBACK_TO_DROP, False)
                daemon._broadcast_ipc_event(RuntimeStateChangedEvent(scope='settings'))

        writer = threading.Thread(target=mutate)
        writer.start()
        self.assertTrue(entered.wait(1))
        snapshots = []

        def collect() -> None:
            snapshots.append(client.runtime_snapshot())
            finished.set()

        reader = threading.Thread(target=collect)
        reader.start()
        self.assertFalse(finished.wait(0.05))
        release.set()
        writer.join(2)
        reader.join(2)
        self.assertTrue(finished.is_set())
        snapshot = snapshots[0]
        self.assertEqual(snapshot.epoch, initial.epoch)
        self.assertGreater(snapshot.revision, initial.revision)
        self.assertTrue(
            any(c.alias == 'saved-peer' and c.saved for c in snapshot.contacts)
        )

    def test_stale_writer_failure_cannot_mutate_replacement_context(self) -> None:
        """F04: pause the real failed writer callback before controller removal."""
        daemon = self.daemon()
        self.client(daemon)
        state = daemon._transport_state
        onion = self.fixture.receiver_onion
        old, old_peer = socket.socketpair()
        new, new_peer = socket.socketpair()
        for sock in (old, old_peer, new, new_peer):
            self.addCleanup(sock.close)
        state.add_active_connection(onion, old)
        entered, release, finished = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def failure(peer: str, failed: socket.socket) -> None:
            entered.set()
            self.assertTrue(release.wait(2))
            daemon._network._controller.disconnect(
                peer, initiated_by_self=False, is_fallback=True, socket_to_close=failed
            )
            finished.set()

        state.set_peer_writer_failure_callback(failure)
        old.shutdown(socket.SHUT_WR)
        state.send_frame(old, b'definitive failed write')
        self.assertTrue(entered.wait(1))
        state.add_active_connection(onion, new)
        context = state.get_live_context_generation(onion)
        revision = daemon._ipc.current_revision()
        release.set()
        self.assertTrue(finished.wait(2))
        self.assertIs(state.get_connection(onion), new)
        self.assertEqual(state.get_live_context_generation(onion), context)
        self.assertFalse(state.has_live_reconnect_grace(onion))
        self.assertEqual(daemon._ipc.current_revision(), revision)
        self.assertNotIn(old, state._socket_writers)
        self.assertEqual(old.fileno(), -1)
        new_peer.settimeout(2)
        state.send_frame(new, b'healthy')
        self.assertEqual(new_peer.recv(7), b'healthy')

    def test_actual_manual_disconnect_orders_final_frame_without_blocking_ipc(
        self,
    ) -> None:
        """F04: actual command dispatch queues final control before socket EOF."""
        daemon = self.daemon()
        client = self.client(daemon)
        other = self.client(daemon)
        local, peer = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(peer.close)
        peer.settimeout(2)
        state = daemon._transport_state
        onion = self.fixture.receiver_onion
        state.add_active_connection(onion, local)
        entered, release = threading.Event(), threading.Event()

        def claimed() -> bool:
            entered.set()
            return release.wait(2)

        state.send_frame(local, b'prior\n', claimed)
        self.assertTrue(entered.wait(1))
        result = client.request(DisconnectCommand(onion), DisconnectedEvent)
        self.assertIsNotNone(result)
        self.assertIsNotNone(other.runtime_snapshot())
        release.set()
        data = bytearray()
        while block := peer.recv(4096):
            data.extend(block)
        self.assertTrue(data.startswith(b'prior\n/disconnect '), data)
        self.assertIn(b'manual', data.lower())


class ClosureCredentialTests(unittest.TestCase):
    """Executes effective native protection, including Unicode/space replacement."""

    def test_native_credential_configure_verify_replace_invalid_remove(self) -> None:
        with TemporaryDirectory(prefix='metor closure ü ') as root:
            path = Path(root) / 'private ü' / 'pin.json'
            store = QuickUnlockStore(path)
            salt, verifier = '01' * 16, '02' * 32
            store.configure(salt, verifier)
            self.assertEqual(store.metadata(), (salt, bytes.fromhex(verifier)))
            import hmac

            challenge = '03' * 32
            proof = hmac.new(
                bytes.fromhex(verifier), bytes.fromhex(challenge), 'sha256'
            ).hexdigest()
            self.assertTrue(store.verify(challenge, proof))
            store.configure('04' * 16, '05' * 32)
            self.assertFalse(store.verify(challenge, proof))
            self.assertEqual(store.metadata(), ('04' * 16, bytes.fromhex('05' * 32)))
            if os.name == 'nt':
                store._validate_windows_acl(path)
                store._validate_windows_acl(path.parent)
                store._run_acl_helper(
                    path,
                    '$acl=[System.IO.File]::GetAccessControl($Target); '
                    '$sid=New-Object System.Security.Principal.SecurityIdentifier("S-1-1-0"); '
                    '$rule=New-Object System.Security.AccessControl.FileSystemAccessRule($sid,"Read","Allow"); '
                    '$acl.AddAccessRule($rule); [System.IO.File]::SetAccessControl($Target,$acl)',
                    'test-unsafe-trustee',
                )
                with self.assertRaises(QuickUnlockStorageError):
                    store.metadata()
                store._protect_windows_path(path, directory=False)
                with patch.object(
                    QuickUnlockStore,
                    '_protect_windows_path',
                    side_effect=QuickUnlockStorageError('test protection failure'),
                ):
                    with self.assertRaises(QuickUnlockStorageError):
                        store.configure('06' * 16, '07' * 32)
                self.assertEqual(
                    store.metadata(), ('04' * 16, bytes.fromhex('05' * 32))
                )
            with path.open('w', encoding='utf-8') as handle:
                handle.write('{"version":999}')
            with self.assertRaises(QuickUnlockStorageError):
                store.metadata()
            store.remove()
            self.assertIsNone(store.metadata())


if __name__ == '__main__':
    unittest.main()
