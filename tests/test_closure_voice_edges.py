"""Enclosing Voice quota and negative persistence schedules for closure."""

import base64
import json
import socket
import threading
import unittest
from unittest.mock import patch

import test_closure_integration as integration
from metor.core.api import (
    ContentType,
    Delivery,
    MarkReadCommand,
    UnreadMessagesEvent,
    VoiceChunkAcceptedEvent,
    VoiceFinalizedEvent,
    VoiceOperationRejectedEvent,
    VoiceResourceLimitEvent,
    VoiceResourcePressureEvent,
)
from metor.data import MessageDirection, MessageStatus, SettingKey
from metor.data.blob import BlobLifecycle


class ClosureVoiceEdgeTests(unittest.TestCase):
    """Uses actual SDK/daemon or actual SQL/blob boundaries, never fabricated success."""

    def setUp(self) -> None:
        self.h = integration.ClosureDaemonTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def test_public_exact_crossing_and_shared_limit_finalize_admitted_prefix(
        self,
    ) -> None:
        f = self.h.fixture
        daemon = self.h.daemon()
        events = []
        finished = threading.Event()
        client = self.h.client(daemon, events)
        original_broadcast = daemon._broadcast_ipc_event

        def observe(event: object) -> None:
            original_broadcast(event)
            if isinstance(event, VoiceFinalizedEvent):
                finished.set()

        # Use the real producer's callback, retaining its request correlation.
        voice = daemon._network._router._voice
        original_get = f.sender_pm.config.get_int
        local, peer = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(peer.close)
        daemon._transport_state.add_active_connection(f.receiver_onion, local)
        for scenario in ('exact', 'crossing', 'shared'):
            with self.subTest(scenario=scenario):
                finished.clear()
                events.clear()

                def get_int(key: SettingKey) -> int:
                    if (
                        key is SettingKey.MAX_PENDING_LIVE_BYTES
                        and scenario == 'shared'
                    ):
                        return 2
                    return original_get(key)

                with (
                    patch.object(
                        voice, '_limit', return_value=4 if scenario != 'shared' else 100
                    ),
                    patch.object(voice, '_used_bytes', return_value=0),
                    patch.object(f.sender_pm.config, 'get_int', side_effect=get_int),
                    patch.object(voice, '_broadcast', side_effect=observe),
                ):
                    delivery = Delivery.LIVE if scenario == 'shared' else Delivery.DROP
                    self.assertIsNotNone(
                        client.begin_voice(f.receiver_alias, delivery, scenario, 'opus')
                    )
                    if scenario == 'exact':
                        result = client.append_voice(
                            scenario, 0, base64.b64encode(b'abcd').decode()
                        )
                        self.assertIsInstance(result, VoiceChunkAcceptedEvent)
                        expected_size = 4
                    else:
                        result = client.append_voice(
                            scenario, 0, base64.b64encode(b'abcde').decode()
                        )
                        self.assertIsInstance(result, VoiceResourceLimitEvent)
                        expected_size = 0
                    self.assertTrue(finished.wait(2))
                    # Same IPC stream barrier completes the whole producer call.
                    self.assertIsNotNone(client.runtime_snapshot())
                record = f.sender_messages.get_voice_payload(
                    f.receiver_onion, scenario, MessageDirection.OUT
                )
                self.assertEqual(
                    json.loads(record.payload)['size_bytes'], expected_size
                )
                self.assertTrue(json.loads(record.payload)['finalized'])
                if delivery is Delivery.DROP:
                    self.assertFalse(
                        any(
                            row[4] == scenario
                            for row in f.sender_messages.get_pending_outbox()
                        )
                    )
                if scenario == 'exact':
                    # Delivery to the callback may lag the correlated result.
                    self.assertTrue(
                        any(isinstance(e, VoiceResourcePressureEvent) for e in events)
                    )

    def test_false_and_exception_metadata_never_report_terminal_success(self) -> None:
        f = self.h.fixture
        for failure in (False, OSError('injected precommit failure')):
            events = []
            voice = f._voice(sender=True, events=events)
            msg_id = 'failure-' + str(isinstance(failure, OSError))
            voice.begin(f.receiver_alias, Delivery.DROP, msg_id, 'opus')
            voice.append(msg_id, 0, base64.b64encode(b'kept').decode())
            turn = voice._outbound[msg_id]
            chunk = turn.chunk_ids[0]
            events.clear()
            with patch.object(
                f.sender_messages,
                'update_retained_bytes',
                return_value=False,
                side_effect=failure if isinstance(failure, OSError) else None,
            ):
                voice.finalize(msg_id, 10)
            self.assertFalse(turn.finalized)
            self.assertFalse(any(isinstance(e, VoiceFinalizedEvent) for e in events))
            self.assertTrue(
                any(isinstance(e, VoiceOperationRejectedEvent) for e in events)
            )
            self.assertEqual(
                f.sender_blobs.read(chunk, BlobLifecycle.TEMPORARY), b'kept'
            )
            voice.finalize(msg_id, 10)
            self.assertTrue(turn.finalized)

    def test_read_receipt_policy_controls_only_transient_peer_notification(
        self,
    ) -> None:
        """Document-1 H: local consume works with receipts OFF, queued wire only ON."""
        f = self.h.fixture
        daemon = self.h.daemon()
        client = self.h.client(daemon)
        local, peer = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(peer.close)
        peer.settimeout(2)
        daemon._transport_state.add_active_connection(f.receiver_onion, local)
        for enabled in (False, True):
            f.sender_pm.config.set(SettingKey.SEND_READ_RECEIPTS, enabled)
            msg_id = 'read-' + str(enabled)
            self.assertTrue(
                f.sender_messages.queue_message(
                    f.receiver_onion,
                    MessageDirection.IN,
                    Delivery.LIVE,
                    ContentType.TEXT,
                    'retained text',
                    MessageStatus.UNREAD,
                    msg_id=msg_id,
                )
            )
            result = client.request(
                MarkReadCommand(f.receiver_alias, Delivery.LIVE), UnreadMessagesEvent
            )
            self.assertEqual([entry.msg_id for entry in result.messages], [msg_id])
            daemon._transport_state.send_frame(local, b'barrier\n')
            data = bytearray()
            while not data.endswith(b'barrier\n'):
                data.extend(peer.recv(4096))
            self.assertEqual(
                bytes(data),
                (f'/read {msg_id}\n'.encode() if enabled else b'') + b'barrier\n',
            )


if __name__ == '__main__':
    unittest.main()
