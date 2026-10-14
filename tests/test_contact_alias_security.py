"""Raw IPC contact mutations preserve usable aliases and safe recovery targets."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from private_fixtures import PrivateTemporaryDirectory

from metor.client import BufferedIpcEventReader
from metor.core.api import (
    AliasRenamedEvent,
    ContactAddedEvent,
    ContactsDataEvent,
    InvalidTargetEvent,
    IpcEvent,
)
from metor.core.daemon.headless import HeadlessDaemon
from metor.core.key import KeyManager
from metor.data import SqlManager
from metor.data.profile import ProfileManager
from metor.utils import Constants


class ContactAliasSecurityTests(unittest.TestCase):
    """Reject invalid new labels at Core while allowing old labels to be repaired."""

    _ONION = 'gqncaw2sjprzovtdquir4etnswg2eyvomid4bsbdld2p5roay5vmvtyd'

    def setUp(self) -> None:
        """Creates a disposable encrypted profile used by every actual IPC request."""
        temporary = PrivateTemporaryDirectory(prefix='metor-contact-alias-')
        self.addCleanup(temporary.cleanup)
        data = patch.object(Constants, 'DATA', Path(temporary.name))
        data.start()
        self.addCleanup(data.stop)
        self.password = 'disposable-password'
        self.assertTrue(
            ProfileManager.add_profile_folder(
                'contacts', master_password=self.password
            ).success
        )
        self.profile = ProfileManager('contacts')
        self.addCleanup(SqlManager.close_connection, self.profile.paths.get_db_file())

    def exchange(self, command: str, **fields: str) -> IpcEvent:
        """Sends unfiltered JSON through production Core framing and dispatch."""
        with HeadlessDaemon(self.profile, self.password) as daemon:
            channel = daemon.client_socket
            channel.settimeout(Constants.DEFAULT_IPC_TIMEOUT)
            channel.sendall(
                (json.dumps({'command_type': command, **fields}) + '\n').encode()
            )
            event = BufferedIpcEventReader().read_from_socket(channel)
            self.assertIsNotNone(event)
            assert event is not None
            return event

    def test_raw_ipc_rejects_invalid_aliases_without_contact_mutation(self) -> None:
        """Empty/control/multiline labels cannot enter or overwrite the address book."""
        invalid_aliases = (
            '',
            ' \t ',
            'bad\nname',
            'bad\x00name',
            'bad\x7fname',
            'bad\x85name',
            'bad\u2028name',
            'bad\ud800name',
        )
        for alias in invalid_aliases:
            with self.subTest(operation='add', alias=repr(alias)):
                result = self.exchange('add_contact', alias=alias, onion=self._ONION)
                self.assertIsInstance(result, InvalidTargetEvent)
        contacts = self.exchange('get_contacts_list')
        assert isinstance(contacts, ContactsDataEvent)
        self.assertEqual(contacts.saved, [])

        valid_alias = 'Zoë 家庭 👩\u200d💻'
        self.assertIsInstance(
            self.exchange('add_contact', alias=valid_alias, onion=self._ONION),
            ContactAddedEvent,
        )
        for alias in invalid_aliases:
            with self.subTest(operation='rename', alias=repr(alias)):
                result = self.exchange(
                    'rename_contact', old_alias=valid_alias, new_alias=alias
                )
                self.assertIsInstance(result, InvalidTargetEvent)
        contacts = self.exchange('get_contacts_list')
        assert isinstance(contacts, ContactsDataEvent)
        self.assertEqual(
            [(entry.alias, entry.onion) for entry in contacts.saved],
            [(valid_alias, self._ONION)],
        )
        self.assertIsInstance(
            self.exchange(
                'rename_contact', old_alias=valid_alias, new_alias='Alice Bob'
            ),
            AliasRenamedEvent,
        )

    def test_preexisting_control_alias_can_be_renamed_to_a_valid_label(self) -> None:
        """Validation applies only to replacement labels, preserving recovery access."""
        self.assertIsInstance(
            self.exchange('add_contact', alias='original', onion=self._ONION),
            ContactAddedEvent,
        )
        keys = KeyManager(self.profile, self.password)
        try:
            sql = SqlManager(
                self.profile.paths.get_db_file(),
                self.profile.config,
                keys.get_database_key(),
            )
            sql.execute(
                'UPDATE peers SET alias = ? WHERE onion = ?',
                ('legacy\nname', self._ONION),
            )
        finally:
            SqlManager.close_connection(self.profile.paths.get_db_file())
            keys.clear_sensitive_state()
        self.assertIsInstance(
            self.exchange(
                'rename_contact', old_alias='legacy\nname', new_alias='recovered'
            ),
            AliasRenamedEvent,
        )


if __name__ == '__main__':
    unittest.main()
