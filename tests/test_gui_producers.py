"""Disposable Voice ownership through real Core IPC, SQLCipher and blob storage."""

import atexit
import base64
import json
import socket
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from metor.client import MetorClient, build_session_auth_proof
from metor.client.session import MetorRequestRejectedError
from metor.core.api import (
    AppendVoiceChunkCommand,
    BeginVoiceCommand,
    CancelVoiceCommand,
    ClientRestrictedEvent,
    CommitVoiceCommand,
    Delivery,
    FinalizeVoiceCommand,
    GetVoiceChunkCommand,
    ListRetainedMessagesCommand,
    MessageDirectionCode,
    RegisterVoiceOwnerCommand,
    ReleaseVoiceOwnerCommand,
    RestrictClientCommand,
    RetainedMessagesEvent,
    VoiceChunkAcceptedEvent,
    VoiceDataEvent,
    VoiceCommittedEvent,
    VoiceFinalizedEvent,
    VoiceOwnerRegisteredEvent,
    VoiceOwnerReleasedEvent,
    VoiceStartedEvent,
    IpcEvent,
    MessageOutcomeEvent,
    MessageStatusCode,
)
from metor.core.daemon.managed.engine import Daemon
from metor.core.daemon.managed.local_auth import create_session_auth_context
from metor.core.daemon.managed.producers import ProducerCleanup, VoiceProducerService
from metor.core.key import KeyManager
from metor.data import ContactManager, HistoryManager, MessageDirection, MessageManager
from metor.data.blob import BlobLifecycle, EncryptedBlobStore
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.utils import Constants


