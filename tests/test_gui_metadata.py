"""Protected GUI metadata migration, authorization, and wire regression contracts."""

from dataclasses import replace
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from metor.core.api import (
    ClientUnlockMethod,
    ContentType,
    Delivery,
    GetGuiPreferencesCommand,
    GuiPreferenceFailure,
    GuiPreferences,
    GuiPreferencesEvent,
    GuiPreferencesRejectedEvent,
    IpcCommand,
    IpcEvent,
    SetGuiPreferencesCommand,
)
from metor.core.daemon.managed.handlers import ProfileMetadataCommandHandler
from metor.data.sql import SqlManager
from metor.data.message import MessageDirection, MessageStatus
from metor.data.sql.backends import sqlite3
from metor.shared import Constants
from metor.versioning import DB_SCHEMA_VERSION


class GuiMetadataTests(unittest.TestCase):
    """Uses real SQLCipher with isolated profiles and no transport or host audio."""

    def setUp(self) -> None:
        """Creates protected disposable metadata storage."""
        self.root = TemporaryDirectory()
        self.path = Path(self.root.name) / 'profile.db'
        self.key = bytes(range(32))
        self.config = Mock()
        self.config.get_bool.return_value = False
        self.sql = SqlManager(self.path, self.config, self.key)
        self.connection = Mock(spec=socket.socket)
        self.full_auth = Mock(return_value=True)
        self.pin_available = Mock(return_value=False)
        self.notify = Mock()
        self.handler = ProfileMetadataCommandHandler(
            lambda: self.sql.metadata, self.full_auth, self.notify, self.pin_available
        )

    def tearDown(self) -> None:
        """Closes every isolated resource and deletes encrypted test data."""
        self.connection.close()
        SqlManager.close_connection(self.path)
        self.root.cleanup()

    def test_defaults_and_round_trip_are_strict_and_protected(self) -> None:
        """Writes only protected canonical data and rejects unknown nested fields."""
        initial = self.handler.handle(GetGuiPreferencesCommand(), self.connection)
        self.assertIsInstance(initial, GuiPreferencesEvent)
        self.assertEqual(initial.preferences, GuiPreferences())
        self.assertEqual(initial.preferences_revision, 0)
        self.assertEqual(len(initial.profile_instance_id), 32)
        updated = replace(initial.preferences, auto_play=True, keyboard_layout='qwertz')
        command = SetGuiPreferencesCommand(0, updated)
        wire = IpcCommand.from_dict(json.loads(command.to_json()))
        self.assertEqual(wire, command)
        result = self.handler.handle(wire, self.connection)
        self.assertIsInstance(result, GuiPreferencesEvent)
        self.assertEqual(result.preferences, updated)
        self.assertEqual(result.preferences_revision, 1)
        self.assertEqual(IpcEvent.from_dict(json.loads(result.to_json())), result)
        self.assertNotIn(b'qwertz', self.path.read_bytes())
        self.assertNotIn(b'ui.gui', self.path.read_bytes())
        self.assertEqual(self.notify.call_args.args[0].scope, 'ui.gui')
        payload = json.loads(command.to_json())
        payload['preferences']['cached_alias'] = 'forbidden'
        with self.assertRaises(TypeError):
            IpcCommand.from_dict(payload)

    def test_stale_writer_cannot_overwrite_or_notify(self) -> None:
        """Compare-and-swap protects settings changed by another authenticated client."""
        first = SetGuiPreferencesCommand(0, GuiPreferences(auto_play=True))
        result = self.handler.handle(first, self.connection)
        self.assertIsInstance(result, GuiPreferencesEvent)
        stale = self.handler.handle(SetGuiPreferencesCommand(), self.connection)
        self.assertEqual(stale.reason, GuiPreferenceFailure.CONFLICT)
        current = self.handler.handle(GetGuiPreferencesCommand(), self.connection)
        self.assertTrue(current.preferences.auto_play)
        self.assertEqual(current.preferences_revision, 1)
        self.assertEqual(self.notify.call_count, 1)

    def test_pin_session_cannot_weaken_method_but_can_change_presentation(self) -> None:
        """Root security policy requires full authorization, ordinary GUI options do not."""
        self.full_auth.return_value = False
        denied = self.handler.handle(
            SetGuiPreferencesCommand(
                0,
                GuiPreferences(
                    unlock_method=ClientUnlockMethod.NONE, setup_complete=True
                ),
            ),
            self.connection,
        )
        self.assertEqual(denied.reason, GuiPreferenceFailure.FULL_AUTH_REQUIRED)
        self.assertEqual(self.sql.metadata.read_gui(), (0, None))
        allowed = self.handler.handle(
            SetGuiPreferencesCommand(0, GuiPreferences(auto_play=True)), self.connection
        )
        self.assertIsInstance(allowed, GuiPreferencesEvent)
        self.full_auth.return_value = True
        missing = self.handler.handle(
            SetGuiPreferencesCommand(
                1, GuiPreferences(unlock_method=ClientUnlockMethod.PIN)
            ),
            self.connection,
        )
        self.assertEqual(missing.reason, GuiPreferenceFailure.PIN_UNAVAILABLE)
        self.pin_available.return_value = True
        accepted = self.handler.handle(
            SetGuiPreferencesCommand(
                1, GuiPreferences(unlock_method=ClientUnlockMethod.PIN)
            ),
            self.connection,
        )
        self.assertIsInstance(accepted, GuiPreferencesEvent)

    def test_plaintext_profile_never_persists_gui_peer_metadata(self) -> None:
        """No plaintext namespace is created when profile protection is unavailable."""
        plain_path = Path(self.root.name) / 'plain.db'
        try:
            plain = SqlManager(plain_path, self.config)
            handler = ProfileMetadataCommandHandler(
                lambda: plain.metadata, self.full_auth, self.notify, self.pin_available
            )
            result = handler.handle(SetGuiPreferencesCommand(), self.connection)
            self.assertIsInstance(result, GuiPreferencesRejectedEvent)
            self.assertEqual(
                result.reason, GuiPreferenceFailure.PROTECTED_STORAGE_UNAVAILABLE
            )
            self.assertEqual(
                plain.fetchall(
                    'SELECT name FROM profile_metadata WHERE name = ?', ('ui.gui',)
                ),
                [],
            )
        finally:
            SqlManager.close_connection(plain_path)

    def test_bounds_are_checked_before_storage_mutation(self) -> None:
        """Malformed identities, policy types and over-budget values never persist."""
        for kwargs in (
            {'idle_seconds': True},
            {'auto_play': 1},
            {'pins': ['invalid']},
            {'pins': ['x'] * 129},
            {'keyboard_layout': 'unknown'},
        ):
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaises((ValueError, TypeError)),
            ):
                GuiPreferences(**kwargs)
        with self.assertRaises(ValueError):
            self.sql.metadata.write_gui(0, 'x' * (Constants.GUI_METADATA_MAX_BYTES + 1))
        self.assertEqual(self.sql.metadata.read_gui(), (0, None))

    def test_identity_survives_move_and_clear_but_not_name_reuse(self) -> None:
        """Stable identity follows database ownership rather than a mutable path."""
        identity = self.sql.metadata.instance_id
        self.sql.metadata.write_gui(0, '{}')
        self.sql.clear_all_profile_data()
        self.assertEqual(self.sql.metadata.instance_id, identity)
        self.assertEqual(self.sql.metadata.read_gui(), (0, None))
        SqlManager.close_connection(self.path)
        renamed = self.path.with_name('renamed.db')
        self.path.rename(renamed)
        try:
            moved = SqlManager(renamed, self.config, self.key)
            self.assertEqual(moved.metadata.instance_id, identity)
            reused = SqlManager(self.path, self.config, self.key)
            self.assertNotEqual(reused.metadata.instance_id, identity)
        finally:
            SqlManager.close_connection(renamed)

    def test_pin_cleanup_tracks_peer_and_conversation_lifetime(self) -> None:
        """Clear unpins even pending DROP; demotion alone preserves peer identity."""
        first, second = 'a' * 56, 'b' * 56
        self.sql.peers.insert(first, 'first', True)
        self.sql.peers.insert(second, 'second', True)
        self.sql.messages.queue_message(
            first,
            MessageDirection.OUT,
            Delivery.DROP,
            ContentType.TEXT,
            'pending',
            MessageStatus.PENDING,
            'pending-test',
        )
        self.sql.metadata.write_gui(0, json.dumps({'pins': [first, second]}))
        self.sql.peers.update_alias_and_saved(first, 'renamed', False)
        self.assertEqual(
            json.loads(self.sql.metadata.read_gui()[1])['pins'], [first, second]
        )
        self.sql.messages.clear_messages(first)
        revision, value = self.sql.metadata.read_gui()
        self.assertEqual(revision, 2)
        self.assertEqual(json.loads(value)['pins'], [second])
        self.assertIn(
            first,
            {
                peer
                for peer, _unread, _pending in self.sql.messages.get_drop_conversation_summaries()
            },
        )
        self.sql.peers.delete_by_alias('second')
        revision, value = self.sql.metadata.read_gui()
        self.assertEqual(revision, 3)
        self.assertEqual(json.loads(value)['pins'], [])
        self.assertIsNone(self.sql.metadata.write_gui(1, '{}'))

    def test_schema_three_migrates_and_export_does_not_falsely_stamp_four(self) -> None:
        """A pre-metadata database retains data and receives exactly one new identity."""
        SqlManager.close_connection(self.path)
        source = sqlite3.connect(str(self.path))
        source.execute(f'PRAGMA key = "x\'{self.key.hex()}\'"')
        source.execute('DROP TABLE profile_metadata')
        source.execute('DROP TABLE voice_producer_items')
        source.execute('CREATE TABLE retained_fixture (value TEXT)')
        source.execute('INSERT INTO retained_fixture VALUES (?)', ('retained',))
        source.execute('PRAGMA user_version = 3')
        source.commit()
        source.close()
        copy = self.path.with_name('copy.db')
        SqlManager.export_database_copy(self.path, copy, self.key, self.key)
        exported = sqlite3.connect(str(copy))
        exported.execute(f'PRAGMA key = "x\'{self.key.hex()}\'"')
        self.assertEqual(exported.execute('PRAGMA user_version').fetchone(), (3,))
        exported.close()
        try:
            migrated = SqlManager(copy, self.config, self.key)
            self.assertEqual(migrated.producers.items(), ())
            self.assertTrue(migrated.producers.protected)
            identity = migrated.metadata.instance_id
            self.assertEqual(
                migrated.fetchall('PRAGMA user_version'), [(DB_SCHEMA_VERSION,)]
            )
            self.assertEqual(
                migrated.fetchall('SELECT value FROM retained_fixture'), [('retained',)]
            )
            SqlManager.close_connection(copy)
            reopened = SqlManager(copy, self.config, self.key)
            self.assertEqual(reopened.metadata.instance_id, identity)
        finally:
            SqlManager.close_connection(copy)


if __name__ == '__main__':
    unittest.main()
