"""Atomic case-preserving alias decisions across real encrypted persistence managers."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from metor.core.key import KeyManager
from metor.data import ContactManager
from metor.data.contact import ContactOperationResult, ContactOperationType
from metor.data.profile import ProfileManager
from metor.data.sql import PeerRepository, SqlManager
from metor.utils import Constants
from test_gui_contacts import address


class ContactAliasAtomicityTests(unittest.TestCase):
    """Holds one actual alias check while a second manager attempts the equivalent label."""

    def setUp(self) -> None:
        """Opens two manager instances on the same SQLCipher profile and pooled connection."""
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data = patch.object(Constants, 'DATA', Path(temporary.name))
        data.start()
        self.addCleanup(data.stop)
        self.profile = ProfileManager('atomic-aliases')
        self.profile.initialize()
        key_manager = KeyManager(self.profile, 'test-password')
        key = key_manager.get_database_key()
        self.addCleanup(SqlManager.close_connection, self.profile.paths.get_db_file())
        self.first = ContactManager(self.profile, key)
        self.second = ContactManager(self.profile, key)

    def _contend(self, *, rename: bool) -> list[ContactOperationResult]:
        """Reproduces the old check/write interleaving without replacing SQL or domain operations.

        Args:
            rename: Whether both saved peers rename instead of adding contacts.
        Returns:
            list[ContactOperationResult]: Actual competing domain outcomes.
        """
        peers = address(71), address(72)
        if rename:
            self.assertTrue(self.first.add_contact('First', peers[0]).success)
            self.assertTrue(self.second.add_contact('Second', peers[1]).success)
        checked = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        competing_check = threading.Event()
        original = PeerRepository.alias_is_taken

        def held_check(
            repository: PeerRepository, alias: str, except_onion: str = ''
        ) -> bool:
            """Pauses the first free check while retaining its production transaction lock."""
            taken = original(repository, alias, except_onion)
            if alias.casefold() == 'strasse':
                if checked.is_set():
                    competing_check.set()
                else:
                    checked.set()
                    if not release.wait(5):
                        raise TimeoutError('Test did not release the alias mutation')
            return taken

        def mutate(index: int) -> ContactOperationResult:
            """Invokes the actual independent manager after synchronizing only the test caller."""
            manager = self.first if index == 0 else self.second
            if index == 1:
                second_started.set()
            alias = 'Straße' if index == 0 else 'STRASSE'
            return (
                manager.rename_contact(
                    'First' if index == 0 else 'Second', alias, peers[index]
                )
                if rename
                else manager.add_contact(alias, peers[index])
            )

        with patch.object(PeerRepository, 'alias_is_taken', held_check):
            with ThreadPoolExecutor(max_workers=2) as workers:
                first = workers.submit(mutate, 0)
                try:
                    self.assertTrue(checked.wait(5))
                    second = workers.submit(mutate, 1)
                    self.assertTrue(second_started.wait(5))
                    self.assertFalse(competing_check.wait(0.1))
                finally:
                    release.set()
                results = [first.result(5), second.result(5)]
        self.assertEqual(sum(result.success for result in results), 1)
        self.assertEqual(results[1].operation_type, ContactOperationType.ALIAS_IN_USE)
        self.assertEqual(self.first.get_onion_by_alias('strasse'), peers[0])
        labels = [
            entry
            for entry in self.first.get_contacts_data().saved
            if entry.alias.casefold() == 'strasse'
        ]
        self.assertEqual(
            [(entry.alias, entry.onion) for entry in labels], [('Straße', peers[0])]
        )
        return results

    def test_parallel_add_keeps_one_casefold_alias_owner(self) -> None:
        """Two spelling variants cannot both pass the free-label check and insert."""
        results = self._contend(rename=False)
        self.assertEqual(results[0].operation_type, ContactOperationType.CONTACT_ADDED)

    def test_parallel_rename_keeps_one_casefold_alias_owner(self) -> None:
        """Two independent saved identities cannot acquire equivalent new display labels."""
        results = self._contend(rename=True)
        self.assertEqual(results[0].operation_type, ContactOperationType.ALIAS_RENAMED)


if __name__ == '__main__':
    unittest.main()
