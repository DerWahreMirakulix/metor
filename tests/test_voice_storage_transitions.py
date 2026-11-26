"""Current-profile conversion and Voice retention contracts across filesystem failures."""

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from private_fixtures import PrivateTemporaryDirectory
from metor.core.api import (
    ClearMessagesCommand,
    ClearProfileDbCommand,
    ContentType,
    Delivery,
    DeleteMessageCommand,
    EventType,
)
from metor.core.daemon.handlers.db import DatabaseCommandHandler
from metor.cli.profile.formatting import format_profile_result_payload
from metor.core.api.codes import ProfileOperationCode
from metor.core.key import KeyManager
from metor.data import (
    ContactManager,
    HistoryManager,
    MessageDirection,
    MessageManager,
    MessageStatus,
    Settings,
    SqlManager,
)
from metor.data.blob import (
    BlobLifecycle,
    EncryptedBlobStore,
    PlaintextBlobStore,
    delete_owned_blob,
)
from metor.data.profile import ProfileManager, ProfileSecurityMode
from metor.data.profile.migration import journal
from metor.data.profile.models import ProfileOperationResult, ProfileOperationType
from metor.utils import Constants


class VoiceStorageTransitionsTests(unittest.TestCase):
    """Exercise fresh local profiles with durable receipts and real external objects."""

    def setUp(self) -> None:
        """Create one explicit debug profile and a current-schema message database."""
        root = self.enterContext(PrivateTemporaryDirectory())
        self.enterContext(patch.object(Constants, 'DATA', Path(root)))
        with patch.object(Settings, 'get_bool', return_value=True):
            result = ProfileManager.add_profile_folder(
                'sample', security_mode=ProfileSecurityMode.PLAINTEXT
            )
        self.assertTrue(result.success)
        self.pm = ProfileManager('sample')
        path = self.pm.paths.get_db_file()
        self.sql = SqlManager(path, self.pm.config)
        self.addCleanup(SqlManager.close_connection, path)
        self.store = PlaintextBlobStore(
            self.pm.paths.get_persistent_blob_dir(),
            self.pm.paths.get_temporary_blob_dir(),
        )
        self.addCleanup(self.store.close)
        self.sql.peers.insert('peer', 'Peer', True)

    def _voice(
        self,
        name: str,
        lifecycle: BlobLifecycle,
        direction: MessageDirection = MessageDirection.IN,
        peer: str = 'peer',
    ) -> tuple[str, str]:
        """Commit a segmented DROP receipt using the production persistence primitives."""
        anchor = self.store.put(b'', lifecycle)
        segment = self.store.put(b'audio', lifecycle)
        metadata = json.dumps(
            {
                'type': 'voice',
                'blob_id': anchor,
                'chunk_ids': [segment],
                'chunk_sizes': [5],
                'size_bytes': 5,
                'codec': 'pcm',
                'finalized': True,
                'duration_ms': 20,
            }
        )
        status = (
            MessageStatus.UNREAD
            if direction is MessageDirection.IN
            else MessageStatus.PENDING
        )
        self.sql.messages.queue_message(
            peer,
            direction,
            Delivery.DROP,
            ContentType.VOICE,
            metadata,
            status,
            name,
            retained_bytes=5,
        )
        return anchor, segment

    def _convert(self) -> ProfileOperationResult:
        """Run the same offline conversion called by the CLI profile command."""
        SqlManager.close_connection(self.pm.paths.get_db_file())
        return ProfileManager.migrate_profile_security(
            'sample', ProfileSecurityMode.ENCRYPTED, new_password='fixture password'
        )

    def test_conversion_recovers_finalized_voice_and_discards_unowned_spool(
        self,
    ) -> None:
        """Move the partially promoted turn and verify the bytes with the target key."""
        anchor, segment = self._voice('audio', BlobLifecycle.TEMPORARY)
        self.store.promote(anchor)
        unrelated = self.store.put(b'unowned', BlobLifecycle.TEMPORARY)
        result = self._convert()
        self.assertTrue(result.success, result)
        pm = ProfileManager('sample')
        keys = KeyManager(pm, 'fixture password')
        self.addCleanup(keys.clear_sensitive_state)
        target = EncryptedBlobStore(
            pm.paths.get_persistent_blob_dir(),
            pm.paths.get_temporary_blob_dir(),
            keys.get_blob_key(),
        )
        self.addCleanup(target.close)
        self.assertEqual(target.read(segment), b'audio')
        self.assertEqual(target.read(anchor), b'')
        self.assertFalse(target.exists(unrelated, BlobLifecycle.TEMPORARY))
        self.assertFalse(target.exists(unrelated))
        sql = SqlManager(pm.paths.get_db_file(), pm.config, keys.get_database_key())
        manifest = sql.messages.get_inbound_voice('peer', 'audio')
        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertEqual(json.loads(manifest.payload)['chunk_ids'], [segment])

    def test_missing_finalized_segment_rejects_conversion_before_activation(
        self,
    ) -> None:
        """Missing receipt-owned source bytes leave the original profile authoritative."""
        anchor, segment = self._voice('audio', BlobLifecycle.TEMPORARY)
        self.store.delete(segment, BlobLifecycle.TEMPORARY)
        self.assertFalse(self._convert().success)
        self.assertTrue(ProfileManager('sample').uses_plaintext_storage())
        self.assertTrue(self.store.exists(anchor, BlobLifecycle.TEMPORARY))

    def test_plaintext_cleanup_pending_remains_visible_until_retry(self) -> None:
        """A sharing failure preserves the active target and reports the outstanding source."""
        _, _, backup = journal.migration_paths('sample')
        remove = journal.secure_remove_path

        def remove_except_backup(path: Path) -> None:
            if path == backup and path.exists():
                raise PermissionError('fixture sharing violation')
            remove(path)

        with patch.object(
            journal, 'secure_remove_path', side_effect=remove_except_backup
        ):
            result = self._convert()
            self.assertEqual(
                result.operation_type, ProfileOperationType.SECURITY_CLEANUP_PENDING
            )
            self.assertFalse(result.success)
            self.assertTrue(result.params['cleanup_pending'])
            message = format_profile_result_payload(
                result.success,
                ProfileOperationCode(result.operation_type.value),
                dict(result.params),
            )
            self.assertIn('encrypted storage', message)
            self.assertIn('previous profile copy is still on disk', message)
            self.assertIn('metor profiles migrate sample --to encrypted', message)
            self.assertTrue(backup.exists())
            self.assertTrue(ProfileManager('sample').uses_encrypted_storage())
            self.assertEqual(
                self._convert().operation_type,
                ProfileOperationType.SECURITY_CLEANUP_PENDING,
            )
        self.assertTrue(self._convert().success)
        self.assertFalse(backup.exists())

    def test_selected_voice_deletion_retries_only_the_removed_objects(self) -> None:
        """Deleting one peer's identity leaves a same-ID incoming message for another peer."""
        self.sql.peers.insert('other', 'Other', True)
        selected = self._voice('same-id', BlobLifecycle.PERSISTENT)
        kept = self._voice('same-id', BlobLifecycle.PERSISTENT, peer='other')
        blocked = True

        def remove(blob_id: str) -> None:
            if blocked:
                raise PermissionError('fixture sharing violation')
            delete_owned_blob(self.store, blob_id)

        handler = DatabaseCommandHandler(
            self.pm,
            ContactManager(self.pm),
            HistoryManager(self.pm),
            MessageManager(self.pm),
            lambda: [],
            Mock(),
            delete_persistent_blob_cb=remove,
        )
        result = handler.handle(DeleteMessageCommand('Peer', 'same-id'))
        self.assertEqual(result.event_type, EventType.MESSAGE_DELETE_REJECTED)
        self.assertEqual(getattr(result, 'reason').value, 'persistence_failed')
        self.assertTrue(all(self.store.exists(item) for item in (*selected, *kept)))
        blocked = False
        self.assertEqual(
            handler.handle(ClearMessagesCommand('Peer')).event_type,
            EventType.MESSAGES_CLEARED,
        )
        self.assertFalse(any(self.store.exists(item) for item in selected))
        self.assertTrue(all(self.store.exists(item) for item in kept))
        self.assertTrue(self.sql.messages.has_drop_payload('other', 'same-id'))

    def test_profile_clear_journals_audio_until_retry_and_preserves_queued_delivery(
        self,
    ) -> None:
        """An interrupted removal can be retried using a different DB handler."""
        anchor, segment = self._voice('archive', BlobLifecycle.PERSISTENT)
        kept = self._voice('queued', BlobLifecycle.PERSISTENT, MessageDirection.OUT)
        self.sql.messages.store_inbound_drop_text('peer', 'text', 'hello', None, 20)
        mm = MessageManager(self.pm)
        cm, hm = ContactManager(self.pm), HistoryManager(self.pm)

        def blocked(blob_id: str) -> None:
            if blob_id == segment:
                raise PermissionError('fixture sharing violation')
            delete_owned_blob(self.store, blob_id)

        handler = DatabaseCommandHandler(
            self.pm, cm, hm, mm, lambda: [], Mock(), delete_persistent_blob_cb=blocked
        )
        self.assertEqual(
            handler.handle(ClearProfileDbCommand()).event_type,
            EventType.DB_CLEAR_FAILED,
        )
        self.assertFalse(self.store.exists(anchor))
        self.assertTrue(self.store.exists(segment))
        self.assertFalse(mm.has_drop_payload('peer', 'text'))
        self.assertTrue(all(self.store.exists(blob_id) for blob_id in kept))
        SqlManager.close_connection(self.pm.paths.get_db_file())
        handler = DatabaseCommandHandler(
            self.pm,
            ContactManager(self.pm),
            HistoryManager(self.pm),
            MessageManager(self.pm),
            lambda: [],
            Mock(),
            delete_persistent_blob_cb=lambda blob_id: delete_owned_blob(
                self.store, blob_id
            ),
        )
        self.assertFalse(self.store.exists(segment))
        self.assertEqual(
            handler.handle(ClearMessagesCommand()).event_type,
            EventType.MESSAGES_CLEARED_ALL,
        )
        self.assertTrue(all(self.store.exists(blob_id) for blob_id in kept))
