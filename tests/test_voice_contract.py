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
        self._alias = self._cm.ensure_alias_for_onion(self._onion)
        assert self._alias is not None
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

    def test_finalized_live_voice_falls_back_with_same_message_id(self) -> None:
        """Promotes one complete disconnected Voice turn without changing identity."""
        payload = b'voice payload'
        self._voice.begin(self._alias, Delivery.LIVE, 'voice-fallback', 'opus')
        self._voice.append(
            'voice-fallback', 0, base64.b64encode(payload).decode('ascii')
        )
        self._voice.finalize('voice-fallback', 500)

        self.assertEqual(self._mm.get_pending_live_outbox(self._onion), [])
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

        self.assertEqual(self._voice.outbound_target('voice-out'), self._onion)
        self.assertTrue(
            any(isinstance(event, MessageReceivedEvent) for event in self._events)
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
        begin = {'id': 'voice-consumed', 'codec': 'opus'}
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
