"""End-to-end regressions for the Core/client/Terminal acceptance repairs."""

# ruff: noqa: E402

import base64
import json
import socket
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import (
    BeginVoiceCommand,
    ClientUnlockMethod,
    ContentType,
    Delivery,
    EventType,
    GetVoiceChunkCommand,
    IpcEvent,
    MarkReadCommand,
    MessageDirectionCode,
    NotificationPrivacy,
    ReleaseVoiceCommand,
    RestrictClientCommand,
    RuntimeStateChangedEvent,
    VoiceDataEvent,
    VoiceReleasedEvent,
    request_context,
)
from metor.core.daemon.handlers.db import DatabaseCommandHandler
from metor.core.daemon.managed.engine.session_access import SessionAccessController
from metor.core.daemon.managed.models import TorCommand
from metor.core.daemon.managed.handlers.network import NetworkCommandHandler
from metor.core.daemon.managed.network.router import MessageRouter
from metor.core.daemon.managed.network.router.admission import FrameAdmission
from metor.core.daemon.managed.network.state import StateTracker
from metor.core.daemon.managed.network.stream import TcpStreamReader
from metor.core.daemon.managed.network.voice import VoiceTransferManager
from metor.core.daemon.managed.outbox.delivery import (
    DropDelivery,
    is_expected_voice_commit_line,
)
from metor.data import (
    ContactManager,
    HistoryManager,
    MessageDirection,
    MessageManager,
    MessageStatus,
    PendingLiveAdmission,
    SettingKey,
)
from metor.data.blob import BlobLifecycle, EncryptedBlobStore
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.utils import Constants


