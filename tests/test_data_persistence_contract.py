"""Regression tests for durable peer, message, and history persistence semantics."""

# ruff: noqa: E402

import sys
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.data import ContactManager, HistoryActor, HistoryEvent, HistoryManager
from metor.core.api import ContentType, Delivery
from metor.data.contact import ContactOperationType
from metor.data.message import (
    MessageDirection,
    MessageManager,
    MessageStatus,
)
from metor.data.profile import ProfileManager
from metor.data.sql import SqlManager
from metor.utils import Constants


class DataPersistenceContractTests(unittest.TestCase):
    """
    Covers data persistence contract regression scenarios.
    """

    def setUp(self) -> None:
        """
        Prepares shared fixtures for each test case.

        Args:
            None

        Returns:
            None
        """

        self._temp_dir = TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self._data_root = Path(self._temp_dir.name) / Constants.DATA_DIR
        self._data_patch = patch.object(Constants, 'DATA', self._data_root)
        self._data_patch.start()
        self.addCleanup(self._data_patch.stop)

        self._pm = ProfileManager('default')
        self._pm.initialize()

        self._cm = ContactManager(self._pm)
        self._hm = HistoryManager(self._pm)
        self._mm = MessageManager(self._pm)

        self.addCleanup(SqlManager.close_connection, self._pm.paths.get_db_file())

    def test_discovered_peer_can_be_renamed_without_promotion(self) -> None:
        """
        Verifies that discovered peer can be renamed without promotion.

        Args:
            None

        Returns:
            None
        """

        onion = 'a' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        alias = self._cm.ensure_alias_for_onion(onion)

        self.assertIsNotNone(alias)
        assert alias is not None

        result = self._cm.rename_contact(alias, 'renamed')

        self.assertTrue(result.success)
        self.assertIs(result.operation_type, ContactOperationType.ALIAS_RENAMED)
        self.assertEqual(self._cm.get_alias_by_onion(onion), 'renamed')
        snapshot = self._cm.get_contacts_data()
        self.assertEqual(
            tuple(entry.alias for entry in snapshot.discovered), ('renamed',)
        )

    def test_promotion_keeps_the_same_discovered_peer_identity(self) -> None:
        """
        Verifies that promotion keeps the same discovered peer identity.

        Args:
            None

        Returns:
            None
        """

        onion = 'b' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        alias = self._cm.ensure_alias_for_onion(onion)

        self.assertIsNotNone(alias)
        assert alias is not None

        result = self._cm.promote_discovered_peer(alias)

        self.assertTrue(result.success)
        self.assertIs(result.operation_type, ContactOperationType.PEER_PROMOTED)
        self.assertEqual(self._cm.get_onion_by_alias(alias), onion)
        self.assertEqual(self._cm.get_all_contacts(), [alias])
        self.assertEqual(self._cm.get_contacts_data().discovered, ())

    def test_saved_contact_with_history_and_ram_alias_is_only_downgraded(self) -> None:
        """
        Verifies that saved contact with history and ram alias is only downgraded.

        Args:
            None

        Returns:
            None
        """

        onion = 'c' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        alias = self._cm.ensure_alias_for_onion(onion)

        self.assertIsNotNone(alias)
        assert alias is not None

        promote_result = self._cm.promote_discovered_peer(alias)
        self.assertTrue(promote_result.success)
        self._hm.log_event(HistoryEvent.REQUESTED, onion, actor=HistoryActor.LOCAL)

        result = self._cm.remove_contact(alias)

        self.assertTrue(result.success)
        self.assertIs(result.operation_type, ContactOperationType.CONTACT_DOWNGRADED)
        self.assertEqual(self._cm.get_alias_by_onion(onion), alias)
        self.assertTrue(self._cm.is_session_alias(alias))

    def test_saved_contact_with_history_and_custom_alias_is_anonymized_on_remove(
        self,
    ) -> None:
        """
        Verifies that saved contact with history and custom alias is anonymized on remove.

        Args:
            None

        Returns:
            None
        """

        onion = '2' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        alias = self._cm.ensure_alias_for_onion(onion)

        self.assertIsNotNone(alias)
        assert alias is not None

        promote_result = self._cm.promote_discovered_peer(alias)
        self.assertTrue(promote_result.success)
        rename_result = self._cm.rename_contact(alias, 'saved-custom')
        self.assertTrue(rename_result.success)
        self._hm.log_event(HistoryEvent.REQUESTED, onion, actor=HistoryActor.LOCAL)

        result = self._cm.remove_contact('saved-custom')

        self.assertTrue(result.success)
        self.assertIs(
            result.operation_type,
            ContactOperationType.CONTACT_REMOVED_DOWNGRADED,
        )
        new_alias = str(result.params['new_alias'])
        self.assertNotEqual(new_alias, 'saved-custom')
        self.assertEqual(self._cm.get_alias_by_onion(onion), new_alias)
        self.assertTrue(self._cm.is_session_alias(new_alias))

    def test_discovered_peer_with_history_is_only_anonymized_on_remove(self) -> None:
        """
        Verifies that discovered peer with history is only anonymized on remove.

        Args:
            None

        Returns:
            None
        """

        onion = 'd' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        alias = self._cm.ensure_alias_for_onion(onion)

        self.assertIsNotNone(alias)
        assert alias is not None

        rename_result = self._cm.rename_contact(alias, 'custom-discovered')
        self.assertTrue(rename_result.success)
        self._hm.log_event(HistoryEvent.REQUESTED, onion, actor=HistoryActor.LOCAL)

        result = self._cm.remove_contact('custom-discovered')

        self.assertTrue(result.success)
        self.assertIs(result.operation_type, ContactOperationType.PEER_ANONYMIZED)
        new_alias = str(result.params['new_alias'])
        self.assertNotEqual(new_alias, 'custom-discovered')
        self.assertEqual(self._cm.get_alias_by_onion(onion), new_alias)
        self.assertTrue(self._cm.is_session_alias(new_alias))

    def test_cleanup_orphans_only_deletes_discovered_peers_without_refs(self) -> None:
        """
        Verifies that cleanup orphans only deletes discovered peers without refs.

        Args:
            None

        Returns:
            None
        """

        kept_onion = 'e' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        removed_onion = 'f' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        kept_alias = self._cm.ensure_alias_for_onion(kept_onion)
        removed_alias = self._cm.ensure_alias_for_onion(removed_onion)

        self.assertIsNotNone(kept_alias)
        self.assertIsNotNone(removed_alias)
        assert kept_alias is not None
        assert removed_alias is not None

        self._mm.queue_message(
            contact_onion=kept_onion,
            direction=MessageDirection.IN,
            delivery=Delivery.DROP,
            content_type=ContentType.TEXT,
            payload='hello',
            status=MessageStatus.UNREAD,
            msg_id='msg-1',
            timestamp='2026-04-17T10:00:00+00:00',
        )

        removed = self._cm.cleanup_orphans([])

        self.assertEqual(removed, [(removed_alias, removed_onion)])
        self.assertEqual(self._cm.get_alias_by_onion(removed_onion), None)
        self.assertEqual(self._cm.get_alias_by_onion(kept_onion), kept_alias)

    def test_saved_contact_without_refs_is_finally_deleted(self) -> None:
        """
        Verifies that saved contact without refs is finally deleted.

        Args:
            None

        Returns:
            None
        """

        onion = '1' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        alias = self._cm.ensure_alias_for_onion(onion)

        self.assertIsNotNone(alias)
        assert alias is not None

        promote_result = self._cm.promote_discovered_peer(alias)
        self.assertTrue(promote_result.success)

        result = self._cm.remove_contact(alias)

        self.assertTrue(result.success)
        self.assertIs(result.operation_type, ContactOperationType.CONTACT_REMOVED)
        self.assertIsNone(self._cm.get_alias_by_onion(onion))

    def test_inbox_consume_rows_carry_msg_id(self) -> None:
        """
        Verifies get_and_read_inbox includes message ID and content discriminator.

        Regression guard for the MarkRead consume path: the SQL row must expose
        the stable message id so the read-receipt chain can address the message.
        A four-field row made the handler index message[4] and crash with
        InternalErrorEvent.

        Args:
            None

        Returns:
            None
        """
        onion: str = 'c' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        self._cm.ensure_alias_for_onion(onion)
        self._mm.queue_message(
            contact_onion=onion,
            direction=MessageDirection.IN,
            delivery=Delivery.DROP,
            content_type=ContentType.TEXT,
            payload='hello e2e',
            status=MessageStatus.UNREAD,
            msg_id='e2e-consume-msg-1',
        )

        rows = self._mm.get_and_read_inbox(onion)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 6)
        self.assertEqual(rows[0][4], 'e2e-consume-msg-1')
        self.assertEqual(str(rows[0][2]), 'hello e2e')
        self.assertEqual(str(rows[0][1]), Delivery.DROP.value)
        self.assertEqual(str(rows[0][5]), ContentType.TEXT.value)

    def test_selective_fallback_is_atomic_and_preserves_message_identity(self) -> None:
        """Promotes only a fully valid selected LIVE subset into the DROP outbox."""
        onion = '7' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        self._cm.ensure_alias_for_onion(onion)
        for msg_id, payload in (('live-1', 'one'), ('live-2', 'two')):
            self._mm.queue_message(
                contact_onion=onion,
                direction=MessageDirection.OUT,
                delivery=Delivery.LIVE,
                content_type=ContentType.TEXT,
                payload=payload,
                status=MessageStatus.PENDING,
                msg_id=msg_id,
            )

        self.assertIsNone(
            self._mm.promote_pending_live_to_drop(onion, ['live-1', 'does-not-exist'])
        )
        self.assertEqual(
            [record.msg_id for record in self._mm.get_pending_live_outbox(onion)],
            ['live-1', 'live-2'],
        )

        promoted = self._mm.promote_pending_live_to_drop(onion, ['live-1'])
        self.assertIsNotNone(promoted)
        assert promoted is not None
        self.assertEqual([record.msg_id for record in promoted], ['live-1'])
        self.assertEqual(
            [record.msg_id for record in self._mm.get_pending_live_outbox(onion)],
            ['live-2'],
        )
        self.assertIn('live-1', [row[4] for row in self._mm.get_pending_outbox()])

    def test_fallback_never_promotes_an_unfinished_voice_turn(self) -> None:
        """Leaves recording Voice LIVE-pending until its logical turn finalizes."""
        onion = '6' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        self._cm.ensure_alias_for_onion(onion)
        metadata = {
            'type': 'voice',
            'blob_id': 'ab' * 32,
            'codec': 'opus',
            'size_bytes': 5,
            'duration_ms': None,
            'finalized': False,
            'acknowledged_offset': 0,
        }
        self._mm.queue_message(
            contact_onion=onion,
            direction=MessageDirection.OUT,
            delivery=Delivery.LIVE,
            content_type=ContentType.VOICE,
            payload=json.dumps(metadata),
            status=MessageStatus.PENDING,
            msg_id='voice-recording',
            retained_bytes=5,
        )

        self.assertIsNone(
            self._mm.promote_pending_live_to_drop(onion, ['voice-recording'])
        )
        self.assertEqual(self._mm.promote_pending_live_to_drop(onion), [])
        metadata['finalized'] = True
        self.assertTrue(
            self._mm.update_retained_bytes(
                onion, 'voice-recording', 5, json.dumps(metadata)
            )
        )

        promoted = self._mm.promote_pending_live_to_drop(onion, ['voice-recording'])
        self.assertIsNotNone(promoted)
        assert promoted is not None
        self.assertEqual([record.msg_id for record in promoted], ['voice-recording'])

    def test_delivery_filtered_consume_does_not_touch_other_projection(self) -> None:
        """Consumes LIVE without marking the same peer's DROP inbox as read."""
        onion = '8' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        self._cm.ensure_alias_for_onion(onion)
        for delivery, msg_id in (
            (Delivery.DROP, 'drop-unread'),
            (Delivery.LIVE, 'live-unread'),
        ):
            self._mm.queue_message(
                contact_onion=onion,
                direction=MessageDirection.IN,
                delivery=delivery,
                content_type=ContentType.TEXT,
                payload=msg_id,
                status=MessageStatus.UNREAD,
                msg_id=msg_id,
            )

        consumed = self._mm.get_and_read_inbox(onion, Delivery.LIVE)
        self.assertEqual([row[4] for row in consumed], ['live-unread'])
        self.assertEqual(self._mm.get_unread_live_count(onion), 0)
        self.assertEqual(self._mm.get_unread_drop_count(onion), 1)

    def test_clear_messages_preserves_live_and_pending_drop_delivery(self) -> None:
        """Clears DROP presentation while retaining all delivery-critical state."""
        onion = '9' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        self._cm.ensure_alias_for_onion(onion)
        self._mm.queue_message(
            contact_onion=onion,
            direction=MessageDirection.OUT,
            delivery=Delivery.LIVE,
            content_type=ContentType.TEXT,
            payload='recover me',
            status=MessageStatus.PENDING,
            msg_id='live-pending',
        )
        self._mm.queue_message(
            contact_onion=onion,
            direction=MessageDirection.OUT,
            delivery=Delivery.DROP,
            content_type=ContentType.TEXT,
            payload='deliver me',
            status=MessageStatus.PENDING,
            msg_id='drop-pending',
        )

        self._mm.clear_messages(onion)

        self.assertEqual(
            [record.msg_id for record in self._mm.get_pending_live_outbox(onion)],
            ['live-pending'],
        )
        self.assertIn('drop-pending', [row[4] for row in self._mm.get_pending_outbox()])

    def test_single_drop_delete_rejects_pending_delivery(self) -> None:
        """Prevents local delete from becoming a hidden DROP cancellation path."""
        onion = 'a' * Constants.TOR_V3_ONION_ADDRESS_LENGTH
        self._cm.ensure_alias_for_onion(onion)
        self._mm.queue_message(
            contact_onion=onion,
            direction=MessageDirection.OUT,
            delivery=Delivery.DROP,
            content_type=ContentType.TEXT,
            payload='still sending',
            status=MessageStatus.PENDING,
            msg_id='pending-drop',
        )
        outcome = self._mm.delete_drop_message(onion, 'pending-drop')
        self.assertEqual(outcome.value, 'pending_delivery')
        self.assertIn('pending-drop', [row[4] for row in self._mm.get_pending_outbox()])

    def test_add_contact_rejects_invalid_onion_format(self) -> None:
        """
        Verifies that add_contact rejects malformed onion identities.

        Regression guard: arbitrary strings like 'kein-onion' were accepted and
        stored as contacts, polluting the address book.

        Args:
            None

        Returns:
            None
        """
        result = self._cm.add_contact('badpeer', 'kein-onion')
        self.assertFalse(result.success)
        self.assertIs(result.operation_type, ContactOperationType.INVALID_ONION)
        self.assertIsNone(self._cm.get_alias_by_onion('kein-onion'))

    def test_add_contact_accepts_valid_v3_onion(self) -> None:
        """
        Verifies that a structurally valid v3 onion is accepted.

        Args:
            None

        Returns:
            None
        """
        result = self._cm.add_contact(
            'goodpeer',
            'gqncaw2sjprzovtdquir4etnswg2eyvomid4bsbdld2p5roay5vmvtyd.onion',
        )
        self.assertTrue(result.success)
        self.assertIs(result.operation_type, ContactOperationType.CONTACT_ADDED)


if __name__ == '__main__':
    unittest.main()
