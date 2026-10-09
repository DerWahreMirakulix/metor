"""Voice Drop reuse through actual Live receivers and encrypted retained payloads."""

import base64
import json
import socket
import threading
import unittest
from unittest.mock import Mock, patch

import test_acceptance_repair_contract as support
from metor.core.api import AckEvent, ContentType, Delivery, DropFailedEvent
from metor.core.daemon.managed.network import StateTracker
from metor.core.daemon.managed.network.receiver import StreamReceiver
from metor.core.daemon.managed.network.router import MessageRouter
from metor.core.daemon.managed.outbox.delivery import DropDelivery, OutboxRow
from metor.data import (
    HistoryEvent,
    HistoryManager,
    MessageDirection,
    MessageStatus,
    SettingKey,
)
from metor.utils import Constants


class DropSessionVoiceTests(unittest.TestCase):
    """Exercises transfer failure and replacement without a second socket reader."""

    def setUp(self) -> None:
        """Builds two real stores and production routing/receiver paths."""
        self.fixture = support.AcceptanceRepairContractTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.sender_state = StateTracker()
        self.receiver_state = StateTracker()
        self.events: list[object] = []
        self.connections: list[socket.socket] = []
        self.threads: list[threading.Thread] = []
        self.stop_flag = threading.Event()
        self.addCleanup(self._stop_transports)
        f = self.fixture
        f.sender_pm.config.set(SettingKey.STREAM_IDLE_TIMEOUT, 1.0)
        f.receiver_pm.config.set(SettingKey.STREAM_IDLE_TIMEOUT, 1.0)
        self.sender_history = HistoryManager(f.sender_pm)
        self.receiver_history = HistoryManager(f.receiver_pm)
        self.sender_router = self._router(True)
        self.receiver_router = self._router(False)
        self.sender_receiver = self._receiver(True)
        self.receiver_receiver = self._receiver(False)
        self.tunnels = Mock()
        self.tunnels.acquire.return_value = None
        self.delivery = DropDelivery(
            mm=f.sender_messages,
            hm=self.sender_history,
            state=self.sender_state,
            tunnels=self.tunnels,
            broadcast_callback=self.events.append,
            stop_flag=self.stop_flag,
            config=f.sender_pm.config,
            blob_store=f.sender_blobs,
        )

    def _router(self, sender: bool) -> MessageRouter:
        """Creates the full text/Voice router over the selected profile."""
        f = self.fixture
        return MessageRouter(
            cm=f.sender_contacts if sender else f.receiver_contacts,
            hm=self.sender_history if sender else self.receiver_history,
            mm=f.sender_messages if sender else f.receiver_messages,
            state=self.sender_state if sender else self.receiver_state,
            broadcast_callback=self.events.append,
            has_clients_callback=lambda: True,
            has_live_consumers_callback=lambda: True,
            notify_callback=lambda _notification: None,
            config=f.sender_pm.config if sender else f.receiver_pm.config,
            blob_store=f.sender_blobs if sender else f.receiver_blobs,
        )

    def _receiver(self, sender: bool) -> StreamReceiver:
        """Creates a production receiver with exact-socket teardown callbacks."""
        f = self.fixture
        state = self.sender_state if sender else self.receiver_state

        def disconnect(
            onion: str,
            _initiated: bool,
            _fallback: bool,
            conn: socket.socket | None,
            _retunnel: bool,
            _origin: object,
            _reason: object,
        ) -> None:
            """Removes only the socket whose read loop ended."""
            if conn is not None:
                state.pop_any_connection(onion, conn)

        def reject(
            onion: str,
            _initiated: bool,
            conn: socket.socket | None,
            _origin: object,
            _intent: object,
        ) -> None:
            """Shares exact-socket removal for remote rejection."""
            if conn is not None:
                state.pop_any_connection(onion, conn)

        return StreamReceiver(
            cm=f.sender_contacts if sender else f.receiver_contacts,
            hm=self.sender_history if sender else self.receiver_history,
            state=state,
            router=self.sender_router if sender else self.receiver_router,
            broadcast_callback=self.events.append,
            disconnect_cb=disconnect,
            reject_cb=reject,
            config=f.sender_pm.config if sender else f.receiver_pm.config,
        )

    def _connect(self) -> tuple[socket.socket, socket.socket]:
        """Starts the sole receiver on both ends of a real replacement socket pair."""
        f = self.fixture
        sender, receiver = socket.socketpair()
        self.connections.extend((sender, receiver))
        self.sender_state.add_active_connection(f.receiver_onion, sender)
        self.receiver_state.add_active_connection(f.sender_onion, receiver)
        for reader, onion, conn in (
            (self.sender_receiver, f.receiver_onion, sender),
            (self.receiver_receiver, f.sender_onion, receiver),
        ):
            thread = threading.Thread(
                target=reader._receiver_target, args=(onion, conn)
            )
            self.threads.append(thread)
            thread.start()
        return sender, receiver

    def _stop_transports(self) -> None:
        """Releases and joins every actual receiver before closing its stores."""
        self.stop_flag.set()
        for conn in self.connections:
            self.sender_state.retire_connection(conn)
            self.receiver_state.retire_connection(conn)
        for thread in self.threads:
            thread.join(2.0)
            self.assertFalse(thread.is_alive())

    def _draft(self, msg_id: str, chunks: tuple[bytes, ...]) -> OutboxRow:
        """Publishes actual capture chunks as one durable Voice Drop."""
        f = self.fixture
        voice = self.sender_router._voice
        assert voice is not None
        voice.begin(f.receiver_alias, Delivery.DROP, msg_id, 'opus')
        offset = 0
        for chunk in chunks:
            voice.append(msg_id, offset, base64.b64encode(chunk).decode('ascii'))
            offset += len(chunk)
        voice.finalize(msg_id, 250)
        self.assertTrue(voice.commit_draft(f.receiver_alias, msg_id))
        return next(
            row for row in f.sender_messages.get_pending_outbox() if row[4] == msg_id
        )

    def _assert_received(self, msg_id: str, payload: bytes) -> None:
        """Checks committed receiver metadata and actual retained byte readback."""
        f = self.fixture
        voice = self.receiver_router._voice
        assert voice is not None
        record = f.receiver_messages.get_voice_payload(
            f.sender_onion, msg_id, MessageDirection.IN
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertTrue(json.loads(record.payload)['finalized'])
        _, delivery, data, next_offset, complete, reason = voice.read_chunk(
            f.sender_onion,
            msg_id,
            MessageDirection.IN,
            0,
            Constants.VOICE_CHUNK_MAX_BYTES,
        )
        self.assertEqual(
            (delivery, data, next_offset, complete, reason),
            (Delivery.DROP, payload, len(payload), True, None),
        )

    def test_mixed_drops_reuse_live_without_dialing_and_keep_live_ack_dispatch(
        self,
    ) -> None:
        """Text and multi-chunk Voice share one Live session and preserve Live ACKs."""
        f = self.fixture
        sender, receiver = self._connect()
        voice_row = self._draft('voice-mixed', (b'first ', b'second'))
        self.assertTrue(
            f.sender_messages.queue_message(
                f.receiver_onion,
                MessageDirection.OUT,
                Delivery.DROP,
                ContentType.TEXT,
                'text Drop',
                MessageStatus.PENDING,
                msg_id='text-mixed',
            )
        )
        self.sender_router.send_message(f.receiver_alias, 'live text', 'live-mixed')
        rows = f.sender_messages.get_pending_outbox()
        self.delivery.process_batch(
            f.receiver_onion,
            [row for row in rows if row[2] == ContentType.TEXT.value] + [voice_row],
        )
        self.assertEqual(f.sender_messages.get_pending_outbox(), [])
        self._assert_received('voice-mixed', b'first second')
        self.assertTrue(
            any(
                isinstance(event, AckEvent) and event.msg_id == voice_row[4]
                for event in self.events
            )
        )
        self.assertEqual(f.sender_messages.get_pending_live_outbox(), [])
        self.assertIs(self.sender_state.get_connection(f.receiver_onion), sender)
        self.assertIs(self.receiver_state.get_connection(f.sender_onion), receiver)
        self.tunnels.acquire.assert_not_called()
        self.tunnels.establish.assert_not_called()
        self.assertEqual(self.sender_state._drop_transfers, {})

    def test_text_ack_cannot_complete_voice_before_its_durable_terminal_ack(
        self,
    ) -> None:
        """Production dispatch ignores a text DROP ACK naming a queued Voice identity."""
        f = self.fixture
        _, receiver = self._connect()
        row = self._draft('voice-text-ack', (b'complete voice',))
        observed = threading.Event()
        original_ack = self.sender_router.process_incoming_drop_ack

        def observe_ack(onion: str, msg_id: str) -> None:
            """Signals after the real text ACK route checks the real Voice receipt."""
            original_ack(onion, msg_id)
            observed.set()

        with patch.object(
            self.sender_router, 'process_incoming_drop_ack', side_effect=observe_ack
        ):
            self.receiver_state.send_frame(receiver, b'/drop_ack voice-text-ack\n')
            self.assertTrue(observed.wait(2.0))
        self.assertEqual(
            [item[4] for item in f.sender_messages.get_pending_outbox()], [row[4]]
        )
        self.assertFalse(
            any(
                isinstance(event, AckEvent) and event.msg_id == row[4]
                for event in self.events
            )
        )
        self.delivery.process_batch(f.receiver_onion, [row])
        self.assertEqual(f.sender_messages.get_pending_outbox(), [])
        self._assert_received(row[4], b'complete voice')

    def test_replacement_during_chunk_ack_preserves_row_and_resumes_exact_prefix(
        self,
    ) -> None:
        """A replaced socket cancels its waiter; a new session resumes retained bytes."""
        f = self.fixture
        old, _ = self._connect()
        row = self._draft('voice-resume', (b'one', b'two'))
        entered, release = threading.Event(), threading.Event()
        original_send = self.receiver_state.send_frame

        def hold_ack(conn: socket.socket, frame: bytes, claim: object = None) -> None:
            """Holds the real ACK only after the real first chunk is durably stored."""
            if frame == b'/voice_ack voice-resume 3\n':
                entered.set()
                self.assertTrue(release.wait(2.0))
            original_send(conn, frame)

        worker = threading.Thread(
            target=self.delivery.process_batch, args=(f.receiver_onion, [row])
        )
        self.threads.append(worker)
        with patch.object(self.receiver_state, 'send_frame', side_effect=hold_ack):
            worker.start()
            self.assertTrue(entered.wait(2.0))
            new, _ = self._connect()
            worker.join(2.0)
            self.assertFalse(worker.is_alive())
            self.assertNotIn(old, self.sender_state._drop_transfers)
            self.assertEqual(
                [item[4] for item in f.sender_messages.get_pending_outbox()], [row[4]]
            )
            release.set()
        self.delivery.process_batch(f.receiver_onion, [row])
        self.assertEqual(f.sender_messages.get_pending_outbox(), [])
        self.assertIs(self.sender_state.get_connection(f.receiver_onion), new)
        self._assert_received(row[4], b'onetwo')

    def test_receiver_commit_failure_keeps_pending_and_retry_commits_once(self) -> None:
        """A failed real final metadata write produces no false delivery success."""
        f = self.fixture
        self._connect()
        row = self._draft('voice-commit-failure', (b'kept',))
        original_update = f.receiver_messages.update_inbound_voice_metadata

        def reject_final(onion: str, msg_id: str, size: int, payload: str) -> bool:
            """Injects only the final persistence failure, retaining actual prefix state."""
            if json.loads(payload).get('finalized') is True:
                return False
            return original_update(onion, msg_id, size, payload)

        with patch.object(
            f.receiver_messages,
            'update_inbound_voice_metadata',
            side_effect=reject_final,
        ):
            self.delivery.process_batch(f.receiver_onion, [row])
        self.assertEqual(
            [item[4] for item in f.sender_messages.get_pending_outbox()], [row[4]]
        )
        self.assertFalse(
            any(
                isinstance(event, AckEvent) and event.msg_id == row[4]
                for event in self.events
            )
        )
        self.assertEqual(self.sender_state._drop_transfers, {})
        self._connect()
        self.delivery.process_batch(f.receiver_onion, [row])
        self.assertEqual(f.sender_messages.get_pending_outbox(), [])
        self._assert_received(row[4], b'kept')

    def test_drop_denial_and_late_denial_leave_live_connected(self) -> None:
        """DROP-policy rejection cancels Voice and cannot end an established Live chat."""
        f = self.fixture
        sender, receiver = self._connect()
        f.receiver_pm.config.set(SettingKey.ALLOW_DROPS, False)
        f.receiver_pm.config.set(SettingKey.EXPOSE_DROP_REJECTION, True)
        row = self._draft('voice-denied', (b'unsent',))
        self.delivery.process_batch(f.receiver_onion, [row])
        self.assertEqual(
            [item[4] for item in f.sender_messages.get_pending_outbox()], [row[4]]
        )
        self.assertTrue(
            any(
                isinstance(event, DropFailedEvent) and event.msg_id == row[4]
                for event in self.events
            )
        )
        self.receiver_state.send_frame(receiver, b'/reject drops_disabled\n')
        finished = threading.Event()
        original_ack = self.sender_router.process_incoming_ack

        def observe_ack(onion: str, msg_id: str) -> None:
            """Uses actual successful Live ACK as the late-rejection stream barrier."""
            original_ack(onion, msg_id)
            if msg_id == 'after-denial':
                finished.set()

        with patch.object(
            self.sender_router, 'process_incoming_ack', side_effect=observe_ack
        ):
            self.sender_router.send_message(
                f.receiver_alias, 'barrier live', 'after-denial'
            )
            self.assertTrue(finished.wait(2.0))
        self.assertIs(self.sender_state.get_connection(f.receiver_onion), sender)
        self.assertIs(self.receiver_state.get_connection(f.sender_onion), receiver)

    def test_reuse_setting_disabled_keeps_voice_on_drop_transport(self) -> None:
        """The documented opt-out applies equally to Voice and text."""
        f = self.fixture
        self._connect()
        row = self._draft('voice-route-setting', (b'pending',))
        f.sender_pm.config.set(SettingKey.REUSE_LIVE_FOR_DROPS, False)
        self.delivery.process_batch(f.receiver_onion, [row])
        self.tunnels.acquire.assert_called_once_with(f.receiver_onion)
        self.assertEqual(
            [item[4] for item in f.sender_messages.get_pending_outbox()], [row[4]]
        )
        self.assertEqual(self.sender_state._drop_transfers, {})

    def test_cancelled_dial_outcome_does_not_report_a_tunnel_failure(self) -> None:
        """Cancellation while establishment is underway suppresses stale failure feedback."""
        f = self.fixture
        for direct in (False, True):
            with self.subTest(direct=direct):
                row = self._draft('voice-cancel-dial-' + str(direct), (b'pending',))

                def cancel_dial(_onion: str) -> None:
                    """Commits real cancellation before the controlled dial returns failure."""
                    with self.delivery._operation_lock:
                        f.sender_messages.delete_drop_message(
                            f.receiver_onion,
                            row[4],
                            MessageDirection.OUT,
                            cancel_pending=True,
                        )

                if direct:
                    self.tunnels.establish.side_effect = cancel_dial
                    self.delivery.send_single_drop(f.receiver_onion, row)
                else:
                    self.tunnels.acquire.side_effect = cancel_dial
                    self.delivery.process_batch(f.receiver_onion, [row])
                self.assertEqual(f.sender_messages.get_pending_outbox(), [])
                self.assertFalse(
                    any(
                        entry.event_code
                        in {HistoryEvent.TUNNEL_FAILED, HistoryEvent.FAILED}
                        for entry in self.sender_history.get_raw_history(
                            f.receiver_onion
                        )
                    )
                )

    def test_cancel_during_first_chunk_ack_stops_remaining_frames_and_keeps_live(
        self,
    ) -> None:
        """Deleting queued Voice revokes its wait and every later frame claim."""
        f = self.fixture
        sender, receiver = self._connect()
        row = self._draft('voice-cancel', (b'one', b'two'))
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original_send = self.receiver_state.send_frame

        def hold_ack(conn: socket.socket, frame: bytes, claim: object = None) -> None:
            """Holds the first actual ACK after its prefix is already admitted."""
            if frame == b'/voice_ack voice-cancel 3\n':
                entered.set()
                self.assertTrue(release.wait(2.0))
            original_send(conn, frame)

        worker = threading.Thread(
            target=self.delivery.process_batch, args=(f.receiver_onion, [row])
        )
        self.threads.append(worker)
        with patch.object(self.receiver_state, 'send_frame', side_effect=hold_ack):
            worker.start()
            self.assertTrue(entered.wait(2.0))
            with self.delivery._operation_lock:
                f.sender_messages.delete_drop_message(
                    f.receiver_onion, row[4], MessageDirection.OUT, cancel_pending=True
                )
            worker.join(2.0)
            self.assertFalse(worker.is_alive())
            release.set()
        self.assertEqual(f.sender_messages.get_pending_outbox(), [])
        self.assertEqual(self.sender_state._drop_transfers, {})
        self.assertFalse(
            any(
                isinstance(event, AckEvent) and event.msg_id == row[4]
                for event in self.events
            )
        )
        record = f.receiver_messages.get_voice_payload(
            f.sender_onion, row[4], MessageDirection.IN
        )
        self.assertIsNotNone(record)
        assert record is not None
        metadata = json.loads(record.payload)
        self.assertEqual(metadata['size_bytes'], 3)
        self.assertFalse(metadata['finalized'])
        self.assertFalse(
            any(
                entry.event_code is HistoryEvent.FAILED
                for entry in self.sender_history.get_raw_history(f.receiver_onion)
            )
        )
        self.assertIs(self.sender_state.get_connection(f.receiver_onion), sender)
        self.assertIs(self.receiver_state.get_connection(f.sender_onion), receiver)

    def test_cancel_before_writer_claim_suppresses_queued_text_and_voice(self) -> None:
        """A real blocked writer drops cached rows after the atomic cancel barrier."""
        f = self.fixture
        sender, _ = self._connect()
        voice_row = self._draft('voice-before-claim', (b'unsent',))
        self.assertTrue(
            f.sender_messages.queue_message(
                f.receiver_onion,
                MessageDirection.OUT,
                Delivery.DROP,
                ContentType.TEXT,
                'unsent text',
                MessageStatus.PENDING,
                msg_id='text-before-claim',
            )
        )
        entered, release, voice_queued = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        self.addCleanup(release.set)

        def block_writer() -> bool:
            """Pauses the actual socket owner before following frame claims."""
            entered.set()
            return release.wait(2.0)

        self.sender_state.send_frame(sender, b'/read emission-barrier\n', block_writer)
        self.assertTrue(entered.wait(2.0))
        original_send = self.sender_state.send_frame

        def observe_enqueue(
            conn: socket.socket, frame: bytes, claim: object = None
        ) -> None:
            """Signals after the real Voice BEGIN has joined the blocked writer queue."""
            original_send(conn, frame, claim)
            if frame.startswith(b'/drop_voice_begin '):
                voice_queued.set()

        rows = f.sender_messages.get_pending_outbox()
        ordered = [row for row in rows if row[2] == ContentType.TEXT.value] + [
            voice_row
        ]
        worker = threading.Thread(
            target=self.delivery.process_batch, args=(f.receiver_onion, ordered)
        )
        self.threads.append(worker)
        with (
            patch.object(self.sender_state, 'send_frame', side_effect=observe_enqueue),
            patch.object(
                self.receiver_router,
                'process_drop_voice_frame',
                wraps=self.receiver_router.process_drop_voice_frame,
            ) as incoming_voice,
            patch.object(
                self.receiver_router,
                'process_incoming_drop_over_session',
                wraps=self.receiver_router.process_incoming_drop_over_session,
            ) as incoming_text,
        ):
            worker.start()
            self.assertTrue(voice_queued.wait(2.0))
            with self.delivery._operation_lock:
                f.sender_messages.clear_messages(f.receiver_onion, cancel_pending=True)
            release.set()
            worker.join(2.0)
            self.assertFalse(worker.is_alive())
            writer = self.sender_state._socket_writers[sender]
            self.assertTrue(writer.flush(2.0))
            incoming_voice.assert_not_called()
            incoming_text.assert_not_called()
        self.assertEqual(f.sender_messages.get_pending_outbox(), [])
        self.assertEqual(self.sender_state._drop_transfers, {})
        self.assertIsNone(
            f.receiver_messages.get_voice_payload(
                f.sender_onion, voice_row[4], MessageDirection.IN
            )
        )
        self.assertFalse(
            any(
                entry.event_code is HistoryEvent.FAILED
                for entry in self.sender_history.get_raw_history(f.receiver_onion)
            )
        )

    def test_mailbox_bounds_correlation_and_old_cleanup_preserves_current_lease(
        self,
    ) -> None:
        """Wrong identities cannot ACK; overflow cancels; old cleanup cannot revoke retry."""
        f = self.fixture
        sender, receiver = self._connect()
        with patch.object(Constants, 'DROP_SESSION_MAX_TRANSFERS', 0):
            with self.assertRaises(ConnectionError):
                self.sender_state.begin_drop_transfer(
                    f.receiver_onion, sender, 'voice-full', 1.0, self.stop_flag
                )
        old = self.sender_state.begin_drop_transfer(
            f.receiver_onion, sender, 'voice-bound', 1.0, self.stop_flag
        )
        for onion, conn, msg_id in (
            (f.sender_onion, sender, 'voice-bound'),
            (f.receiver_onion, receiver, 'voice-bound'),
            (f.receiver_onion, sender, 'another-id'),
        ):
            self.assertFalse(
                self.sender_state.acknowledge_drop_transfer(
                    onion, conn, msg_id, '/voice_ack voice-bound 0'
                )
            )
        self.assertTrue(
            self.sender_state.acknowledge_drop_transfer(
                f.receiver_onion, sender, 'voice-bound', '/voice_ack voice-bound 0'
            )
        )
        self.assertTrue(
            self.sender_state.acknowledge_drop_transfer(
                f.receiver_onion, sender, 'voice-bound', '/voice_ack voice-bound 0'
            )
        )
        self.assertIsNone(old.read_line())
        self.sender_state.finish_drop_transfer(sender, old)
        current = self.sender_state.begin_drop_transfer(
            f.receiver_onion, sender, 'voice-bound', 1.0, self.stop_flag
        )
        self.sender_state.finish_drop_transfer(sender, old)
        self.assertTrue(self.sender_state.is_drop_transfer_current(sender, current))
        self.sender_state.finish_drop_transfer(sender, current)


if __name__ == '__main__':
    unittest.main()