class _VoiceSocket:
    """Socket-shaped frame collector for direct manager tests."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def sendall(self, payload: bytes) -> None:
        """Records one serialized application frame."""
        self.sent.append(payload)


class _ContendedWriter:
    """Amplifies interleaving risk while recording writes byte by byte."""

    def __init__(self) -> None:
        self.data = bytearray()

    def sendall(self, payload: bytes) -> None:
        """Records a deliberately partial logical write."""
        for value in payload:
            self.data.append(value)


class _ObservedFence:
    """Event-shaped purge fence exposing the first guard check to a test."""

    def __init__(self) -> None:
        self.value = False
        self.checked = threading.Event()

    def is_set(self) -> bool:
        """Records guard observation and returns current fence state."""
        self.checked.set()
        return self.value

    def set(self) -> None:
        """Raises the destructive lifecycle fence."""
        self.value = True


class _BlockingSocket(_VoiceSocket):
    """Socket-shaped writer held by explicit synchronization events."""

    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        super().__init__()
        self._entered = entered
        self._release = release

    def sendall(self, payload: bytes) -> None:
        """Blocks one peer write until the test releases it."""
        self._entered.set()
        self._release.wait(timeout=2.0)
        super().sendall(payload)


class AcceptanceRepairContractTests(unittest.TestCase):
    """Covers the critical media, identity, quota, and framing gates."""

    def setUp(self) -> None:
        """Builds two isolated profiles with encrypted segmented blob stores."""
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        self._data_patch = patch.object(Constants, 'DATA', root / Constants.DATA_DIR)
        self._data_patch.start()
        self.addCleanup(self._data_patch.stop)
        self.sender_pm = ProfileManager('sender')
        self.receiver_pm = ProfileManager('receiver')
        self.sender_pm.initialize()
        self.receiver_pm.initialize()
        self.sender_contacts = ContactManager(self.sender_pm)
        self.receiver_contacts = ContactManager(self.receiver_pm)
        self.sender_messages = MessageManager(self.sender_pm)
        self.receiver_messages = MessageManager(self.receiver_pm)
        self.sender_onion = 'a' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        self.receiver_onion = 'b' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        self.receiver_alias = self.sender_contacts.ensure_alias_for_onion(
            self.receiver_onion
        )
        self.receiver_contacts.ensure_alias_for_onion(self.sender_onion)
        assert self.receiver_alias is not None
        self.sender_blobs = EncryptedBlobStore(
            root / 'sender-persistent', root / 'sender-temporary', b's' * 32
        )
        self.receiver_blobs = EncryptedBlobStore(
            root / 'receiver-persistent', root / 'receiver-temporary', b'r' * 32
        )
        self.addCleanup(self.sender_blobs.close)
        self.addCleanup(self.receiver_blobs.close)
        self.addCleanup(SqlManager.close_connection, self.sender_pm.paths.get_db_file())
        self.addCleanup(
            SqlManager.close_connection, self.receiver_pm.paths.get_db_file()
        )

    def _voice(
        self,
        *,
        sender: bool,
        state: StateTracker | None = None,
        events: list[object] | None = None,
    ) -> VoiceTransferManager:
        """Constructs one manager over the selected encrypted profile."""
        return VoiceTransferManager(
            contacts=self.sender_contacts if sender else self.receiver_contacts,
            messages=self.sender_messages if sender else self.receiver_messages,
            blobs=self.sender_blobs if sender else self.receiver_blobs,
            state=state or StateTracker(),
            broadcast=(events if events is not None else []).append,
            config=self.sender_pm.config if sender else self.receiver_pm.config,
        )

    def _send_drop_voice_over_socketpair(self, msg_id: str, payload: bytes) -> None:
        """Runs the real DROP sender and receiver framing paths once."""
        sender_voice = self._voice(sender=True)
        sender_voice.begin(self.receiver_alias, Delivery.DROP, msg_id, 'opus')
        if payload:
            sender_voice.append(msg_id, 0, base64.b64encode(payload).decode('ascii'))
        sender_voice.finalize(msg_id, 250)
        self.assertTrue(sender_voice.commit_draft(self.receiver_alias, msg_id))
        row = next(
            row for row in self.sender_messages.get_pending_outbox() if row[4] == msg_id
        )

        receiver_voice = self._voice(sender=False)
        sender_socket, receiver_socket = socket.socketpair()
        self.addCleanup(sender_socket.close)
        self.addCleanup(receiver_socket.close)
        sender_socket.settimeout(2.0)
        receiver_socket.settimeout(2.0)
        receiver_outcomes: list[FrameAdmission] = []
        receiver_errors: list[BaseException] = []

        def receive_frames() -> None:
            """Consumes BEGIN/CHUNK/END using the production stream decoder."""
            try:
                stream = TcpStreamReader(receiver_socket)
                while True:
                    line = stream.read_line()
                    if line is None:
                        raise ConnectionError('DROP Voice stream ended early.')
                    command, encoded = line.split(' ', 1)
                    decoded = receiver_voice.decode_wire_payload(encoded)
                    if decoded is None:
                        raise ValueError('Invalid Voice envelope.')
                    if command == TorCommand.DROP_VOICE_BEGIN.value:
                        outcome = receiver_voice.receive_begin(
                            receiver_socket,
                            self.sender_onion,
                            decoded,
                            Delivery.DROP,
                        )
                    elif command == TorCommand.DROP_VOICE_CHUNK.value:
                        outcome = receiver_voice.receive_chunk(
                            receiver_socket, self.sender_onion, decoded
                        )
                    elif command == TorCommand.DROP_VOICE_END.value:
                        outcome = receiver_voice.receive_end(
                            receiver_socket, self.sender_onion, decoded
                        )
                        receiver_outcomes.append(outcome)
                        return
                    else:
                        raise ValueError('Unexpected Voice command.')
                    receiver_outcomes.append(outcome)
            except BaseException as exc:  # pragma: no cover - asserted in caller
                receiver_errors.append(exc)

        receiver_thread = threading.Thread(target=receive_frames)
        receiver_thread.start()
        delivery = DropDelivery(
            mm=self.sender_messages,
            hm=Mock(),
            state=StateTracker(),
            tunnels=Mock(),
            broadcast_callback=lambda _event: None,
            stop_flag=threading.Event(),
            config=self.sender_pm.config,
            blob_store=self.sender_blobs,
        )
        sender_stream = TcpStreamReader(sender_socket)
        early_ack = delivery._send_drop_row(sender_socket, sender_stream, row)
        final_ack = early_ack or sender_stream.read_line()
        receiver_thread.join(timeout=2.0)

        self.assertFalse(receiver_thread.is_alive())
        self.assertEqual(receiver_errors, [])
        self.assertTrue(
            all(outcome is FrameAdmission.ACCEPTED for outcome in receiver_outcomes)
        )
        self.assertTrue(is_expected_voice_commit_line(msg_id, final_ack))
        record = self.receiver_messages.get_voice_payload(
            self.sender_onion, msg_id, MessageDirection.IN
        )
        self.assertIsNotNone(record)
        assert record is not None
        content, delivery_type, data, next_offset, complete, reason = (
            receiver_voice.read_chunk(
                self.sender_onion,
                msg_id,
                MessageDirection.IN,
                0,
                Constants.VOICE_CHUNK_MAX_BYTES,
            )
        )
        self.assertIsNone(reason)
        self.assertIs(delivery_type, Delivery.DROP)
        self.assertEqual(data, payload)
        self.assertEqual(next_offset, len(payload))
        self.assertTrue(complete)
        self.assertEqual(content.size_bytes if content else None, len(payload))

    def test_fresh_drop_voice_completes_first_attempt_empty_and_nonempty(self) -> None:
        """G01: every fresh BEGIN receives offset zero and reaches commit ACK."""
        self._send_drop_voice_over_socketpair('drop-nonempty', b'first attempt')
        self._send_drop_voice_over_socketpair('drop-empty', b'')

    def test_progress_ack_never_releases_before_terminal_commit(self) -> None:
        """G03/G04: chunk progress and terminal commit remain independent."""
        state = StateTracker()
        conn_obj = _VoiceSocket()
        conn = cast(socket.socket, conn_obj)
        state.add_active_connection(self.receiver_onion, conn)
        voice = self._voice(sender=True, state=state)
        voice.begin(self.receiver_alias, Delivery.LIVE, 'live-ack', 'opus')
        voice.append('live-ack', 0, base64.b64encode(b'abc').decode('ascii'))
        voice.finalize('live-ack', 10)

        voice.acknowledge(self.receiver_onion, 'live-ack', 3)
        sent_count = len(conn_obj.sent)
        voice.acknowledge(self.receiver_onion, 'live-ack', 1)
        voice.acknowledge(self.receiver_onion, 'live-ack', 4)
        self.assertEqual(len(conn_obj.sent), sent_count)
        self.assertEqual(voice.outbound_target('live-ack'), self.receiver_onion)
        self.assertEqual(
            len(self.sender_messages.get_pending_live_outbox(self.receiver_onion)), 1
        )
        voice.acknowledge_complete(self.receiver_onion, 'live-ack')
        self.assertIsNone(voice.outbound_target('live-ack'))

    def test_common_replay_keeps_text_and_voice_frames_typed(self) -> None:
        """G02: the common reconnect dispatcher never emits Voice metadata as MSG."""
        state = StateTracker()
        conn_obj = _VoiceSocket()
        conn = cast(socket.socket, conn_obj)
        state.add_active_connection(self.receiver_onion, conn)
        router = MessageRouter(
            cm=self.sender_contacts,
            hm=HistoryManager(self.sender_pm),
            mm=self.sender_messages,
            state=state,
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: True,
            has_live_consumers_callback=lambda: True,
            notify_callback=lambda _payload: None,
            config=self.sender_pm.config,
            blob_store=self.sender_blobs,
        )
        router.send_message(self.receiver_alias, 'text', 'typed-text')
        router.begin_voice(self.receiver_alias, Delivery.LIVE, 'typed-voice', 'opus')
        conn_obj.sent.clear()

        replayed = router.replay_unacked_messages(self.receiver_onion)

        self.assertCountEqual(replayed, ['typed-text', 'typed-voice'])
        self.assertTrue(
            any(frame.startswith(b'/msg typed-text ') for frame in conn_obj.sent)
        )
        self.assertFalse(
            any(frame.startswith(b'/msg typed-voice ') for frame in conn_obj.sent)
        )
        self.assertTrue(
            any(frame.startswith(b'/voice_begin ') for frame in conn_obj.sent)
        )

    def test_duplicate_chunk_is_idempotent_but_conflict_is_malformed(self) -> None:
        """G03: reconnect duplicates preserve exact retained bytes."""
        voice = self._voice(sender=False)
        conn_obj = _VoiceSocket()
        conn = cast(socket.socket, conn_obj)
        begin = {'id': 'duplicate', 'codec': 'opus'}
        chunk = base64.b64encode(b'abc').decode('ascii')
        self.assertIs(
            voice.receive_begin(conn, self.sender_onion, begin),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            voice.receive_chunk(
                conn,
                self.sender_onion,
                {'id': 'duplicate', 'offset': 0, 'data': chunk},
            ),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            voice.receive_begin(conn, self.sender_onion, begin),
            FrameAdmission.ACCEPTED,
        )
        self.assertEqual(
            conn_obj.sent[-1],
            f'{TorCommand.VOICE_ACK.value} duplicate 3\n'.encode('ascii'),
        )
        self.assertIs(
            voice.receive_chunk(
                conn,
                self.sender_onion,
                {'id': 'duplicate', 'offset': 0, 'data': chunk},
            ),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            voice.receive_chunk(
                conn,
                self.sender_onion,
                {
                    'id': 'duplicate',
                    'offset': 0,
                    'data': base64.b64encode(b'xyz').decode('ascii'),
                },
            ),
            FrameAdmission.MALFORMED,
        )

    def test_duplicate_end_repeats_terminal_commit_ack(self) -> None:
        """G04: a lost END response is recovered without recreating content."""
        voice = self._voice(sender=False)
        conn_obj = _VoiceSocket()
        conn = cast(socket.socket, conn_obj)
        begin = {'id': 'repeat-end', 'codec': 'opus'}
        chunk = {
            'id': 'repeat-end',
            'offset': 0,
            'data': base64.b64encode(b'complete').decode('ascii'),
        }
        end = {'id': 'repeat-end', 'size': 8, 'duration_ms': 50}
        self.assertIs(
            voice.receive_begin(conn, self.sender_onion, begin),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            voice.receive_chunk(conn, self.sender_onion, chunk),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            voice.receive_end(conn, self.sender_onion, end),
            FrameAdmission.ACCEPTED,
        )
        commit = f'{TorCommand.VOICE_COMMIT_ACK.value} repeat-end\n'.encode('ascii')
        self.assertEqual(conn_obj.sent[-1], commit)
        self.assertIs(
            voice.receive_end(conn, self.sender_onion, end),
            FrameAdmission.ACCEPTED,
        )
        self.assertEqual(conn_obj.sent[-1], commit)

    def test_partial_live_promotes_to_drop_with_same_identity_and_full_bytes(
        self,
    ) -> None:
        """G05/G06: receiver promotion strengthens one identity in place."""
        voice = self._voice(sender=False)
        conn = cast(socket.socket, _VoiceSocket())
        begin = {'id': 'same-id', 'codec': 'opus'}
        first = base64.b64encode(b'abc').decode('ascii')
        second = base64.b64encode(b'def').decode('ascii')
        self.assertFalse(voice.receive_begin(conn, self.sender_onion, begin))
        self.assertFalse(
            voice.receive_chunk(
                conn,
                self.sender_onion,
                {'id': 'same-id', 'offset': 0, 'data': first},
            )
        )
        self.assertFalse(
            voice.receive_begin(conn, self.sender_onion, begin, delivery=Delivery.DROP)
        )
        self.assertFalse(
            voice.receive_chunk(
                conn,
                self.sender_onion,
                {'id': 'same-id', 'offset': 3, 'data': second},
            )
        )
        self.assertFalse(
            voice.receive_end(conn, self.sender_onion, {'id': 'same-id', 'size': 6})
        )
        record = self.receiver_messages.get_voice_payload(
            self.sender_onion, 'same-id', MessageDirection.IN
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.delivery, Delivery.DROP.value)
        read = voice.read_chunk(
            self.sender_onion,
            'same-id',
            MessageDirection.IN,
            0,
            Constants.VOICE_CHUNK_MAX_BYTES,
        )
        self.assertEqual(read[2], b'abcdef')
        self.assertTrue(read[4])

    def test_interrupted_encrypted_blob_promotion_reconciles_on_restart(self) -> None:
        """G07: committed DROP metadata recovers interrupted object ownership."""
        original_promote = self.sender_blobs.promote
        for failure_index in (0, 1):
            with self.subTest(failure_index=failure_index):
                msg_id = f'crash-boundary-{failure_index}'
                voice = self._voice(sender=True)
                voice.begin(self.receiver_alias, Delivery.LIVE, msg_id, 'opus')
                voice.append(msg_id, 0, base64.b64encode(b'encrypted').decode('ascii'))
                calls = 0

                def fail_selected_promotion(blob_id: str) -> None:
                    """Fails exactly one ordered object-ownership transition."""
                    nonlocal calls
                    current = calls
                    calls += 1
                    if current == failure_index:
                        raise OSError('crash')
                    original_promote(blob_id)

                with patch.object(
                    self.sender_blobs,
                    'promote',
                    side_effect=fail_selected_promotion,
                ):
                    with self.assertRaises(OSError):
                        voice.finalize(msg_id, 50)

                row = next(
                    row
                    for row in self.sender_messages.get_pending_outbox()
                    if row[4] == msg_id
                )
                metadata = json.loads(row[3])
                blob_ids = [metadata['blob_id'], *metadata['chunk_ids']]
                self.assertTrue(
                    any(
                        self.sender_blobs.exists(blob_id, BlobLifecycle.TEMPORARY)
                        for blob_id in blob_ids
                    )
                )

                self._voice(sender=True)

                self.assertTrue(
                    all(
                        self.sender_blobs.exists(blob_id, BlobLifecycle.PERSISTENT)
                        for blob_id in blob_ids
                    )
                )

    def test_stale_live_ack_waits_behind_atomic_fallback_transition(self) -> None:
        """G06: a delayed text ACK cannot complete an already-promoted DROP."""
        state = StateTracker()
        state.mark_scheduled_auto_reconnect(self.receiver_onion)
        router = MessageRouter(
            cm=self.sender_contacts,
            hm=HistoryManager(self.sender_pm),
            mm=self.sender_messages,
            state=state,
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: True,
            has_live_consumers_callback=lambda: True,
            notify_callback=lambda _payload: None,
            config=self.sender_pm.config,
            blob_store=self.sender_blobs,
        )
        router.send_message(self.receiver_alias, 'retain me', 'fallback-race')
        entered = threading.Event()
        release = threading.Event()
        original_promote = self.sender_messages.promote_pending_live_to_drop

        def block_after_lock(*args: object, **kwargs: object) -> object:
            """Holds fallback while a stale ACK queues on the same barrier."""
            entered.set()
            release.wait(timeout=2.0)
            return original_promote(*args, **kwargs)  # type: ignore[arg-type]

        with patch.object(
            self.sender_messages,
            'promote_pending_live_to_drop',
            side_effect=block_after_lock,
        ):
            fallback = threading.Thread(
                target=router.force_fallback,
                args=(self.receiver_alias, ['fallback-race']),
            )
            fallback.start()
            self.assertTrue(entered.wait(timeout=1.0))
            stale_ack = threading.Thread(
                target=router.process_incoming_ack,
                args=(self.receiver_onion, 'fallback-race'),
            )
            stale_ack.start()
            release.set()
            fallback.join(timeout=1.0)
            stale_ack.join(timeout=1.0)

        self.assertFalse(fallback.is_alive())
        self.assertFalse(stale_ack.is_alive())
        self.assertEqual(self.sender_messages.get_pending_live_outbox(), [])
        self.assertEqual(
            [row[4] for row in self.sender_messages.get_pending_outbox()],
            ['fallback-race'],
        )

    def test_interrupted_drop_draft_promotion_reconciles_before_review(self) -> None:
        """G07: finalized draft objects recover before bounded client reads."""
        voice = self._voice(sender=True)
        voice.begin(self.receiver_alias, Delivery.DROP, 'draft-crash', 'opus')
        voice.append('draft-crash', 0, base64.b64encode(b'reviewable').decode('ascii'))
        with patch.object(self.sender_blobs, 'promote', side_effect=OSError('crash')):
            with self.assertRaises(OSError):
                voice.finalize('draft-crash', 70)
        self.assertEqual(len(self.sender_messages.get_voice_draft_payloads()), 1)

        recovered = self._voice(sender=True)
        read = recovered.read_chunk(
            self.receiver_onion,
            'draft-crash',
            MessageDirection.OUT,
            0,
            Constants.VOICE_CHUNK_MAX_BYTES,
        )

        self.assertEqual(read[2], b'reviewable')
        self.assertTrue(read[4])
        self.assertTrue(recovered.cancel_draft(self.receiver_alias, 'draft-crash'))

    def test_text_consume_and_live_dismiss_preserve_other_voice_state(self) -> None:
        """G09-G11: peer-wide text actions cannot destroy active media."""
        voice = self._voice(sender=False)
        conn = cast(socket.socket, _VoiceSocket())
        self.assertFalse(
            voice.receive_begin(
                conn, self.sender_onion, {'id': 'live-mixed', 'codec': 'opus'}
            )
        )
        self.assertFalse(
            voice.receive_chunk(
                conn,
                self.sender_onion,
                {
                    'id': 'live-mixed',
                    'offset': 0,
                    'data': base64.b64encode(b'a').decode('ascii'),
                },
            )
        )
        self.receiver_messages.queue_message(
            self.sender_onion,
            MessageDirection.IN,
            Delivery.LIVE,
            ContentType.TEXT,
            'text',
            MessageStatus.UNREAD,
            msg_id='text-mixed',
        )
        consumed = self.receiver_messages.get_and_read_inbox(
            self.sender_onion, Delivery.LIVE
        )
        self.assertEqual([row[4] for row in consumed], ['text-mixed'])
        self.assertFalse(
            voice.receive_chunk(
                conn,
                self.sender_onion,
                {
                    'id': 'live-mixed',
                    'offset': 1,
                    'data': base64.b64encode(b'b').decode('ascii'),
                },
            )
        )

        self.assertFalse(
            voice.receive_begin(
                conn,
                self.sender_onion,
                {'id': 'drop-mixed', 'codec': 'opus'},
                Delivery.DROP,
            )
        )
        voice.dismiss_inbound(self.sender_onion)
        self.assertFalse(
            voice.receive_chunk(
                conn,
                self.sender_onion,
                {
                    'id': 'drop-mixed',
                    'offset': 0,
                    'data': base64.b64encode(b'drop').decode('ascii'),
                },
            )
        )

    def test_public_bounded_read_precedes_explicit_release(self) -> None:
        """G08/G09: a reattached client obtains bytes before consuming them."""
        voice = self._voice(sender=False)
        conn = cast(socket.socket, _VoiceSocket())
        self.assertFalse(
            voice.receive_begin(
                conn, self.sender_onion, {'id': 'reattach', 'codec': 'opus'}
            )
        )
        self.assertFalse(
            voice.receive_chunk(
                conn,
                self.sender_onion,
                {
                    'id': 'reattach',
                    'offset': 0,
                    'data': base64.b64encode(b'play me').decode('ascii'),
                },
            )
        )
        self.assertFalse(
            voice.receive_end(conn, self.sender_onion, {'id': 'reattach', 'size': 7})
        )

        class _NetworkBoundary:
            """Exposes the manager through the NetworkManager-shaped API."""

            def read_voice_chunk(self, *args: object) -> object:
                """Delegates one bounded read."""
                return voice.read_chunk(*args)  # type: ignore[arg-type]

            def release_inbound_voice_item(self, onion: str, msg_id: str) -> bool:
                """Delegates one explicit release."""
                return voice.release_inbound(onion, msg_id)

        events: list[IpcEvent] = []
        broadcasts: list[IpcEvent] = []
        handler = object.__new__(NetworkCommandHandler)
        handler._cm = self.receiver_contacts
        handler._network = cast(object, _NetworkBoundary())
        handler._send_to = lambda _conn, event: events.append(event)
        handler._broadcast = broadcasts.append
        request_conn = cast(socket.socket, object())

        handler.handle(
            GetVoiceChunkCommand(
                self.sender_onion,
                'reattach',
                MessageDirectionCode.IN,
                0,
                64,
            ),
            request_conn,
        )
        self.assertIsInstance(events[-1], VoiceDataEvent)
        self.assertEqual(
            base64.b64decode(cast(VoiceDataEvent, events[-1]).data), b'play me'
        )
        self.assertIsNotNone(
            self.receiver_messages.get_voice_payload(
                self.sender_onion, 'reattach', MessageDirection.IN
            )
        )

        handler.handle(ReleaseVoiceCommand(self.sender_onion, 'reattach'), request_conn)
        self.assertIsInstance(events[-1], VoiceReleasedEvent)
        self.assertEqual(len(broadcasts), 1)
        self.assertIsNone(
            self.receiver_messages.get_inbound_voice(self.sender_onion, 'reattach')
        )

    def test_drop_disabled_rejects_voice_before_receipt_on_session(self) -> None:
        """G15: session-carried DROP Voice uses the common DROP policy."""
        original_get_bool = self.receiver_pm.config.get_bool

        def get_bool(key: SettingKey) -> bool:
            """Disables inbound DROP while preserving unrelated settings."""
            if key is SettingKey.ALLOW_DROPS:
                return False
            return original_get_bool(key)

        with patch.object(self.receiver_pm.config, 'get_bool', side_effect=get_bool):
            router = MessageRouter(
                cm=self.receiver_contacts,
                hm=HistoryManager(self.receiver_pm),
                mm=self.receiver_messages,
                state=StateTracker(),
                broadcast_callback=lambda _event: None,
                has_clients_callback=lambda: False,
                has_live_consumers_callback=lambda: False,
                notify_callback=lambda _payload: None,
                config=self.receiver_pm.config,
                blob_store=self.receiver_blobs,
            )
            envelope = base64.b64encode(
                json.dumps({'id': 'disabled-drop', 'codec': 'opus'}).encode('utf-8')
            ).decode('ascii')
            outcome = router.process_drop_voice_frame(
                cast(socket.socket, _VoiceSocket()),
                self.sender_onion,
                TorCommand.DROP_VOICE_BEGIN.value,
                envelope,
            )
            tunnel_conn = Mock()
            tunnel_stream = Mock()
            tunnel_stream.read_line.return_value = (
                f'{TorCommand.DROP_VOICE_BEGIN.value} {envelope}'
            )
            router.process_async_drop(
                cast(socket.socket, tunnel_conn),
                cast(TcpStreamReader, tunnel_stream),
                self.sender_onion,
            )

        self.assertIs(outcome, FrameAdmission.POLICY_REJECTED)
        tunnel_stream.read_line.assert_not_called()
        tunnel_conn.close.assert_called_once_with()
        self.assertIsNone(
            self.receiver_messages.get_inbound_voice(self.sender_onion, 'disabled-drop')
        )

        sent: list[IpcEvent] = []
        handler = object.__new__(NetworkCommandHandler)
        handler._config = self.receiver_pm.config
        handler._send_to = lambda _conn, event: sent.append(event)
        handler._network = Mock()
        handler._cm = self.receiver_contacts
        handler._tm = Mock(onion=self.receiver_onion)
        handler._is_self_target = lambda _target: False
        with patch.object(self.receiver_pm.config, 'get_bool', side_effect=get_bool):
            handler.handle(
                BeginVoiceCommand(
                    self.sender_onion, Delivery.DROP, 'local-disabled', 'opus'
                ),
                cast(socket.socket, object()),
            )
        self.assertIs(sent[-1].event_type, EventType.DROPS_DISABLED)
        handler._network.begin_voice.assert_not_called()

    def test_atomic_mixed_pending_count_quota_admits_only_one(self) -> None:
        """G12: text and Voice share one transactional admission ceiling."""
        barrier = threading.Barrier(3)
        outcomes: list[PendingLiveAdmission] = []

        def admit(content_type: ContentType, msg_id: str) -> None:
            """Attempts one simultaneous mixed-content reservation."""
            barrier.wait()
            outcomes.append(
                self.sender_messages.queue_pending_live_if_capacity(
                    self.receiver_onion,
                    content_type,
                    '{}' if content_type is ContentType.VOICE else 'x',
                    msg_id,
                    '2026-09-11T00:00:00+00:00',
                    0,
                    1,
                    1024,
                )
            )

        first = threading.Thread(target=admit, args=(ContentType.TEXT, 'quota-text'))
        second = threading.Thread(target=admit, args=(ContentType.VOICE, 'quota-voice'))
        first.start()
        second.start()
        barrier.wait()
        first.join()
        second.join()

        self.assertCountEqual(
            outcomes,
            [PendingLiveAdmission.ACCEPTED, PendingLiveAdmission.COUNT_LIMIT],
        )

    def test_voice_byte_quota_rejects_growth_without_partial_storage(self) -> None:
        """G12: pending byte admission rolls back the just-written segment."""
        original_get_int = self.sender_pm.config.get_int

        def get_int(key: SettingKey) -> int:
            """Overrides only the shared pending LIVE byte ceiling."""
            if key is SettingKey.MAX_PENDING_LIVE_BYTES:
                return 2
            return original_get_int(key)

        with patch.object(self.sender_pm.config, 'get_int', side_effect=get_int):
            voice = self._voice(sender=True)
            voice.begin(self.receiver_alias, Delivery.LIVE, 'byte-limit', 'opus')
            voice.append('byte-limit', 0, base64.b64encode(b'abc').decode('ascii'))
        record = self.sender_messages.get_voice_payload(
            self.receiver_onion, 'byte-limit', MessageDirection.OUT
        )
        self.assertIsNotNone(record)
        assert record is not None
        metadata = json.loads(record.payload)
        self.assertEqual(metadata['size_bytes'], 0)
        self.assertEqual(metadata['chunk_ids'], [])

    def test_segment_storage_is_linear_and_socket_frames_do_not_interleave(
        self,
    ) -> None:
        """G13/G14: chunks are append-only objects and writers serialize frames."""
        state = StateTracker()
        voice = self._voice(sender=True, state=state)
        with patch.object(self.sender_blobs, 'put', wraps=self.sender_blobs.put) as put:
            voice.begin(self.receiver_alias, Delivery.DROP, 'linear', 'opus')
            for index in range(3):
                voice.append(
                    'linear',
                    index * 2,
                    base64.b64encode(b'aa').decode('ascii'),
                )
        self.assertEqual(
            [len(call.args[0]) for call in put.call_args_list], [0, 2, 2, 2]
        )

        writer = cast(socket.socket, _ContendedWriter())
        start = threading.Barrier(3)

        def send(frame: bytes) -> None:
            """Starts one contended application-frame write."""
            start.wait()
            state.send_frame(writer, frame)

        left = threading.Thread(target=send, args=(b'A' * 128 + b'\n',))
        right = threading.Thread(target=send, args=(b'B' * 128 + b'\n',))
        left.start()
        right.start()
        start.wait()
        left.join()
        right.join()
        self.assertIn(
            bytes(cast(_ContendedWriter, writer).data),
            (
                b'A' * 128 + b'\n' + b'B' * 128 + b'\n',
                b'B' * 128 + b'\n' + b'A' * 128 + b'\n',
            ),
        )

    def test_purge_fence_wins_after_voice_finalize_passes_initial_guard(self) -> None:
        """G25: a queued finalize cannot fallback after purge raises its fence."""
        operation_lock = threading.RLock()
        fence = _ObservedFence()
        voice = VoiceTransferManager(
            contacts=self.sender_contacts,
            messages=self.sender_messages,
            blobs=self.sender_blobs,
            state=StateTracker(),
            broadcast=lambda _event: None,
            config=self.sender_pm.config,
            transition_lock=operation_lock,
            purge_fence=cast(threading.Event, fence),
        )
        voice.begin(self.receiver_alias, Delivery.LIVE, 'purge-race', 'opus')
        voice.append('purge-race', 0, base64.b64encode(b'keep').decode('ascii'))
        fence.checked.clear()

        operation_lock.acquire()
        worker = threading.Thread(target=voice.finalize, args=('purge-race', 20))
        worker.start()
        self.assertTrue(fence.checked.wait(timeout=1.0))
        fence.set()
        operation_lock.release()
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertEqual(
            [row.msg_id for row in self.sender_messages.get_pending_live_outbox()],
            ['purge-race'],
        )
        self.assertEqual(self.sender_messages.get_pending_outbox(), [])

    def test_purge_stop_wins_after_outbox_ack_passes_initial_guard(self) -> None:
        """G25: queued DROP acknowledgement cannot commit beyond purge stop."""
        operation_lock = threading.RLock()
        stop_flag = _ObservedFence()
        message_manager = Mock()
        history_manager = Mock()
        broadcasts: list[IpcEvent] = []
        delivery = DropDelivery(
            mm=message_manager,
            hm=history_manager,
            state=StateTracker(),
            tunnels=Mock(),
            broadcast_callback=broadcasts.append,
            stop_flag=cast(threading.Event, stop_flag),
            config=self.sender_pm.config,
            operation_lock=operation_lock,
        )

        operation_lock.acquire()
        worker = threading.Thread(
            target=delivery._finalize_delivery,
            args=(1, self.receiver_onion, 'text', 'payload', 'purge-drop', '', 'drop'),
        )
        worker.start()
        self.assertTrue(stop_flag.checked.wait(timeout=1.0))
        stop_flag.set()
        operation_lock.release()
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        message_manager.update_message_status.assert_not_called()
        history_manager.log_event.assert_not_called()
        self.assertEqual(broadcasts, [])

    def test_slow_voice_peer_does_not_stall_another_peer(self) -> None:
        """G13: outbound network I/O is outside the global Voice state lock."""
        second_onion = 'c' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        second_alias = self.sender_contacts.ensure_alias_for_onion(second_onion)
        assert second_alias is not None
        state = StateTracker()
        voice = self._voice(sender=True, state=state)
        voice.begin(self.receiver_alias, Delivery.LIVE, 'slow-a', 'opus')
        voice.begin(second_alias, Delivery.LIVE, 'fast-b', 'opus')
        entered = threading.Event()
        release = threading.Event()
        slow = cast(socket.socket, _BlockingSocket(entered, release))
        fast_obj = _VoiceSocket()
        fast = cast(socket.socket, fast_obj)
        state.add_active_connection(self.receiver_onion, slow)
        state.add_active_connection(second_onion, fast)

        slow_worker = threading.Thread(
            target=voice.append,
            args=('slow-a', 0, base64.b64encode(b'a').decode('ascii')),
        )
        slow_worker.start()
        self.assertTrue(entered.wait(timeout=1.0))
        fast_worker = threading.Thread(
            target=voice.append,
            args=('fast-b', 0, base64.b64encode(b'b').decode('ascii')),
        )
        fast_worker.start()
        fast_worker.join(timeout=1.0)

        self.assertFalse(fast_worker.is_alive())
        self.assertTrue(
            any(frame.startswith(b'/voice_chunk ') for frame in fast_obj.sent)
        )
        release.set()
        slow_worker.join(timeout=1.0)

    def test_direction_collision_deletes_only_selected_receipt(self) -> None:
        """G28: destructive identity includes the local message direction."""
        for direction in (MessageDirection.IN, MessageDirection.OUT):
            self.sender_messages.queue_message(
                self.receiver_onion,
                direction,
                Delivery.DROP,
                ContentType.TEXT,
                direction.value,
                MessageStatus.READ
                if direction is MessageDirection.IN
                else MessageStatus.DELIVERED,
                msg_id='collision',
            )
        self.assertEqual(
            self.sender_messages.delete_drop_message(
                self.receiver_onion, 'collision', MessageDirection.IN
            ).value,
            'deleted',
        )
        remaining = self.sender_messages.get_chat_history(self.receiver_onion)
        self.assertEqual(
            [(row.direction, row.payload) for row in remaining], [('out', 'out')]
        )

    def test_mutation_fans_out_content_free_state_to_restricted_peer(self) -> None:
        """G22: client A's mutation safely invalidates client B's projection."""
        client_a = cast(socket.socket, object())
        client_b = cast(socket.socket, object())
        access = SessionAccessController(
            require_auth=False,
            send_callback=lambda _conn, _event: None,
            lockout_timeout_callback=lambda: 30.0,
            failure_limit_callback=lambda: 3,
            live_consumer_available_callback=lambda: None,
        )
        access.mark_authenticated(client_a)
        access.mark_authenticated(client_b)
        access.restrict(
            client_b,
            RestrictClientCommand(
                unlock_method=ClientUnlockMethod.PROFILE_PASSWORD,
                notification_privacy=NotificationPrivacy.ANONYMIZE,
            ),
        )
        delivered_a: list[IpcEvent] = []
        delivered_b: list[IpcEvent] = []

        def broadcast(event: IpcEvent) -> None:
            """Projects one canonical broadcast to both authenticated clients."""
            projected_a = access.filter_restricted_event(client_a, event)
            projected_b = access.filter_restricted_event(client_b, event)
            if projected_a is not None:
                delivered_a.append(projected_a)
            if projected_b is not None:
                delivered_b.append(projected_b)

        self.receiver_messages.queue_message(
            self.sender_onion,
            MessageDirection.IN,
            Delivery.DROP,
            ContentType.TEXT,
            'private text',
            MessageStatus.UNREAD,
            msg_id='fanout',
        )
        handler = DatabaseCommandHandler(
            self.receiver_pm,
            self.receiver_contacts,
            HistoryManager(self.receiver_pm),
            self.receiver_messages,
            get_active_onions=lambda: [],
            broadcast=broadcast,
        )
        with request_context('client-a-request'):
            handler.handle(MarkReadCommand(target=self.sender_onion))

        self.assertEqual(len(delivered_a), 1)
        self.assertEqual(len(delivered_b), 1)
        self.assertIsInstance(delivered_a[0], RuntimeStateChangedEvent)
        self.assertEqual(delivered_a[0].onion, self.sender_onion)
        self.assertIsNone(delivered_a[0].request_id)
        self.assertIsInstance(delivered_b[0], RuntimeStateChangedEvent)
        self.assertIsNone(delivered_b[0].onion)
        self.assertFalse(hasattr(delivered_b[0], 'content'))

    def test_normal_exit_preserves_pending_text_and_voice_locally(self) -> None:
        """G23: normal exit strengthens pending LIVE work without remote waits."""
        state = StateTracker()
        state.mark_scheduled_auto_reconnect(self.receiver_onion)
        router = MessageRouter(
            cm=self.sender_contacts,
            hm=HistoryManager(self.sender_pm),
            mm=self.sender_messages,
            state=state,
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: True,
            has_live_consumers_callback=lambda: True,
            notify_callback=lambda _payload: None,
            config=self.sender_pm.config,
            blob_store=self.sender_blobs,
        )
        router.send_message(self.receiver_alias, 'pending text', 'exit-text')
        router.begin_voice(self.receiver_alias, Delivery.LIVE, 'exit-voice', 'opus')
        router.append_voice(
            'exit-voice', 0, base64.b64encode(b'pending voice').decode('ascii')
        )
        router.finalize_voice('exit-voice', 80)
        self.assertCountEqual(
            [row.msg_id for row in self.sender_messages.get_pending_live_outbox()],
            ['exit-text', 'exit-voice'],
        )

        router.finalize_pending_live_messages()

        self.assertEqual(self.sender_messages.get_pending_live_outbox(), [])
        self.assertCountEqual(
            [row[4] for row in self.sender_messages.get_pending_outbox()],
            ['exit-text', 'exit-voice'],
        )
        voice_read = router.read_voice_chunk(
            self.receiver_onion,
            'exit-voice',
            MessageDirection.OUT,
            0,
            Constants.VOICE_CHUNK_MAX_BYTES,
        )
        self.assertIs(voice_read[1], Delivery.DROP)
        self.assertEqual(voice_read[2], b'pending voice')

    def test_profile_return_does_not_resurrect_live_reconnect_intent(self) -> None:
        """G24: reopening durable DROP work does not auto-reconnect or fallback."""
        self.sender_messages.queue_message(
            self.receiver_onion,
            MessageDirection.OUT,
            Delivery.DROP,
            ContentType.TEXT,
            'already preserved',
            MessageStatus.PENDING,
            msg_id='return-drop',
        )
        state = StateTracker()
        events: list[IpcEvent] = []

        MessageRouter(
            cm=self.sender_contacts,
            hm=HistoryManager(self.sender_pm),
            mm=self.sender_messages,
            state=state,
            broadcast_callback=events.append,
            has_clients_callback=lambda: True,
            has_live_consumers_callback=lambda: True,
            notify_callback=lambda _payload: None,
            config=self.sender_pm.config,
            blob_store=self.sender_blobs,
        )

        self.assertFalse(state.has_scheduled_auto_reconnect(self.receiver_onion))
        self.assertFalse(state.has_outbound_attempt(self.receiver_onion))
        self.assertEqual(self.sender_messages.get_pending_live_outbox(), [])
        self.assertEqual(
            [row[4] for row in self.sender_messages.get_pending_outbox()],
            ['return-drop'],
        )
        self.assertEqual(events, [])

    def test_drop_voice_draft_requires_commit_and_can_be_cancelled(self) -> None:
        """G04: finalized DROP media is not published before explicit commit."""
        voice = self._voice(sender=True)
        voice.begin(self.receiver_alias, Delivery.DROP, 'draft-commit', 'opus')
        voice.append('draft-commit', 0, base64.b64encode(b'publish me').decode('ascii'))
        voice.finalize('draft-commit', 90)
        self.assertEqual(self.sender_messages.get_pending_outbox(), [])
        self.assertEqual(self.sender_messages.get_chat_history(self.receiver_onion), [])

        self.assertTrue(voice.commit_draft(self.receiver_alias, 'draft-commit'))
        self.assertEqual(
            [row[4] for row in self.sender_messages.get_pending_outbox()],
            ['draft-commit'],
        )

        voice.begin(self.receiver_alias, Delivery.DROP, 'draft-cancel', 'opus')
        voice.append('draft-cancel', 0, base64.b64encode(b'discard me').decode('ascii'))
        voice.finalize('draft-cancel', 90)
        self.assertTrue(voice.cancel_draft(self.receiver_alias, 'draft-cancel'))
        self.assertIsNone(
            self.sender_messages.get_voice_payload(
                self.receiver_onion, 'draft-cancel', MessageDirection.OUT
            )
        )

    def test_generic_text_ack_cannot_complete_voice_identity(self) -> None:
        """G02: a stale generic ACK cannot release pending Voice payload."""
        state = StateTracker()
        state.mark_scheduled_auto_reconnect(self.receiver_onion)
        router = MessageRouter(
            cm=self.sender_contacts,
            hm=HistoryManager(self.sender_pm),
            mm=self.sender_messages,
            state=state,
            broadcast_callback=lambda _event: None,
            has_clients_callback=lambda: True,
            has_live_consumers_callback=lambda: True,
            notify_callback=lambda _payload: None,
            config=self.sender_pm.config,
            blob_store=self.sender_blobs,
        )
        router.begin_voice(self.receiver_alias, Delivery.LIVE, 'voice-only', 'opus')
        router.append_voice(
            'voice-only', 0, base64.b64encode(b'retained').decode('ascii')
        )

        router.process_incoming_ack(self.receiver_onion, 'voice-only')

        self.assertEqual(
            [row.msg_id for row in self.sender_messages.get_pending_live_outbox()],
            ['voice-only'],
        )
        read = router.read_voice_chunk(
            self.receiver_onion,
            'voice-only',
            MessageDirection.OUT,
            0,
            Constants.VOICE_CHUNK_MAX_BYTES,
        )
        self.assertEqual(read[2], b'retained')


if __name__ == '__main__':
    unittest.main()
