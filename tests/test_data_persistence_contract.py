"""Regression tests for durable peer, message, and history persistence semantics."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.data import ContactManager, HistoryActor, HistoryEvent, HistoryManager
from metor.data.contact import ContactOperationType
from metor.data.message import (
    MessageDirection,
    MessageManager,
    MessageStatus,
    MessageType,
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
            msg_type=MessageType.DROP_TEXT,
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


if __name__ == '__main__':
    unittest.main()
