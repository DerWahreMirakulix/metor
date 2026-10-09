"""Exact ended-LIVE Voice cancellation across SQL, blobs and the real socket writer."""

import base64
import json
import socket
import threading
import unittest

import test_acceptance_repair_contract as support
from metor.core.api import Delivery, VoiceOperationRejectedEvent
from metor.core.daemon.managed.network import StateTracker, TcpStreamReader
from metor.data import MessageDirection, MessageStatus
from metor.data.blob import BlobLifecycle


class LiveVoiceCancellationTests(unittest.TestCase):
    """Uses committed SQL selections and real encrypted object ownership."""

    def setUp(self) -> None:
        """Builds isolated encrypted Voice stores and an actual blocked peer writer."""
        self.fixture = support.AcceptanceRepairContractTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.state = StateTracker()
        self.events: list[object] = []
        self.voice = self.fixture._voice(
            sender=True, state=self.state, events=self.events
        )
        self.local, self.peer = socket.socketpair()
        self.addCleanup(self.peer.close)
        self.addCleanup(self.state.retire_connection, self.local)
        self.peer.settimeout(1.0)
        self.state.add_active_connection(self.fixture.receiver_onion, self.local)
        self.entered, self.release = threading.Event(), threading.Event()
        self.addCleanup(self.release.set)

        def hold_writer() -> bool:
            """Holds the real emission owner before following Voice frame claims."""
            self.entered.set()
            return self.release.wait(2.0)

        self.state.send_frame(self.local, b'writer-barrier\n', hold_writer)
        self.assertTrue(self.entered.wait(1.0))

    def _stage(
        self, msg_id: str, delivery: Delivery, *, publish: bool
    ) -> tuple[str, ...]:
        """Stages actual Voice bytes and optionally commits their selected delivery."""
        f = self.fixture
        self.voice.begin(f.receiver_alias, delivery, msg_id, 'opus')
        self.voice.append(
            msg_id, 0, base64.b64encode(b'protected voice').decode('ascii')
        )
        self.voice.finalize(msg_id, 250)
        if publish:
            self.assertTrue(self.voice.commit_draft(f.receiver_alias, msg_id))
        record = f.sender_messages.get_voice_payload(
            f.receiver_onion, msg_id, MessageDirection.OUT
        )
        self.assertIsNotNone(record)
        assert record is not None
        metadata = json.loads(record.payload)
        return (metadata['blob_id'], *metadata['chunk_ids'])

    def test_cancelled_live_releases_payload_and_queued_frames_preserving_draft_and_drop(
        self,
    ) -> None:
        """Only the selected published LIVE turn loses emission and object ownership."""
        f = self.fixture
        cancelled = self._stage('cancel-live-voice', Delivery.LIVE, publish=True)
        draft = self._stage('unsent-live-voice', Delivery.LIVE, publish=False)
        drop = self._stage('kept-drop-voice', Delivery.DROP, publish=True)
        with self.voice._lock:
            records = f.sender_messages.discard_pending_live(
                f.receiver_onion, ['cancel-live-voice']
            )
            self.assertIsNotNone(records)
            assert records is not None
            self.state.invalidate_live_generations(
                f.receiver_onion, ['cancel-live-voice']
            )
            self.state.remove_unacked_message(f.receiver_onion, 'cancel-live-voice')
            self.voice.cancel_pending_live(f.receiver_onion, records)
        self.assertNotIn('cancel-live-voice', self.voice._outbound)
        self.assertIn('unsent-live-voice', self.voice._outbound)
        self.assertTrue(
            all(
                not f.sender_blobs.exists(blob_id, BlobLifecycle.TEMPORARY)
                for blob_id in cancelled
            )
        )
        self.assertTrue(
            all(
                f.sender_blobs.exists(blob_id, BlobLifecycle.TEMPORARY)
                for blob_id in draft
            )
        )
        self.assertTrue(
            all(
                f.sender_blobs.exists(blob_id, BlobLifecycle.PERSISTENT)
                for blob_id in drop
            )
        )
        self.voice.acknowledge(f.receiver_onion, 'cancel-live-voice', 15)
        self.voice.acknowledge_complete(f.receiver_onion, 'cancel-live-voice')
        self.assertEqual(
            f.sender_messages.message_state(
                f.receiver_onion, 'cancel-live-voice', MessageDirection.OUT
            ),
            (Delivery.LIVE, MessageStatus.PENDING, False),
        )
        self.assertEqual(f.sender_messages.get_pending_live_outbox(), [])
        self.assertEqual(
            [row[4] for row in f.sender_messages.get_pending_outbox()],
            ['kept-drop-voice'],
        )
        self.assertFalse(
            any(isinstance(event, VoiceOperationRejectedEvent) for event in self.events)
        )
        self.assertEqual(self.voice.replay(f.receiver_onion), [])
        self.release.set()
        self.assertTrue(self.state._socket_writers[self.local].flush(1.0))
        self.assertEqual(TcpStreamReader(self.peer).read_line(), 'writer-barrier')
        self.peer.settimeout(0.1)
        with self.assertRaises(socket.timeout):
            self.peer.recv(1)

    def test_cold_turn_cleanup_uses_sql_metadata_and_rejects_stale_drop_selection(
        self,
    ) -> None:
        """Missing runtime restoration still cleans cancelled bytes without touching fallback."""
        f = self.fixture
        cancelled = self._stage('cold-live-voice', Delivery.LIVE, publish=True)
        with self.voice._lock:
            records = f.sender_messages.discard_pending_live(
                f.receiver_onion, ['cold-live-voice']
            )
            self.assertIsNotNone(records)
            assert records is not None
            self.state.invalidate_live_generations(
                f.receiver_onion, ['cold-live-voice']
            )
            self.state.remove_unacked_message(f.receiver_onion, 'cold-live-voice')
            self.voice._outbound.pop('cold-live-voice')
            self.voice.cancel_pending_live(f.receiver_onion, records)
        self.assertTrue(
            all(
                not f.sender_blobs.exists(blob_id, BlobLifecycle.TEMPORARY)
                for blob_id in cancelled
            )
        )
        fallback = self._stage('fallback-live-voice', Delivery.LIVE, publish=True)
        stale = f.sender_messages.get_pending_live_outbox(f.receiver_onion)
        converted = f.sender_messages.promote_pending_live_to_drop(
            f.receiver_onion, ['fallback-live-voice']
        )
        self.assertIsNotNone(converted)
        self.state.invalidate_live_generations(
            f.receiver_onion, ['fallback-live-voice']
        )
        self.voice.promote_fallback(['fallback-live-voice'], f.receiver_onion)
        self.voice.cancel_pending_live(f.receiver_onion, stale)
        self.assertTrue(
            all(
                f.sender_blobs.exists(blob_id, BlobLifecycle.PERSISTENT)
                for blob_id in fallback
            )
        )
        self.assertEqual(
            [row[4] for row in f.sender_messages.get_pending_outbox()],
            ['fallback-live-voice'],
        )


if __name__ == '__main__':
    unittest.main()