class GuiProducerTests(unittest.TestCase):
    """Tests production persistence and authorization with no real peer or microphone."""

    def setUp(self) -> None:
        """Creates an isolated protected daemon and two independently authenticated clients."""
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        patcher = patch.object(Constants, 'DATA', root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pm = ProfileManager('voice-owned')
        self.pm.initialize()
        km = KeyManager(self.pm, 'test-password')
        key = km.get_database_key()
        self.addCleanup(SqlManager.close_connection, self.pm.paths.get_db_file())
        self.contacts = ContactManager(self.pm, key)
        self.messages = MessageManager(self.pm, key)
        self.blobs = EncryptedBlobStore(root / 'persistent', root / 'temporary', key)
        self.addCleanup(self.blobs.close)
        self.onion = 'b' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        self.contacts.ensure_alias_for_onion(self.onion)
        tor = Mock()
        tor.onion = 'a' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        tor.is_running.return_value = True
        with patch('metor.core.daemon.managed.engine.daemon.signal.signal'):
            self.daemon = Daemon(
                self.pm,
                km,
                tor,
                self.contacts,
                HistoryManager(self.pm, key),
                self.messages,
                self.blobs,
                session_auth=create_session_auth_context('test-password'),
                require_session_auth=True,
            )
        atexit.unregister(self.daemon.stop)
        self.addCleanup(self.daemon.stop)
        self.daemon._ipc.start()
        self.client = self.make_client()
        self.other = self.make_client()
        self.repository = SqlManager.opened_voice_producers(self.pm.paths.get_db_file())
        self._last_capture_timings: dict[str, float] = {}
        self.owner = self.client.request(
            RegisterVoiceOwnerCommand(), VoiceOwnerRegisteredEvent
        ).owner_token

    def make_client(self) -> MetorClient:
        """Authenticates a public SDK connection with one-use password proofs."""
        provider = Mock()
        provider.get_session_auth_proof.side_effect = lambda challenge, salt: (
            build_session_auth_proof('test-password', challenge, salt)
        )
        client = MetorClient(
            self.daemon._ipc.port,
            auth_provider=provider,
            timeout=Constants.DEFAULT_IPC_TIMEOUT,
        )
        self.addCleanup(client.disconnect)
        self.assertIsNotNone(client.bootstrap())
        return client

    def capture(
        self, msg_id: str, delivery: Delivery = Delivery.DROP
    ) -> dict[str, object]:
        """Admits actual bytes through the owned public Begin/Append operations."""
        self._last_capture_timings = {}
        begin_started = time.monotonic()
        try:
            self.client.request(
                BeginVoiceCommand(
                    self.onion, delivery, msg_id, 'pcm_s16le_16000_mono', self.owner
                ),
                VoiceStartedEvent,
            )
        finally:
            self._last_capture_timings['begin_voice_seconds'] = (
                time.monotonic() - begin_started
            )
        append_started = time.monotonic()
        try:
            self.client.request(
                AppendVoiceChunkCommand(
                    msg_id,
                    0,
                    base64.b64encode(b'\x00\x01' * 320).decode(),
                    self.owner,
                ),
                VoiceChunkAcceptedEvent,
            )
        finally:
            self._last_capture_timings['append_voice_seconds'] = (
                time.monotonic() - append_started
            )
        record = self.messages.get_voice_payload(
            self.onion, msg_id, MessageDirection.OUT
        )
        self.assertIsNotNone(record)
        return json.loads(record.payload)

    def test_owner_is_connection_bound_and_inventory_qualified(self) -> None:
        """Knowing another owner's token/ID cannot read, append or cancel its draft."""
        self.capture('owned')
        for command, expected in (
            (
                AppendVoiceChunkCommand('owned', 640, 'AAE=', self.owner),
                VoiceChunkAcceptedEvent,
            ),
            (
                GetVoiceChunkCommand(
                    self.onion, 'owned', MessageDirectionCode.OUT, 0, 640, self.owner
                ),
                VoiceDataEvent,
            ),
            (
                CancelVoiceCommand(self.onion, 'owned', self.owner),
                VoiceOwnerReleasedEvent,
            ),
            (
                ListRetainedMessagesCommand(owner_token=self.owner),
                RetainedMessagesEvent,
            ),
        ):
            with (
                self.subTest(command=type(command).__name__),
                self.assertRaises(MetorRequestRejectedError),
            ):
                self.other.request(command, expected)
        self.assertEqual(
            self.other.request(
                ListRetainedMessagesCommand(), RetainedMessagesEvent
            ).messages,
            [],
        )
        owned = self.client.request(
            ListRetainedMessagesCommand(owner_token=self.owner), RetainedMessagesEvent
        )
        self.assertEqual([entry.msg_id for entry in owned.messages], ['owned'])
        with self.assertRaises(MetorRequestRejectedError):
            self.client.request(
                BeginVoiceCommand(
                    self.onion, Delivery.DROP, 'collision', 'opus', self.owner
                ),
                VoiceStartedEvent,
            )
        self.assertIsNone(self.repository.get('collision'))

    def test_release_cleans_only_owner_drafts_and_preserves_generic_drafts(
        self,
    ) -> None:
        """Restricted screen lock preserves staging; explicit owner release deletes it."""
        payload = self.capture('disposable')
        self.other.begin_voice(self.onion, Delivery.DROP, 'generic', 'opus')
        self.client.request(RestrictClientCommand(), ClientRestrictedEvent)
        self.assertIsNotNone(self.repository.get('disposable'))
        result = self.client.request(
            ReleaseVoiceOwnerCommand(self.owner), VoiceOwnerReleasedEvent
        )
        self.assertFalse(result.cleanup_pending)
        self.assertIsNone(self.repository.get('disposable'))
        self.assertIsNone(
            self.messages.get_voice_payload(
                self.onion, 'disposable', MessageDirection.OUT
            )
        )
        self.assertIsNotNone(
            self.messages.get_voice_payload(self.onion, 'generic', MessageDirection.OUT)
        )
        for blob_id in [payload['blob_id'], *payload['chunk_ids']]:
            self.assertFalse(self.blobs.exists(blob_id, BlobLifecycle.TEMPORARY))
            self.assertFalse(self.blobs.exists(blob_id, BlobLifecycle.PERSISTENT))

    def test_committed_drop_survives_unknown_commit_response(self) -> None:
        """Cleanup reconciles a committed receipt even when transfer bookkeeping is lost."""
        self.capture('committed')
        self.client.request(
            FinalizeVoiceCommand('committed', 20, self.owner), VoiceFinalizedEvent
        )
        service = self.daemon._command_dispatcher._producers
        with patch.object(service, 'after'):
            self.client.request(
                CommitVoiceCommand(self.onion, 'committed', self.owner),
                VoiceCommittedEvent,
            )
        self.assertIsNotNone(self.repository.get('committed'))
        result = self.client.request(
            ReleaseVoiceOwnerCommand(self.owner), VoiceOwnerReleasedEvent
        )
        self.assertFalse(result.cleanup_pending)
        record = self.messages.get_voice_payload(
            self.onion, 'committed', MessageDirection.OUT
        )
        self.assertEqual(record.status, 'pending')
        payload = json.loads(record.payload)
        self.assertTrue(
            self.blobs.exists(payload['chunk_ids'][0], BlobLifecycle.PERSISTENT)
        )

    def test_failed_blob_cleanup_is_journaled_and_retryable_after_receipt_removal(
        self,
    ) -> None:
        """A deletion failure after SQL cancellation retains all object identifiers."""
        payload = self.capture('cleanup-failure')
        with patch.object(
            self.blobs, 'delete', side_effect=OSError('injected deletion failure')
        ):
            result = self.client.request(
                ReleaseVoiceOwnerCommand(self.owner), VoiceOwnerReleasedEvent
            )
        self.assertTrue(result.cleanup_pending)
        item = self.repository.get('cleanup-failure')
        self.assertEqual(json.loads(item.cleanup_payload), payload)
        self.assertIsNone(
            self.messages.get_voice_payload(
                self.onion, 'cleanup-failure', MessageDirection.OUT
            )
        )
        with self.daemon._domain_operation_lock:
            self.daemon._command_dispatcher.retry_voice_cleanup()
        self.assertIsNone(self.repository.get('cleanup-failure'))
        self.assertFalse(
            self.blobs.exists(payload['chunk_ids'][0], BlobLifecycle.TEMPORARY)
        )

    def test_interrupted_live_finalizes_the_accepted_prefix(self) -> None:
        """Producer revocation preserves authorized LIVE bytes through normal fallback."""
        self.capture('interrupted', Delivery.LIVE)
        with patch.object(self.messages, 'update_retained_bytes', return_value=False):
            result = self.client.request(
                ReleaseVoiceOwnerCommand(self.owner), VoiceOwnerReleasedEvent
            )
        self.assertTrue(result.cleanup_pending)
        self.assertIsNotNone(self.repository.get('interrupted'))
        record = self.messages.get_voice_payload(
            self.onion, 'interrupted', MessageDirection.OUT
        )
        self.assertEqual(json.loads(record.payload)['size_bytes'], 640)
        inventory = self.other.request(
            ListRetainedMessagesCommand(), RetainedMessagesEvent
        )
        item = next(
            entry for entry in inventory.messages if entry.msg_id == 'interrupted'
        )
        self.assertTrue(item.producer_interrupted)
        self.assertTrue(item.can_retry_finalization)
        self.other.request(FinalizeVoiceCommand('interrupted'), VoiceFinalizedEvent)
        self.assertIsNone(self.repository.get('interrupted'))
        record = self.messages.get_voice_payload(
            self.onion, 'interrupted', MessageDirection.OUT
        )
        metadata = json.loads(record.payload)
        self.assertTrue(metadata['finalized'])
        self.assertEqual(metadata['size_bytes'], 640)

    def test_recovery_response_waits_for_release_and_broadcasts_uncorrelated(
        self,
    ) -> None:
        """The recovery request completes only after producer ownership is gone."""
        self.capture('barrier', Delivery.LIVE)
        with patch.object(self.messages, 'update_retained_bytes', return_value=False):
            result = self.client.request(
                ReleaseVoiceOwnerCommand(self.owner), VoiceOwnerReleasedEvent
            )
        self.assertTrue(result.cleanup_pending)

        first_observed = threading.Event()
        second_observed = threading.Event()
        first_events: list[VoiceFinalizedEvent] = []
        second_events: list[VoiceFinalizedEvent] = []

        def observe_first(event: IpcEvent) -> None:
            if isinstance(event, VoiceFinalizedEvent) and event.msg_id == 'barrier':
                first_events.append(event)
                first_observed.set()

        def observe_second(event: IpcEvent) -> None:
            if isinstance(event, VoiceFinalizedEvent) and event.msg_id == 'barrier':
                second_events.append(event)
                second_observed.set()

        self.client._on_event = observe_first
        self.other._on_event = observe_second
        release_entered = threading.Event()
        allow_release = threading.Event()
        original_release = self.repository.release

        def release_with_barrier(item: object) -> None:
            release_entered.set()
            if not allow_release.wait(2):
                raise TimeoutError('test release barrier timed out')
            original_release(item)

        command = FinalizeVoiceCommand('barrier')
        request_result: list[VoiceFinalizedEvent] = []
        request_error: list[BaseException] = []

        def recover() -> None:
            try:
                recovered = self.other.request(command, VoiceFinalizedEvent)
                if recovered is not None:
                    request_result.append(recovered)
            except BaseException as exc:
                request_error.append(exc)

        with patch.object(
            self.repository,
            'release',
            side_effect=release_with_barrier,
        ):
            worker = threading.Thread(target=recover)
            worker.start()
            self.assertTrue(release_entered.wait(2))
            self.assertTrue(first_observed.wait(2))
            self.assertTrue(second_observed.wait(2))
            self.assertTrue(worker.is_alive())
            self.assertIsNotNone(self.repository.get('barrier'))
            allow_release.set()
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(request_error, [])
        self.assertEqual(len(request_result), 1)
        self.assertEqual(request_result[0].request_id, command.request_id)
        self.assertIsNone(self.repository.get('barrier'))
        self.assertEqual(len(first_events), 1)
        self.assertEqual(len(second_events), 1)
        self.assertIsNone(first_events[0].request_id)
        self.assertIsNone(second_events[0].request_id)

        repeated = self.other.request(
            FinalizeVoiceCommand('barrier'), VoiceFinalizedEvent
        )
        self.assertIsNotNone(repeated)
        self.assertEqual(repeated.size_bytes, 640)
        self.assertIsNone(self.repository.get('barrier'))

    def test_recovery_reclaim_false_returns_no_success(self) -> None:
        """A failed reclaim remains retryable and rejects the correlated request."""
        self.capture('reclaim-false', Delivery.LIVE)
        with patch.object(self.messages, 'update_retained_bytes', return_value=False):
            result = self.client.request(
                ReleaseVoiceOwnerCommand(self.owner), VoiceOwnerReleasedEvent
            )
        self.assertTrue(result.cleanup_pending)
        service = self.daemon._command_dispatcher._producers
        false_success = VoiceFinalizedEvent(
            msg_id='reclaim-false',
            onion=self.onion,
            direction=MessageDirectionCode.OUT,
            delivery=Delivery.LIVE,
            size_bytes=640,
        )

        with (
            patch.object(service._cleanup, 'reclaim', return_value=False),
            patch.object(
                service._cleanup,
                'finalization_result',
                return_value=false_success,
            ),
            self.assertRaises(MetorRequestRejectedError) as raised,
        ):
            self.other.request(
                FinalizeVoiceCommand('reclaim-false'), VoiceFinalizedEvent
            )

        self.assertEqual(
            raised.exception.event.reason,
            'persistence_failed',
        )
        self.assertIsNotNone(self.repository.get('reclaim-false'))

        with (
            patch.object(
                service._cleanup,
                'reclaim',
                side_effect=OSError('injected reclaim failure'),
            ),
            self.assertRaises(MetorRequestRejectedError) as failed,
        ):
            self.other.request(
                FinalizeVoiceCommand('reclaim-false'), VoiceFinalizedEvent
            )
        self.assertEqual(failed.exception.event.reason, 'persistence_failed')
        self.assertIsNotNone(self.repository.get('reclaim-false'))

    def test_prewrite_journal_retains_a_blob_after_failed_admission_and_delete(
        self,
    ) -> None:
        """A real object written before SQL failure remains owned and retryable."""
        with (
            patch.object(
                self.messages,
                'queue_message',
                side_effect=OSError('injected admission failure'),
            ),
            patch.object(
                self.blobs, 'delete', side_effect=OSError('injected cleanup failure')
            ),
        ):
            with self.assertRaises(MetorRequestRejectedError):
                self.client.request(
                    BeginVoiceCommand(
                        self.onion, Delivery.DROP, 'prewrite', 'opus', self.owner
                    ),
                    VoiceStartedEvent,
                )
            # Same-connection barrier waits for the failed command's cleanup attempt.
            self.client.runtime_snapshot()
        item = self.repository.get('prewrite')
        self.assertEqual(len(item.allocated_ids), 1)
        self.assertTrue(
            self.blobs.exists(item.allocated_ids[0], BlobLifecycle.TEMPORARY)
        )
        result = self.client.request(
            ReleaseVoiceOwnerCommand(self.owner), VoiceOwnerReleasedEvent
        )
        self.assertFalse(result.cleanup_pending)
        self.assertFalse(
            self.blobs.exists(item.allocated_ids[0], BlobLifecycle.TEMPORARY)
        )
        self.assertIsNone(self.repository.get('prewrite'))

    def test_confirmed_disconnect_invalidates_lease_and_reclaims_draft(self) -> None:
        """The actual IPC disconnect callback performs owner revocation and cleanup."""
        payload = self.capture('lost-client')
        service = self.daemon._command_dispatcher._producers
        original = service.disconnect
        finished = threading.Event()

        def observe(connection: object) -> None:
            original(connection)
            finished.set()

        with patch.object(service, 'disconnect', side_effect=observe):
            self.client.disconnect()
            self.assertTrue(finished.wait(2))
        self.assertIsNone(self.repository.get('lost-client'))
        self.assertFalse(
            self.blobs.exists(payload['chunk_ids'][0], BlobLifecycle.TEMPORARY)
        )
        with self.assertRaises(MetorRequestRejectedError):
            self.other.request(
                ReleaseVoiceOwnerCommand(self.owner), VoiceOwnerReleasedEvent
            )

    def test_snapshot_context_identity_guards_a_late_recording_press(self) -> None:
        """The same peer in a later call cannot inherit an old PTT target token."""
        local, peer = socket.socketpair()
        self.addCleanup(local.close)
        self.addCleanup(peer.close)
        state = self.daemon._transport_state
        state.add_active_connection(self.onion, local)
        snapshot = self.client.runtime_snapshot()
        generation = next(
            item.context_generation
            for item in snapshot.live_contexts
            if item.onion == self.onion
        )
        self.assertIsInstance(generation, int)
        with self.assertRaises(MetorRequestRejectedError):
            self.client.begin_voice(
                self.onion,
                Delivery.LIVE,
                'stale-context',
                'opus',
                owner_token=self.owner,
                context_generation=generation + 1,
            )
        self.client.runtime_snapshot()
        self.assertIsNone(self.repository.get('stale-context'))
        self.assertIsNotNone(
            self.client.begin_voice(
                self.onion,
                Delivery.LIVE,
                'correct-context',
                'opus',
                owner_token=self.owner,
                context_generation=generation,
            )
        )
        self.client.runtime_snapshot()
        state.pop_any_connection(self.onion)
        with self.assertRaises(MetorRequestRejectedError):
            self.client.begin_voice(
                self.onion,
                Delivery.LIVE,
                'ended-context',
                'opus',
                owner_token=self.owner,
                context_generation=generation,
            )
        self.client.runtime_snapshot()
        self.assertIsNone(self.repository.get('ended-context'))

    def test_receipt_outcome_wire_fields_are_validated_enums(self) -> None:
        """Optional receipt enums cannot remain unchecked strings after IPC decoding."""
        event = IpcEvent.from_dict(
            json.loads(
                MessageOutcomeEvent(
                    self.onion,
                    'receipt',
                    MessageDirectionCode.OUT,
                    Delivery.DROP,
                    MessageStatusCode.DRAFT,
                ).to_json()
            )
        )
        self.assertIs(event.delivery, Delivery.DROP)
        self.assertIs(event.status, MessageStatusCode.DRAFT)
        payload = json.loads(event.to_json())
        payload['status'] = 'invented-status'
        with self.assertRaises((TypeError, ValueError)):
            IpcEvent.from_dict(payload)
        for context in (True, 0, -1):
            with self.subTest(context=context), self.assertRaises(ValueError):
                BeginVoiceCommand(
                    self.onion,
                    Delivery.LIVE,
                    'context',
                    'opus',
                    context_generation=context,
                )

    def test_restarted_owner_service_reclaims_orphans_without_restoring_gui_drafts(
        self,
    ) -> None:
        """Fresh runtime ownership reconstructs cleanup from SQL, not a GUI list."""
        try:
            payload = self.capture('restart-draft')
        finally:
            print(
                'GUI_PRODUCER_CAPTURE_TIMING '
                + json.dumps(
                    {
                        phase: round(elapsed, 3)
                        for phase, elapsed in self._last_capture_timings.items()
                    },
                    sort_keys=True,
                )
            )
        self.other.begin_voice(self.onion, Delivery.DROP, 'generic-restart', 'opus')
        fresh = VoiceProducerService(
            ProducerCleanup(
                self.repository,
                self.messages,
                self.blobs,
                self.daemon._network.cancel_voice_draft,
                self.daemon._network.finalize_interrupted_voice,
            ),
            lambda target: target,
            lambda connection, event: None,
            lambda: False,
        )
        with self.daemon._domain_operation_lock:
            self.assertTrue(fresh.retry())
        self.assertIsNone(self.repository.get('restart-draft'))
        self.assertFalse(
            self.blobs.exists(payload['chunk_ids'][0], BlobLifecycle.TEMPORARY)
        )
        self.assertIsNotNone(
            self.messages.get_voice_payload(
                self.onion, 'generic-restart', MessageDirection.OUT
            )
        )


if __name__ == '__main__':
    unittest.main()
