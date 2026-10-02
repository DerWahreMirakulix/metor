"""Focused Voice content, retention, resume, fallback, and duplex contracts."""

# ruff: noqa: E402

import base64
import json
import socket
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import ContentType, Delivery, MessageReceivedEvent
from metor.core.daemon.managed.network.state import StateTracker
from metor.core.daemon.managed.network.voice import VoiceTransferManager
from metor.core.daemon.managed.network.voice.capture import VoiceCaptureMixin
from metor.core.daemon.managed.network.voice.inbound import VoiceInboundMixin
from metor.core.daemon.managed.network.voice.retained import VoiceRetainedMixin
from metor.data import ContactManager, MessageDirection, MessageManager, SettingKey
from metor.data.blob import BlobLifecycle, PlaintextBlobStore
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.utils import Constants


class _VoiceSocket:
    """Small socket-shaped writer used by protocol unit tests."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)


class VoiceContractTests(unittest.TestCase):
    """Covers logical Voice turns on the canonical message/blob foundation."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        self._data_patch = patch.object(Constants, 'DATA', root / Constants.DATA_DIR)
        self._data_patch.start()
        self.addCleanup(self._data_patch.stop)
        self._pm = ProfileManager('default')
        self._pm.initialize()
        self._cm = ContactManager(self._pm)
        self._mm = MessageManager(self._pm)
        self._blobs = PlaintextBlobStore(root / 'persistent', root / 'temporary')
        self.addCleanup(self._blobs.close)
        self.addCleanup(SqlManager.close_connection, self._pm.paths.get_db_file())
        self._onion = 'b' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        alias = self._cm.ensure_alias_for_onion(self._onion)
        assert alias is not None
        self._alias: str = alias
        self._events: list[object] = []
        self._state = StateTracker()
        self._voice = VoiceTransferManager(
            contacts=self._cm,
            messages=self._mm,
            blobs=self._blobs,
            state=self._state,
            broadcast=self._events.append,
            config=self._pm.config,
        )

    def test_inbound_frame_methods_have_one_dedicated_owner(self) -> None:
        """Receive admission is inherited unchanged from the inbound component."""
        self.assertIs(
            VoiceTransferManager.receive_begin, VoiceInboundMixin.receive_begin
        )
        self.assertIs(
            VoiceTransferManager.receive_chunk, VoiceInboundMixin.receive_chunk
        )
        self.assertIs(VoiceTransferManager.receive_end, VoiceInboundMixin.receive_end)

    def test_retained_metadata_methods_have_one_dedicated_owner(self) -> None:
        """Hydration and retained-content operations share one focused component."""
        self.assertIs(
            VoiceTransferManager.finalize_interrupted,
            VoiceRetainedMixin.finalize_interrupted,
        )
        self.assertIs(
            VoiceTransferManager.dismiss_inbound,
            VoiceRetainedMixin.dismiss_inbound,
        )

    def test_outbound_capture_methods_have_one_dedicated_owner(self) -> None:
        """Capture admission, append, and finalization share one focused owner."""
        self.assertIs(VoiceTransferManager.begin, VoiceCaptureMixin.begin)
        self.assertIs(VoiceTransferManager.append, VoiceCaptureMixin.append)
        self.assertIs(VoiceTransferManager.finalize, VoiceCaptureMixin.finalize)

    def test_live_draft_requires_explicit_drop_send_with_same_message_id(self) -> None:
        """Finalization remains local; explicit Drop Send preserves the recording identity."""
        payload = b'voice payload'
        self._voice.begin(self._alias, Delivery.LIVE, 'voice-fallback', 'opus')
        self._voice.append(
            'voice-fallback', 0, base64.b64encode(payload).decode('ascii')
        )
        self._voice.finalize('voice-fallback', 500)

        self.assertEqual(self._mm.get_pending_live_outbox(self._onion), [])
        self.assertEqual(self._mm.get_pending_outbox(), [])
        draft = self._mm.get_voice_payload(
            self._onion, 'voice-fallback', MessageDirection.OUT
        )
        self.assertEqual(draft.delivery, Delivery.LIVE.value)
        self.assertEqual(draft.status, 'draft')
        self.assertFalse(self._voice.commit_draft(self._alias, 'voice-fallback'))
        self.assertTrue(
            self._voice.commit_draft(self._alias, 'voice-fallback', Delivery.DROP)
        )
        self.assertTrue(
            self._voice.commit_draft(self._alias, 'voice-fallback', Delivery.DROP)
        )
        rows = self._mm.get_pending_outbox()
        self.assertEqual([row[4] for row in rows], ['voice-fallback'])
        self.assertEqual(rows[0][2], ContentType.VOICE.value)
        metadata = json.loads(rows[0][3])
        self.assertTrue(metadata['finalized'])
        self.assertEqual(metadata['size_bytes'], len(payload))
        self.assertEqual(
            b''.join(
                self._blobs.read(chunk_id, BlobLifecycle.PERSISTENT)
                for chunk_id in metadata['chunk_ids']
            ),
            payload,
        )

    def test_both_mode_drafts_emit_no_peer_bytes_until_explicit_send(self) -> None:
        """A connected peer sees no begin/chunk/end during capture and review."""
        writer = _VoiceSocket()
        conn = cast(socket.socket, writer)
        self._state.add_active_connection(self._onion, conn)
        for delivery in Delivery:
            with self.subTest(delivery=delivery):
                identity = 'staged-' + delivery.value
                self._voice.begin(self._alias, delivery, identity, 'opus')
                self._voice.append(
                    identity, 0, base64.b64encode(b'private recording').decode()
                )
                self._voice.replay(self._onion)
                self._voice.finalize(identity, 20)
                self._voice.replay(self._onion)
                self.assertEqual(writer.sent, [])
                draft = self._mm.get_voice_payload(
                    self._onion, identity, MessageDirection.OUT
                )
                self.assertEqual(draft.status, 'draft')
                self.assertEqual(self._mm.get_pending_live_outbox(), [])
                self.assertEqual(self._mm.get_pending_outbox(), [])
                content, mode, data, _, complete, reason = self._voice.read_chunk(
                    self._onion,
                    identity,
                    MessageDirection.OUT,
                    0,
                    Constants.VOICE_CHUNK_MAX_BYTES,
                )
                self.assertIsNone(reason)
                self.assertEqual(mode, delivery)
                self.assertEqual(data, b'private recording')
                self.assertTrue(complete)
                self.assertTrue(self._voice.cancel_draft(self._alias, identity))
        self._voice.begin(self._alias, Delivery.LIVE, 'explicit-live', 'opus')
        self._voice.append('explicit-live', 0, base64.b64encode(b'send me').decode())
        self._voice.finalize('explicit-live', 20)
        self.assertEqual(writer.sent, [])
        self.assertTrue(self._voice.commit_draft(self._alias, 'explicit-live'))
        self.assertEqual(len(writer.sent), 1)
        self.assertTrue(writer.sent[0].startswith(b'/voice_begin '))

    def test_live_draft_cannot_publish_into_a_later_chat_generation(self) -> None:
        """An ended chat never implicitly commits or retargets its review draft."""
        first = cast(socket.socket, _VoiceSocket())
        self._state.add_active_connection(self._onion, first)
        self._voice.begin(self._alias, Delivery.LIVE, 'old-context', 'opus')
        self._voice.append('old-context', 0, base64.b64encode(b'old draft').decode())
        self._voice.finalize('old-context', 20)
        self._state.pop_any_connection(self._onion)
        replacement = _VoiceSocket()
        self._state.add_active_connection(self._onion, cast(socket.socket, replacement))
        self.assertFalse(self._voice.commit_draft(self._alias, 'old-context'))
        self.assertEqual(replacement.sent, [])
        self.assertTrue(
            self._voice.commit_draft(self._alias, 'old-context', Delivery.DROP)
        )
        self.assertEqual(replacement.sent, [])

    def test_live_voice_allows_simultaneous_inbound_and_outbound_turns(self) -> None:
        """Does not impose a half-duplex lock on authenticated LIVE Voice state."""
        conn = cast(socket.socket, _VoiceSocket())
        self._state.add_active_connection(self._onion, conn)
        self._voice.begin(self._alias, Delivery.LIVE, 'voice-out', 'opus')
        self.assertFalse(
            self._voice.receive_begin(
                conn,
                self._onion,
                {
                    'id': 'voice-in',
                    'codec': 'opus',
                    'timestamp': '2026-09-11T10:00:00+00:00',
                },
            )
        )
        inbound = b'inbound'
        self.assertFalse(
            self._voice.receive_chunk(
                conn,
                self._onion,
                {
                    'id': 'voice-in',
                    'offset': 0,
                    'data': base64.b64encode(inbound).decode('ascii'),
                },
            )
        )
        self._voice.append(
            'voice-out', 0, base64.b64encode(b'outbound').decode('ascii')
        )
        self.assertFalse(
            self._voice.receive_end(
                conn,
                self._onion,
                {'id': 'voice-in', 'size': len(inbound)},
            )
        )

        retained = self._mm.get_voice_payload(
            self._onion, 'voice-out', MessageDirection.OUT
        )
        self.assertIsNotNone(retained)
        self.assertEqual(retained.peer_onion, self._onion)
        self.assertTrue(
            any(isinstance(event, MessageReceivedEvent) for event in self._events)
        )

    def test_delayed_duplicate_chunks_after_finalization_preserve_live_tunnel(
        self,
    ) -> None:
        """Byte-identical replay after END is accepted; changed or extending data is rejected."""
        from metor.core.daemon.managed.network.router.admission import FrameAdmission

        conn = cast(socket.socket, _VoiceSocket())
        identity = 'voice-late-ack'
        payload = b'\x00\x01' * 320
        chunk: dict[str, object] = {
            'id': identity,
            'offset': 0,
            'data': base64.b64encode(payload).decode('ascii'),
        }
        self.assertIs(
            self._voice.receive_begin(
                conn,
                self._onion,
                {
                    'id': identity,
                    'codec': 'pcm_s16le_16000_mono',
                },
            ),
            FrameAdmission.ACCEPTED,
        )
        self.assertIs(
            self._voice.receive_chunk(conn, self._onion, chunk), FrameAdmission.ACCEPTED
        )
        self.assertIs(
            self._voice.receive_end(
                conn,
                self._onion,
                {
                    'id': identity,
                    'size': len(payload),
                    'duration_ms': 20,
                },
            ),
            FrameAdmission.ACCEPTED,
        )
        events = len(self._events)
        self.assertIs(
            self._voice.receive_chunk(conn, self._onion, chunk), FrameAdmission.ACCEPTED
        )
        self.assertEqual(len(self._events), events)
        changed = dict(chunk, data=base64.b64encode(b'\x02\x03' * 320).decode('ascii'))
        self.assertIs(
            self._voice.receive_chunk(conn, self._onion, changed),
            FrameAdmission.MALFORMED,
        )
        self.assertIs(
            self._voice.receive_chunk(
                conn, self._onion, dict(chunk, offset=len(payload))
            ),
            FrameAdmission.MALFORMED,
        )

    def test_inbound_drop_voice_keeps_drop_receipt_and_persistent_blob(self) -> None:
        """Commits DROP Voice metadata and object under the same delivery semantics."""
        conn = cast(socket.socket, _VoiceSocket())
        payload = b'durable inbound voice'

        self.assertFalse(
            self._voice.receive_begin(
                conn,
                self._onion,
                {
                    'id': 'voice-drop-in',
                    'codec': 'opus',
                    'timestamp': '2026-09-11T10:00:00+00:00',
                },
                Delivery.DROP,
            )
        )
        self.assertFalse(
            self._voice.receive_chunk(
                conn,
                self._onion,
                {
                    'id': 'voice-drop-in',
                    'offset': 0,
                    'data': base64.b64encode(payload).decode('ascii'),
                },
            )
        )
        self.assertEqual(self._mm.get_chat_history(self._onion), [])
        self.assertFalse(
            self._voice.receive_end(
                conn,
                self._onion,
                {'id': 'voice-drop-in', 'size': len(payload)},
            )
        )

        record = self._mm.get_voice_payload(
            self._onion, 'voice-drop-in', MessageDirection.IN
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.delivery, Delivery.DROP.value)
        metadata = json.loads(record.payload)
        self.assertEqual(
            b''.join(
                self._blobs.read(chunk_id, BlobLifecycle.PERSISTENT)
                for chunk_id in metadata['chunk_ids']
            ),
            payload,
        )

    def test_inbound_voice_obeys_headless_unseen_count_policy(self) -> None:
        """Refuses a new Voice item when zero backlog has no LIVE consumer."""
        original_get_int = self._pm.config.get_int

        def get_int(key: SettingKey) -> int:
            if key is SettingKey.MAX_UNSEEN_LIVE_MSGS:
                return 0
            return original_get_int(key)

        conn = cast(socket.socket, _VoiceSocket())
        with patch.object(self._pm.config, 'get_int', side_effect=get_int):
            voice = VoiceTransferManager(
                contacts=self._cm,
                messages=self._mm,
                blobs=self._blobs,
                state=self._state,
                broadcast=self._events.append,
                config=self._pm.config,
                has_clients_callback=lambda: False,
                has_live_consumers_callback=lambda: False,
            )
            should_disconnect = voice.receive_begin(
                conn,
                self._onion,
                {'id': 'headless-voice', 'codec': 'opus'},
            )

        self.assertTrue(should_disconnect)
        self.assertIsNone(self._mm.get_inbound_voice(self._onion, 'headless-voice'))

    def test_consumed_live_voice_duplicate_is_terminally_acknowledged(self) -> None:
        """Uses retained dedupe metadata without recreating a shredded Voice spool."""
        conn = cast(socket.socket, _VoiceSocket())
        payload = b'consume once'
        begin: dict[str, object] = {'id': 'voice-consumed', 'codec': 'opus'}
        self.assertFalse(self._voice.receive_begin(conn, self._onion, begin))
        self.assertFalse(
            self._voice.receive_chunk(
                conn,
                self._onion,
                {
                    'id': 'voice-consumed',
                    'offset': 0,
                    'data': base64.b64encode(payload).decode('ascii'),
                },
            )
        )
        self.assertFalse(
            self._voice.receive_end(
                conn,
                self._onion,
                {'id': 'voice-consumed', 'size': len(payload)},
            )
        )
        self.assertTrue(self._voice.release_inbound(self._onion, 'voice-consumed'))

        duplicate_socket = _VoiceSocket()
        duplicate_conn = cast(socket.socket, duplicate_socket)
        self.assertFalse(self._voice.receive_begin(duplicate_conn, self._onion, begin))

        self.assertEqual(duplicate_socket.sent, [b'/voice_commit_ack voice-consumed\n'])
        self.assertIsNone(self._mm.get_inbound_voice(self._onion, 'voice-consumed'))


if __name__ == '__main__':
    unittest.main()
