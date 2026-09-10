"""Security contracts for PMK-based profiles and encrypted external blobs."""

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.daemon.managed.engine import Daemon
from metor.core.api import CMD_MAP, ChangePasswordCommand, CommandType
from metor.core.key import KeyManager
from metor.core.profile_destruction import destroy_profile_storage
from metor.core.profile_keys import (
    BLOB_KEY_CONTEXT,
    DB_KEY_CONTEXT,
    KEYSLOT_FORMAT,
    KEYSLOT_VERSION,
    MIN_PASSWORD_KDF_MEMLIMIT,
    MIN_PASSWORD_KDF_OPSLIMIT,
    PROFILE_MASTER_KEY_BYTES,
    SECRET_KEY_CONTEXT,
    InvalidCredentialError,
    InvalidKeyslotError,
    KeyProtector,
    PasswordKeyProtector,
    ProfileKeySet,
    ProtectedKeyMissingError,
)
from metor.data.blob import (
    BLOB_FORMAT_MAGIC,
    BlobAuthenticationError,
    BlobFormatError,
    BlobLifecycle,
    EncryptedBlobStore,
    InvalidBlobIdError,
    PlaintextBlobStore,
)
from metor.data.profile import ProfileConfigKey, ProfileManager, ProfileSecurityMode
from metor.data.profile import lifecycle as profile_lifecycle
from metor.data.sql import DatabaseCorruptedError, SqlManager
from metor.data import Settings
from metor.utils import Constants


class ProfileStorageSecurityTests(unittest.TestCase):
    """Covers profile root keys, SQLCipher integration, and blob encryption."""

    def _profile(self, root: Path, name: str = 'primary') -> ProfileManager:
        """Creates one default encrypted profile under an isolated data root.

        Args:
            root (Path): Isolated profile parent.
            name (str): Profile name.

        Returns:
            ProfileManager: Initialized encrypted profile manager.
        """
        Constants.DATA = root
        pm = ProfileManager(name)
        pm.initialize()
        return pm

    def _keyslot(self, root: Path, password: str, pmk: bytes) -> PasswordKeyProtector:
        """Creates one isolated password keyslot.

        Args:
            root (Path): Keyslot directory.
            password (str): Protection password.
            pmk (bytes): Profile master key.

        Returns:
            PasswordKeyProtector: Initialized protector.
        """
        protector = PasswordKeyProtector(root / 'keyslot.json')
        protector.protect(pmk, password)
        return protector

    def test_profile_key_hierarchy_is_stable_and_domain_separated(self) -> None:
        """Verifies explicit versioned labels produce independent deterministic keys.

        Args:
            None

        Returns:
            None
        """
        self.assertEqual(DB_KEY_CONTEXT, b'metor/db/v1')
        self.assertEqual(SECRET_KEY_CONTEXT, b'metor/secrets/v1')
        self.assertEqual(BLOB_KEY_CONTEXT, b'metor/blobs/v1')
        pmk = bytes(range(PROFILE_MASTER_KEY_BYTES))
        first = ProfileKeySet.derive(pmk)
        second = ProfileKeySet.derive(pmk)
        try:
            keys = {
                first.database_key(),
                first.secret_key(),
                first.blob_key(),
            }
            self.assertEqual(len(keys), 3)
            self.assertEqual(first.database_key(), second.database_key())
            self.assertEqual(first.secret_key(), second.secret_key())
            self.assertEqual(first.blob_key(), second.blob_key())
            self.assertNotIn(pmk.hex(), repr(first))
        finally:
            first.clear()
            second.clear()

    def test_same_password_protects_independent_random_pmks(self) -> None:
        """Verifies profiles and keyslot salts remain independent.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_pmk = bytes(range(PROFILE_MASTER_KEY_BYTES))
            second_pmk = bytes(reversed(range(PROFILE_MASTER_KEY_BYTES)))
            first = self._keyslot(root / 'first', 'same-password', first_pmk)
            second = self._keyslot(root / 'second', 'same-password', second_pmk)
            first_doc = json.loads((root / 'first' / 'keyslot.json').read_text())
            second_doc = json.loads((root / 'second' / 'keyslot.json').read_text())
            self.assertNotEqual(first_doc['kdf']['salt'], second_doc['kdf']['salt'])
            self.assertEqual(bytes(first.unprotect('same-password')), first_pmk)
            self.assertEqual(bytes(second.unprotect('same-password')), second_pmk)

    def test_encrypted_profile_creation_generates_one_random_pmk(self) -> None:
        """Verifies independent profiles generate distinct 32-byte PMKs.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                first_pm = self._profile(root, 'first')
                second_pm = self._profile(root, 'second')
                first_manager = KeyManager(first_pm, 'same-password')
                second_manager = KeyManager(second_pm, 'same-password')
                first_manager.unlock_profile_keys()
                second_manager.unlock_profile_keys()
                first_pmk = PasswordKeyProtector(
                    first_pm.paths.get_keyslot_file()
                ).unprotect('same-password')
                second_pmk = PasswordKeyProtector(
                    second_pm.paths.get_keyslot_file()
                ).unprotect('same-password')
                try:
                    self.assertEqual(len(first_pmk), PROFILE_MASTER_KEY_BYTES)
                    self.assertEqual(len(second_pmk), PROFILE_MASTER_KEY_BYTES)
                    self.assertNotEqual(first_pmk, second_pmk)
                finally:
                    first_manager.clear_sensitive_state()
                    second_manager.clear_sensitive_state()
                    first_pmk[:] = b'\x00' * len(first_pmk)
                    second_pmk[:] = b'\x00' * len(second_pmk)
        finally:
            Constants.DATA = original_data

    def test_keyslot_contains_only_versioned_protected_material(self) -> None:
        """Verifies passwords, KEKs, and plaintext PMKs are never persisted.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            pmk = b'p' * PROFILE_MASTER_KEY_BYTES
            password = 'unique-password-value'
            path = Path(temp_dir) / 'keyslot.json'
            self._keyslot(Path(temp_dir), password, pmk)
            raw = path.read_bytes()
            document = json.loads(raw)
            self.assertEqual(document['format'], KEYSLOT_FORMAT)
            self.assertEqual(document['version'], KEYSLOT_VERSION)
            self.assertEqual(document['kdf']['algorithm'], 'argon2id')
            self.assertNotIn(password.encode(), raw)
            self.assertNotIn(pmk, raw)
            self.assertNotIn('kek', document)

    def test_profile_creation_is_complete_or_removed(self) -> None:
        """Verifies encrypted creation persists keyslot, keys, and SQLCipher atomically.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                Constants.DATA = root
                created = ProfileManager.add_profile_folder(
                    'created', master_password='profile-password'
                )
                self.assertTrue(created.success)
                pm = ProfileManager('created')
                self.assertTrue(pm.paths.get_keyslot_file().exists())
                self.assertTrue(pm.paths.get_db_file().exists())
                if os.name != 'nt':
                    self.assertEqual(
                        pm.paths.get_keyslot_file().stat().st_mode & 0o777,
                        0o600,
                    )
                    self.assertEqual(
                        pm.paths.get_protected_key_dir().stat().st_mode & 0o777,
                        0o700,
                    )
                self.assertTrue(
                    KeyManager(pm, 'profile-password').has_complete_key_material()
                )

                rejected = ProfileManager.add_profile_folder('incomplete')
                self.assertFalse(rejected.success)
                self.assertFalse((root / 'incomplete').exists())
        finally:
            Constants.DATA = original_data

    def test_wrong_password_tamper_and_unsupported_format_fail(self) -> None:
        """Verifies keyslot authentication and strict format handling.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            protector = self._keyslot(root, 'correct', b'k' * PROFILE_MASTER_KEY_BYTES)
            with self.assertRaises(InvalidCredentialError):
                protector.unprotect('incorrect')

            path = root / 'keyslot.json'
            document = json.loads(path.read_text())
            document['version'] = KEYSLOT_VERSION + 1
            path.write_text(json.dumps(document))
            with self.assertRaises(InvalidKeyslotError):
                protector.unprotect('correct')

            document['version'] = KEYSLOT_VERSION
            ciphertext = document['wrap']['ciphertext']
            document['wrap']['ciphertext'] = (
                'A' if ciphertext[0] != 'A' else 'B'
            ) + ciphertext[1:]
            path.write_text(json.dumps(document))
            with self.assertRaises((InvalidCredentialError, InvalidKeyslotError)):
                protector.unprotect('correct')

    def test_password_rewrap_keeps_pmk_and_derived_keys(self) -> None:
        """Verifies password changes replace only PMK wrapping metadata.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            pmk = b'r' * PROFILE_MASTER_KEY_BYTES
            protector = self._keyslot(Path(temp_dir), 'old', pmk)
            before = ProfileKeySet.derive(pmk)
            with self.assertRaises(InvalidCredentialError):
                protector.rewrap('wrong', 'new')
            self.assertEqual(bytes(protector.unprotect('old')), pmk)
            protector.rewrap('old', 'new')
            with self.assertRaises(InvalidCredentialError):
                protector.unprotect('old')
            recovered = protector.unprotect('new')
            after = ProfileKeySet.derive(recovered)
            try:
                self.assertEqual(bytes(recovered), pmk)
                self.assertEqual(before.database_key(), after.database_key())
                self.assertEqual(before.blob_key(), after.blob_key())
            finally:
                before.clear()
                after.clear()

    def test_password_rewrap_validation_failure_preserves_old_keyslot(self) -> None:
        """Verifies a staged keyslot must read back before replacing the active one.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            pmk = b'v' * PROFILE_MASTER_KEY_BYTES
            protector = self._keyslot(Path(temp_dir), 'old', pmk)
            with (
                patch.object(protector, '_build_document', return_value=b'{}'),
                self.assertRaises(InvalidKeyslotError),
            ):
                protector.rewrap('old', 'new')
            self.assertEqual(bytes(protector.unprotect('old')), pmk)
            with self.assertRaises(InvalidCredentialError):
                protector.unprotect('new')

    def test_keyslot_uses_persisted_bounded_kdf_parameters(self) -> None:
        """Verifies existing keyslots remain readable when recommended limits change.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            protector = PasswordKeyProtector(Path(temp_dir) / 'keyslot.json')
            with (
                patch(
                    'metor.core.profile_keys.PASSWORD_KDF_OPSLIMIT',
                    MIN_PASSWORD_KDF_OPSLIMIT,
                ),
                patch(
                    'metor.core.profile_keys.PASSWORD_KDF_MEMLIMIT',
                    MIN_PASSWORD_KDF_MEMLIMIT,
                ),
            ):
                protector.protect(b'p' * PROFILE_MASTER_KEY_BYTES, 'password')
            self.assertEqual(
                bytes(protector.unprotect('password')),
                b'p' * PROFILE_MASTER_KEY_BYTES,
            )
            document = json.loads((Path(temp_dir) / 'keyslot.json').read_text())
            document['kdf']['memlimit'] = -1
            (Path(temp_dir) / 'keyslot.json').write_text(json.dumps(document))
            with self.assertRaises(InvalidKeyslotError):
                protector.unprotect('password')

    def test_keyslot_destroy_overwrites_before_removal(self) -> None:
        """Verifies software key destruction delegates overwrite before unlinking.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'keyslot.json'
            protector = self._keyslot(Path(temp_dir), 'password', b'p' * 32)
            with patch('metor.core.profile_keys.secure_shred_file') as shred:
                protector.destroy()
            shred.assert_called_once_with(path)

    def test_key_manager_change_password_preserves_all_derived_keys(self) -> None:
        """Verifies central password change rewraps, rather than replaces, the PMK.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                self.assertTrue(
                    ProfileManager.add_profile_folder(
                        'password-change', master_password='old-password'
                    ).success
                )
                pm = ProfileManager('password-change')
                key_manager = KeyManager(pm, 'old-password')
                before = (
                    key_manager.get_database_key(),
                    key_manager.get_secret_key(),
                    key_manager.get_blob_key(),
                )
                key_manager.change_password('old-password', 'new-password')
                key_manager.clear_sensitive_state()
                with self.assertRaises(InvalidCredentialError):
                    KeyManager(pm, 'old-password').get_database_key()
                reopened = KeyManager(pm, 'new-password')
                self.assertEqual(
                    before,
                    (
                        reopened.get_database_key(),
                        reopened.get_secret_key(),
                        reopened.get_blob_key(),
                    ),
                )
                reopened.clear_sensitive_state()
        finally:
            Constants.DATA = original_data

    def test_offline_clear_profile_db_uses_mode_appropriate_database_access(
        self,
    ) -> None:
        """Verifies encrypted clears require DB_KEY credentials while plaintext clears do not.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                self.assertTrue(
                    ProfileManager.add_profile_folder(
                        'encrypted-clear', master_password='clear-password'
                    ).success
                )
                encrypted_pm = ProfileManager('encrypted-clear')
                encrypted_keys = KeyManager(encrypted_pm, 'clear-password')
                encrypted_sql = SqlManager(
                    encrypted_pm.paths.get_db_file(),
                    encrypted_pm.config,
                    encrypted_keys.get_database_key(),
                )
                encrypted_sql.execute(
                    'INSERT INTO peers VALUES (?, ?, ?, ?, ?)',
                    ('onion', 'alias', 'saved', 'created', 'updated'),
                )
                SqlManager.close_connection(encrypted_pm.paths.get_db_file())
                encrypted_keys.clear_sensitive_state()
                self.assertFalse(
                    ProfileManager.clear_profile_db('encrypted-clear', 'wrong').success
                )
                self.assertTrue(
                    ProfileManager.clear_profile_db(
                        'encrypted-clear', 'clear-password'
                    ).success
                )
                verified_keys = KeyManager(encrypted_pm, 'clear-password')
                verified_sql = SqlManager(
                    encrypted_pm.paths.get_db_file(),
                    encrypted_pm.config,
                    verified_keys.get_database_key(),
                )
                self.assertEqual(verified_sql.fetchall('SELECT * FROM peers'), [])
                SqlManager.close_connection(encrypted_pm.paths.get_db_file())
                verified_keys.clear_sensitive_state()

                plaintext_pm = self._profile(Constants.DATA, 'plaintext-clear')
                plaintext_pm.config.set(
                    ProfileConfigKey.SECURITY_MODE,
                    ProfileSecurityMode.PLAINTEXT.value,
                    allow_mutating_structural_keys=True,
                )
                plaintext_sql = SqlManager(
                    plaintext_pm.paths.get_db_file(), plaintext_pm.config
                )
                plaintext_sql.execute(
                    'INSERT INTO peers VALUES (?, ?, ?, ?, ?)',
                    ('plain-onion', 'plain-alias', 'saved', 'created', 'updated'),
                )
                SqlManager.close_connection(plaintext_pm.paths.get_db_file())
                self.assertTrue(
                    ProfileManager.clear_profile_db('plaintext-clear').success
                )
                verified_plain_sql = SqlManager(
                    plaintext_pm.paths.get_db_file(), plaintext_pm.config
                )
                self.assertEqual(verified_plain_sql.fetchall('SELECT * FROM peers'), [])
                SqlManager.close_connection(plaintext_pm.paths.get_db_file())
        finally:
            Constants.DATA = original_data

    def test_sqlcipher_uses_derived_key_across_lock_style_release(self) -> None:
        """Verifies profile data opens with DB_KEY rather than the user password.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                pm = self._profile(Path(temp_dir))
                first = KeyManager(pm, 'user-password')
                first.unlock_profile_keys()
                database_key = first.get_database_key()
                self.assertIsNotNone(database_key)
                self.assertNotEqual(database_key, b'user-password')
                sql = SqlManager(pm.paths.get_db_file(), pm.config, database_key)
                sql.execute('CREATE TABLE protected_test (value TEXT NOT NULL)')
                sql.execute('INSERT INTO protected_test VALUES (?)', ('survives',))
                SqlManager.close_connection(pm.paths.get_db_file())
                first.clear_sensitive_state()
                self.assertTrue(pm.paths.get_keyslot_file().exists())

                second = KeyManager(pm, 'user-password')
                reopened = SqlManager(
                    pm.paths.get_db_file(), pm.config, second.get_database_key()
                )
                self.assertEqual(
                    reopened.fetchall('SELECT value FROM protected_test'),
                    [('survives',)],
                )
                SqlManager.close_connection(pm.paths.get_db_file())
                second.clear_sensitive_state()

                wrong_keys = ProfileKeySet.derive(b'w' * PROFILE_MASTER_KEY_BYTES)
                with self.assertRaises(DatabaseCorruptedError):
                    SqlManager(
                        pm.paths.get_db_file(),
                        pm.config,
                        wrong_keys.database_key(),
                    )
                wrong_keys.clear()

                wrong = KeyManager(pm, 'wrong-password')
                with self.assertRaises(InvalidCredentialError):
                    wrong.get_database_key()
        finally:
            Constants.DATA = original_data

    def test_profile_password_rewrap_preserves_database_and_blobs(self) -> None:
        """Verifies internal rewrap changes no PMK-derived persistent encryption.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                result = ProfileManager.add_profile_folder(
                    'rewrap', master_password='old-password'
                )
                self.assertTrue(result.success)
                pm = ProfileManager('rewrap')
                old_manager = KeyManager(pm, 'old-password')
                database_key_before = old_manager.get_database_key()
                blob_key_before = old_manager.get_blob_key()
                self.assertIsNotNone(database_key_before)
                sql = SqlManager(pm.paths.get_db_file(), pm.config, database_key_before)
                sql.execute('CREATE TABLE rewrap_test (value TEXT NOT NULL)')
                sql.execute('INSERT INTO rewrap_test VALUES (?)', ('same-db',))
                SqlManager.close_connection(pm.paths.get_db_file())
                blob_store = EncryptedBlobStore(
                    pm.paths.get_persistent_blob_dir(),
                    pm.paths.get_temporary_blob_dir(),
                    blob_key_before,
                )
                blob_id = blob_store.put(b'same-blob')
                blob_store.close()

                old_manager.rewrap_password('new-password')
                old_manager.clear_sensitive_state()
                with self.assertRaises(InvalidCredentialError):
                    KeyManager(pm, 'old-password').get_database_key()

                new_manager = KeyManager(pm, 'new-password')
                self.assertEqual(new_manager.get_database_key(), database_key_before)
                self.assertEqual(new_manager.get_blob_key(), blob_key_before)
                reopened = SqlManager(
                    pm.paths.get_db_file(),
                    pm.config,
                    new_manager.get_database_key(),
                )
                self.assertEqual(
                    reopened.fetchall('SELECT value FROM rewrap_test'),
                    [('same-db',)],
                )
                SqlManager.close_connection(pm.paths.get_db_file())
                reopened_blobs = EncryptedBlobStore(
                    pm.paths.get_persistent_blob_dir(),
                    pm.paths.get_temporary_blob_dir(),
                    new_manager.get_blob_key(),
                )
                self.assertEqual(reopened_blobs.read(blob_id), b'same-blob')
                reopened_blobs.close()
                new_manager.clear_sensitive_state()
        finally:
            Constants.DATA = original_data

    def test_security_migration_stages_both_directions_before_activation(self) -> None:
        """Verifies both migration directions preserve data and alter mode only at commit.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                self.assertTrue(
                    ProfileManager.add_profile_folder(
                        'migrated', master_password='old-password'
                    ).success
                )
                pm = ProfileManager('migrated')
                key_manager = KeyManager(pm, 'old-password')
                sql = SqlManager(
                    pm.paths.get_db_file(),
                    pm.config,
                    key_manager.get_database_key(),
                )
                sql.execute('CREATE TABLE migration_test (value TEXT NOT NULL)')
                sql.execute('INSERT INTO migration_test VALUES (?)', ('retained',))
                SqlManager.close_connection(pm.paths.get_db_file())
                key_manager.clear_sensitive_state()

                with patch.object(Settings, 'get_bool', return_value=True):
                    plaintext_result = ProfileManager.migrate_profile_security(
                        'migrated',
                        ProfileSecurityMode.PLAINTEXT,
                        current_password='old-password',
                    )
                self.assertTrue(plaintext_result.success)
                plain_pm = ProfileManager('migrated')
                self.assertTrue(plain_pm.uses_plaintext_storage())
                plain_sql = SqlManager(plain_pm.paths.get_db_file(), plain_pm.config)
                self.assertEqual(
                    plain_sql.fetchall('SELECT value FROM migration_test'),
                    [('retained',)],
                )
                SqlManager.close_connection(plain_pm.paths.get_db_file())

                encrypted_result = ProfileManager.migrate_profile_security(
                    'migrated',
                    ProfileSecurityMode.ENCRYPTED,
                    new_password='new-password',
                )
                self.assertTrue(encrypted_result.success)
                encrypted_pm = ProfileManager('migrated')
                self.assertTrue(encrypted_pm.uses_encrypted_storage())
                reopened_key_manager = KeyManager(encrypted_pm, 'new-password')
                reopened_sql = SqlManager(
                    encrypted_pm.paths.get_db_file(),
                    encrypted_pm.config,
                    reopened_key_manager.get_database_key(),
                )
                self.assertEqual(
                    reopened_sql.fetchall('SELECT value FROM migration_test'),
                    [('retained',)],
                )
                SqlManager.close_connection(encrypted_pm.paths.get_db_file())
                reopened_key_manager.clear_sensitive_state()
        finally:
            Constants.DATA = original_data

    def test_blob_security_migration_round_trip_preserves_ids_and_payloads(
        self,
    ) -> None:
        """Verifies blobs and structured data survive both security-mode transforms.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                self.assertTrue(
                    ProfileManager.add_profile_folder(
                        'blob-round-trip', master_password='source-password'
                    ).success
                )
                source_pm = ProfileManager('blob-round-trip')
                source_keys = KeyManager(source_pm, 'source-password')
                sql = SqlManager(
                    source_pm.paths.get_db_file(),
                    source_pm.config,
                    source_keys.get_database_key(),
                )
                sql.execute('CREATE TABLE blob_owner (blob_id TEXT PRIMARY KEY)')
                source_store = EncryptedBlobStore(
                    source_pm.paths.get_persistent_blob_dir(),
                    source_pm.paths.get_temporary_blob_dir(),
                    source_keys.get_blob_key(),
                )
                payloads = (b'first persistent payload', b'\x00second payload\xff')
                blob_ids = [source_store.put(payload) for payload in payloads]
                for blob_id in blob_ids:
                    sql.execute('INSERT INTO blob_owner VALUES (?)', (blob_id,))
                temporary_id = source_store.put(
                    b'non-durable spool', BlobLifecycle.TEMPORARY
                )
                source_store.close()
                SqlManager.close_connection(source_pm.paths.get_db_file())
                source_keys.clear_sensitive_state()

                with patch.object(Settings, 'get_bool', return_value=True):
                    result = ProfileManager.migrate_profile_security(
                        'blob-round-trip',
                        ProfileSecurityMode.PLAINTEXT,
                        current_password='source-password',
                    )
                self.assertTrue(result.success, result.params)
                plain_pm = ProfileManager('blob-round-trip')
                self.assertFalse(plain_pm.paths.get_keyslot_file().exists())
                plain_store = PlaintextBlobStore(
                    plain_pm.paths.get_persistent_blob_dir(),
                    plain_pm.paths.get_temporary_blob_dir(),
                )
                for blob_id, payload in zip(blob_ids, payloads, strict=True):
                    self.assertEqual(plain_store.read(blob_id), payload)
                    self.assertEqual(
                        (
                            plain_pm.paths.get_persistent_blob_dir() / f'{blob_id}.blob'
                        ).read_bytes(),
                        payload,
                    )
                self.assertFalse(
                    (
                        plain_pm.paths.get_temporary_blob_dir() / f'{temporary_id}.blob'
                    ).exists()
                )
                plain_store.close()

                result = ProfileManager.migrate_profile_security(
                    'blob-round-trip',
                    ProfileSecurityMode.ENCRYPTED,
                    new_password='target-password',
                )
                self.assertTrue(result.success, result.params)
                target_pm = ProfileManager('blob-round-trip')
                target_keys = KeyManager(target_pm, 'target-password')
                target_store = EncryptedBlobStore(
                    target_pm.paths.get_persistent_blob_dir(),
                    target_pm.paths.get_temporary_blob_dir(),
                    target_keys.get_blob_key(),
                )
                for blob_id, payload in zip(blob_ids, payloads, strict=True):
                    self.assertEqual(target_store.read(blob_id), payload)
                    encoded = (
                        target_pm.paths.get_persistent_blob_dir() / f'{blob_id}.blob'
                    ).read_bytes()
                    self.assertTrue(encoded.startswith(BLOB_FORMAT_MAGIC))
                    self.assertNotEqual(encoded, payload)
                wrong_keys = ProfileKeySet.derive(b'z' * PROFILE_MASTER_KEY_BYTES)
                wrong_store = EncryptedBlobStore(
                    target_pm.paths.get_persistent_blob_dir(),
                    target_pm.paths.get_temporary_blob_dir(),
                    wrong_keys.blob_key(),
                )
                with self.assertRaises(BlobAuthenticationError):
                    wrong_store.read(blob_ids[0])
                migrated_path = (
                    target_pm.paths.get_persistent_blob_dir() / f'{blob_ids[0]}.blob'
                )
                original_encoded = migrated_path.read_bytes()
                tampered_encoded = bytearray(original_encoded)
                tampered_encoded[-1] ^= 1
                migrated_path.write_bytes(tampered_encoded)
                with self.assertRaises(BlobAuthenticationError):
                    target_store.read(blob_ids[0])
                migrated_path.write_bytes(original_encoded)
                wrong_store.close()
                wrong_keys.clear()
                reopened = SqlManager(
                    target_pm.paths.get_db_file(),
                    target_pm.config,
                    target_keys.get_database_key(),
                )
                self.assertEqual(
                    reopened.fetchall('SELECT blob_id FROM blob_owner ORDER BY rowid'),
                    [(blob_id,) for blob_id in blob_ids],
                )
                SqlManager.close_connection(target_pm.paths.get_db_file())
                target_store.close()
                target_keys.clear_sensitive_state()
        finally:
            Constants.DATA = original_data

    def test_blob_migration_precommit_failures_preserve_readable_sources(self) -> None:
        """Verifies blob-stage failures cannot damage either active source mode.

        Args:
            None

        Returns:
            None
        """
        stages = (
            'before_blob_read:0',
            'before_blob_read:1',
            'before_blob_write:0',
            'after_blob_write:0',
            'after_all_blob_writes',
            'during_blob_validation:0',
            'immediately_before_commit',
        )
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                for source_mode in (
                    ProfileSecurityMode.ENCRYPTED,
                    ProfileSecurityMode.PLAINTEXT,
                ):
                    for index, stage in enumerate(stages):
                        with self.subTest(source_mode=source_mode, stage=stage):
                            name = f'blob-failure-{source_mode.value}-{index}'
                            if source_mode is ProfileSecurityMode.ENCRYPTED:
                                self.assertTrue(
                                    ProfileManager.add_profile_folder(
                                        name, master_password='source-password'
                                    ).success
                                )
                                source_pm = ProfileManager(name)
                                source_keys = KeyManager(source_pm, 'source-password')
                                source_store = EncryptedBlobStore(
                                    source_pm.paths.get_persistent_blob_dir(),
                                    source_pm.paths.get_temporary_blob_dir(),
                                    source_keys.get_blob_key(),
                                )
                            else:
                                source_pm = self._profile(Constants.DATA, name)
                                source_pm.config.set(
                                    ProfileConfigKey.SECURITY_MODE,
                                    source_mode.value,
                                    allow_mutating_structural_keys=True,
                                )
                                source_keys = None
                                source_store = PlaintextBlobStore(
                                    source_pm.paths.get_persistent_blob_dir(),
                                    source_pm.paths.get_temporary_blob_dir(),
                                )
                            blob_ids = [
                                source_store.put(b'first'),
                                source_store.put(b'second'),
                            ]
                            source_store.close()
                            if source_keys is not None:
                                source_keys.clear_sensitive_state()
                            with (
                                patch.object(Settings, 'get_bool', return_value=True),
                                patch.object(
                                    profile_lifecycle,
                                    '_migration_checkpoint',
                                    side_effect=lambda checkpoint, expected=stage: (
                                        (_ for _ in ()).throw(OSError(expected))
                                        if checkpoint == expected
                                        else None
                                    ),
                                ),
                            ):
                                result = ProfileManager.migrate_profile_security(
                                    name,
                                    (
                                        ProfileSecurityMode.PLAINTEXT
                                        if source_mode is ProfileSecurityMode.ENCRYPTED
                                        else ProfileSecurityMode.ENCRYPTED
                                    ),
                                    current_password=(
                                        'source-password'
                                        if source_mode is ProfileSecurityMode.ENCRYPTED
                                        else None
                                    ),
                                    new_password=(
                                        'target-password'
                                        if source_mode is ProfileSecurityMode.PLAINTEXT
                                        else None
                                    ),
                                )
                            self.assertFalse(result.success)
                            recovered_pm = ProfileManager(name)
                            self.assertIs(recovered_pm.get_security_mode(), source_mode)
                            if source_mode is ProfileSecurityMode.ENCRYPTED:
                                recovered_keys = KeyManager(
                                    recovered_pm, 'source-password'
                                )
                                recovered_database_key = (
                                    recovered_keys.get_database_key()
                                )
                                recovered_store = EncryptedBlobStore(
                                    recovered_pm.paths.get_persistent_blob_dir(),
                                    recovered_pm.paths.get_temporary_blob_dir(),
                                    recovered_keys.get_blob_key(),
                                )
                            else:
                                recovered_keys = None
                                recovered_database_key = None
                                recovered_store = PlaintextBlobStore(
                                    recovered_pm.paths.get_persistent_blob_dir(),
                                    recovered_pm.paths.get_temporary_blob_dir(),
                                )
                            self.assertEqual(
                                recovered_store.read(blob_ids[0]), b'first'
                            )
                            self.assertEqual(
                                recovered_store.read(blob_ids[1]), b'second'
                            )
                            SqlManager(
                                recovered_pm.paths.get_db_file(),
                                recovered_pm.config,
                                recovered_database_key,
                            )
                            SqlManager.close_connection(
                                recovered_pm.paths.get_db_file()
                            )
                            recovered_store.close()
                            if recovered_keys is not None:
                                recovered_keys.clear_sensitive_state()
        finally:
            Constants.DATA = original_data

    def test_blob_migration_rejects_tampering_and_missing_database_references(
        self,
    ) -> None:
        """Verifies authentication and target-reference failures abort before commit.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                self.assertTrue(
                    ProfileManager.add_profile_folder(
                        'tampered-source', master_password='source-password'
                    ).success
                )
                encrypted_pm = ProfileManager('tampered-source')
                encrypted_keys = KeyManager(encrypted_pm, 'source-password')
                encrypted_store = EncryptedBlobStore(
                    encrypted_pm.paths.get_persistent_blob_dir(),
                    encrypted_pm.paths.get_temporary_blob_dir(),
                    encrypted_keys.get_blob_key(),
                )
                blob_id = encrypted_store.put(b'authenticated payload')
                blob_path = (
                    encrypted_pm.paths.get_persistent_blob_dir() / f'{blob_id}.blob'
                )
                tampered = bytearray(blob_path.read_bytes())
                tampered[-1] ^= 1
                blob_path.write_bytes(tampered)
                encrypted_store.close()
                encrypted_keys.clear_sensitive_state()
                with patch.object(Settings, 'get_bool', return_value=True):
                    result = ProfileManager.migrate_profile_security(
                        'tampered-source',
                        ProfileSecurityMode.PLAINTEXT,
                        current_password='source-password',
                    )
                self.assertFalse(result.success)
                tampered_staged_path = (
                    Constants.DATA / '.tampered-source.security-migration.staged'
                )
                tampered_staged_db = tampered_staged_path / Constants.DB_FILE
                self.assertNotIn(
                    str(tampered_staged_db.absolute()), SqlManager._connections
                )
                recovered_encrypted = ProfileManager('tampered-source')
                self.assertFalse(tampered_staged_path.exists())
                self.assertFalse(
                    (
                        Constants.DATA / '.tampered-source.security-migration.json'
                    ).exists()
                )
                self.assertTrue(recovered_encrypted.uses_encrypted_storage())
                KeyManager(recovered_encrypted, 'source-password').get_blob_key()
                self.assertEqual(blob_path.read_bytes(), bytes(tampered))

                plaintext_pm = self._profile(Constants.DATA, 'missing-reference')
                plaintext_pm.config.set(
                    ProfileConfigKey.SECURITY_MODE,
                    ProfileSecurityMode.PLAINTEXT.value,
                    allow_mutating_structural_keys=True,
                )
                plaintext_sql = SqlManager(
                    plaintext_pm.paths.get_db_file(), plaintext_pm.config
                )
                plaintext_sql.execute(
                    'CREATE TABLE blob_reference (blob_id TEXT NOT NULL)'
                )
                missing_id = 'a' * 64
                plaintext_sql.execute(
                    'INSERT INTO blob_reference VALUES (?)', (missing_id,)
                )
                SqlManager.close_connection(plaintext_pm.paths.get_db_file())
                plaintext_store = PlaintextBlobStore(
                    plaintext_pm.paths.get_persistent_blob_dir(),
                    plaintext_pm.paths.get_temporary_blob_dir(),
                )
                readable_blob_id = plaintext_store.put(b'readable source blob')
                plaintext_store.close()
                result = ProfileManager.migrate_profile_security(
                    'missing-reference',
                    ProfileSecurityMode.ENCRYPTED,
                    new_password='target-password',
                )
                self.assertFalse(result.success)
                staged_path = (
                    Constants.DATA / '.missing-reference.security-migration.staged'
                )
                staged_db_path = staged_path / Constants.DB_FILE
                self.assertNotIn(
                    str(staged_db_path.absolute()), SqlManager._connections
                )
                recovered_plaintext = ProfileManager('missing-reference')
                self.assertFalse(staged_path.exists())
                self.assertFalse(
                    (
                        Constants.DATA / '.missing-reference.security-migration.json'
                    ).exists()
                )
                self.assertTrue(recovered_plaintext.uses_plaintext_storage())
                recovered_store = PlaintextBlobStore(
                    recovered_plaintext.paths.get_persistent_blob_dir(),
                    recovered_plaintext.paths.get_temporary_blob_dir(),
                )
                self.assertEqual(
                    recovered_store.read(readable_blob_id), b'readable source blob'
                )
                recovered_store.close()
                recovered_sql = SqlManager(
                    recovered_plaintext.paths.get_db_file(),
                    recovered_plaintext.config,
                )
                self.assertEqual(
                    recovered_sql.fetchall('SELECT blob_id FROM blob_reference'),
                    [(missing_id,)],
                )
                SqlManager.close_connection(recovered_plaintext.paths.get_db_file())
        finally:
            Constants.DATA = original_data

    def test_precommit_migration_failure_preserves_encrypted_source(self) -> None:
        """Verifies a staged migration failure leaves the original password usable.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                self.assertTrue(
                    ProfileManager.add_profile_folder(
                        'failed', master_password='source-password'
                    ).success
                )
                with (
                    patch.object(Settings, 'get_bool', return_value=True),
                    patch.object(
                        profile_lifecycle,
                        '_fsync_tree',
                        side_effect=OSError('injected before commit'),
                    ),
                ):
                    result = ProfileManager.migrate_profile_security(
                        'failed',
                        ProfileSecurityMode.PLAINTEXT,
                        current_password='source-password',
                    )
                self.assertFalse(result.success)
                recovered_pm = ProfileManager('failed')
                self.assertTrue(recovered_pm.uses_encrypted_storage())
                KeyManager(recovered_pm, 'source-password').get_database_key()
                self.assertFalse(
                    (Constants.DATA / '.failed.security-migration.staged').exists()
                )
        finally:
            Constants.DATA = original_data

    def test_encrypted_to_plaintext_failure_injection_preserves_source_before_commit(
        self,
    ) -> None:
        """Verifies every encrypted-source pre-commit checkpoint preserves unlock.

        Args:
            None

        Returns:
            None
        """
        stages = (
            'before_target_db_creation',
            'during_secret_transformation',
            'during_db_copy',
            'after_target_db_creation',
            'before_validation',
            'during_validation',
            'immediately_before_commit',
        )
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                for index, stage in enumerate(stages):
                    with self.subTest(stage=stage):
                        name = f'encrypted-failure-{index}'
                        self.assertTrue(
                            ProfileManager.add_profile_folder(
                                name,
                                master_password='source-password',
                            ).success
                        )
                        with (
                            patch.object(Settings, 'get_bool', return_value=True),
                            patch.object(
                                profile_lifecycle,
                                '_migration_checkpoint',
                                side_effect=lambda checkpoint, expected=stage: (
                                    (_ for _ in ()).throw(OSError(expected))
                                    if checkpoint == expected
                                    else None
                                ),
                            ),
                        ):
                            result = ProfileManager.migrate_profile_security(
                                name,
                                ProfileSecurityMode.PLAINTEXT,
                                current_password='source-password',
                            )
                        self.assertFalse(result.success)
                        source_pm = ProfileManager(name)
                        self.assertTrue(source_pm.uses_encrypted_storage())
                        source_keys = KeyManager(source_pm, 'source-password')
                        self.assertIsNotNone(source_keys.get_database_key())
                        source_keys.clear_sensitive_state()
        finally:
            Constants.DATA = original_data

    def test_plaintext_to_encrypted_keyslot_failure_preserves_source(self) -> None:
        """Verifies encrypted-target keyslot failure leaves plaintext storage usable.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                source_pm = self._profile(Constants.DATA, 'plaintext-failure')
                source_pm.config.set(
                    ProfileConfigKey.SECURITY_MODE,
                    ProfileSecurityMode.PLAINTEXT.value,
                    allow_mutating_structural_keys=True,
                )
                with patch.object(
                    profile_lifecycle,
                    '_migration_checkpoint',
                    side_effect=lambda stage: (
                        (_ for _ in ()).throw(OSError(stage))
                        if stage == 'after_target_keyslot_creation'
                        else None
                    ),
                ):
                    result = ProfileManager.migrate_profile_security(
                        'plaintext-failure',
                        ProfileSecurityMode.ENCRYPTED,
                        new_password='target-password',
                    )
                self.assertFalse(result.success)
                recovered_pm = ProfileManager('plaintext-failure')
                self.assertTrue(recovered_pm.uses_plaintext_storage())
                SqlManager(recovered_pm.paths.get_db_file(), recovered_pm.config)
                SqlManager.close_connection(recovered_pm.paths.get_db_file())
        finally:
            Constants.DATA = original_data

    def test_postcommit_failure_recovers_committed_target_and_tolerates_cleanup_failure(
        self,
    ) -> None:
        """Verifies committed generations stay usable after interruption or cleanup loss.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                for name, stage in (
                    ('post-commit', 'immediately_after_commit'),
                    ('cleanup-failure', 'during_old_state_cleanup'),
                ):
                    with self.subTest(stage=stage):
                        self.assertTrue(
                            ProfileManager.add_profile_folder(
                                name,
                                master_password='source-password',
                            ).success
                        )
                        source_pm = ProfileManager(name)
                        source_keys = KeyManager(source_pm, 'source-password')
                        source_store = EncryptedBlobStore(
                            source_pm.paths.get_persistent_blob_dir(),
                            source_pm.paths.get_temporary_blob_dir(),
                            source_keys.get_blob_key(),
                        )
                        blob_id = source_store.put(b'committed blob')
                        source_store.close()
                        source_keys.clear_sensitive_state()
                        with (
                            patch.object(Settings, 'get_bool', return_value=True),
                            patch.object(
                                profile_lifecycle,
                                '_migration_checkpoint',
                                side_effect=lambda checkpoint, expected=stage: (
                                    (_ for _ in ()).throw(OSError(expected))
                                    if checkpoint == expected
                                    else None
                                ),
                            ),
                        ):
                            result = ProfileManager.migrate_profile_security(
                                name,
                                ProfileSecurityMode.PLAINTEXT,
                                current_password='source-password',
                            )
                        recovered_pm = ProfileManager(name)
                        self.assertTrue(recovered_pm.uses_plaintext_storage())
                        recovered_store = PlaintextBlobStore(
                            recovered_pm.paths.get_persistent_blob_dir(),
                            recovered_pm.paths.get_temporary_blob_dir(),
                        )
                        self.assertEqual(
                            recovered_store.read(blob_id), b'committed blob'
                        )
                        recovered_store.close()
                        self.assertTrue(
                            result.success or stage == 'immediately_after_commit'
                        )
        finally:
            Constants.DATA = original_data

    def test_plaintext_to_encrypted_postcommit_failure_recovers_target(self) -> None:
        """Verifies committed encrypted blobs retain their target keyslot on recovery.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                Constants.DATA = Path(temp_dir)
                source_pm = self._profile(Constants.DATA, 'encrypted-recovery')
                source_pm.config.set(
                    ProfileConfigKey.SECURITY_MODE,
                    ProfileSecurityMode.PLAINTEXT.value,
                    allow_mutating_structural_keys=True,
                )
                source_store = PlaintextBlobStore(
                    source_pm.paths.get_persistent_blob_dir(),
                    source_pm.paths.get_temporary_blob_dir(),
                )
                blob_id = source_store.put(b'encrypted after recovery')
                source_store.close()
                with patch.object(
                    profile_lifecycle,
                    '_migration_checkpoint',
                    side_effect=lambda stage: (
                        (_ for _ in ()).throw(OSError(stage))
                        if stage == 'immediately_after_commit'
                        else None
                    ),
                ):
                    result = ProfileManager.migrate_profile_security(
                        'encrypted-recovery',
                        ProfileSecurityMode.ENCRYPTED,
                        new_password='target-password',
                    )
                self.assertFalse(result.success)
                recovered_pm = ProfileManager('encrypted-recovery')
                self.assertTrue(recovered_pm.uses_encrypted_storage())
                recovered_keys = KeyManager(recovered_pm, 'target-password')
                recovered_store = EncryptedBlobStore(
                    recovered_pm.paths.get_persistent_blob_dir(),
                    recovered_pm.paths.get_temporary_blob_dir(),
                    recovered_keys.get_blob_key(),
                )
                self.assertEqual(
                    recovered_store.read(blob_id), b'encrypted after recovery'
                )
                recovered_store.close()
                recovered_keys.clear_sensitive_state()
        finally:
            Constants.DATA = original_data

    def test_change_password_command_is_registered_and_redacts_credentials(
        self,
    ) -> None:
        """Verifies the public password-change command has no credential-bearing repr.

        Args:
            None

        Returns:
            None
        """
        command = ChangePasswordCommand(
            current_password='current-secret',
            new_password='replacement-secret',
        )
        self.assertIs(CMD_MAP[CommandType.CHANGE_PASSWORD], ChangePasswordCommand)
        self.assertNotIn('current-secret', repr(command))
        self.assertNotIn('replacement-secret', repr(command))

    def _blob_store(self, root: Path, key: bytes) -> EncryptedBlobStore:
        """Creates one isolated encrypted blob store.

        Args:
            root (Path): Store root.
            key (bytes): Blob-domain key.

        Returns:
            EncryptedBlobStore: Active test store.
        """
        return EncryptedBlobStore(root / 'persistent', root / 'temporary', key)

    def test_blob_round_trip_tamper_wrong_key_and_deletion(self) -> None:
        """Verifies ciphertext confidentiality, authentication, and logical deletion.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plaintext = b'future voice payload with private content'
            right_keys = ProfileKeySet.derive(b'a' * PROFILE_MASTER_KEY_BYTES)
            wrong_keys = ProfileKeySet.derive(b'b' * PROFILE_MASTER_KEY_BYTES)
            store = self._blob_store(root, right_keys.blob_key())
            blob_id = store.put(plaintext)
            path = root / 'persistent' / f'{blob_id}.blob'
            encoded = path.read_bytes()
            self.assertTrue(encoded.startswith(BLOB_FORMAT_MAGIC))
            self.assertNotIn(plaintext, encoded)
            self.assertEqual(store.read(blob_id), plaintext)
            second_blob_id = store.put(plaintext)
            second_path = root / 'persistent' / f'{second_blob_id}.blob'
            self.assertNotEqual(blob_id, second_blob_id)
            self.assertNotEqual(encoded, second_path.read_bytes())
            self.assertTrue(store.exists(blob_id))

            wrong_store = self._blob_store(root, wrong_keys.blob_key())
            with self.assertRaises(BlobAuthenticationError):
                wrong_store.read(blob_id)

            tampered = bytearray(encoded)
            tampered[-1] ^= 1
            path.write_bytes(tampered)
            with self.assertRaises(BlobAuthenticationError):
                store.read(blob_id)
            path.write_bytes(encoded)

            store.delete(blob_id)
            self.assertFalse(path.exists())
            self.assertFalse(store.exists(blob_id))
            store.delete(blob_id)
            store.close()
            wrong_store.close()
            right_keys.clear()
            wrong_keys.clear()

    def test_blob_header_identity_and_paths_are_strict(self) -> None:
        """Verifies immutable context and identifiers cannot be redirected.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = self._blob_store(root, b'c' * 32)
            blob_id = store.put(b'content')
            original = root / 'persistent' / f'{blob_id}.blob'
            encoded = original.read_bytes()

            encoded_with_bad_header = bytearray(encoded)
            encoded_with_bad_header[0] ^= 1
            original.write_bytes(encoded_with_bad_header)
            with self.assertRaises(BlobFormatError):
                store.read(blob_id)
            original.write_bytes(encoded)

            encoded_with_bad_version = bytearray(encoded)
            encoded_with_bad_version[len(BLOB_FORMAT_MAGIC)] += 1
            original.write_bytes(encoded_with_bad_version)
            with self.assertRaises(BlobFormatError):
                store.read(blob_id)
            original.write_bytes(encoded)

            other_id = 'f' * 64 if blob_id != 'f' * 64 else 'e' * 64
            other_path = root / 'persistent' / f'{other_id}.blob'
            original.replace(other_path)
            with self.assertRaises(BlobAuthenticationError):
                store.read(other_id)
            with self.assertRaises(InvalidBlobIdError):
                store.read('../../keyslot')

    def test_temporary_blob_promotes_without_plaintext_spool(self) -> None:
        """Verifies LIVE-style ciphertext can move into DROP-style ownership.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = self._blob_store(root, b'd' * 32)
            blob_id = store.put(b'pending voice', BlobLifecycle.TEMPORARY)
            temporary = root / 'temporary' / f'{blob_id}.blob'
            persistent = root / 'persistent' / f'{blob_id}.blob'
            self.assertTrue(temporary.exists())
            self.assertNotIn(b'pending voice', temporary.read_bytes())
            store.promote(blob_id)
            self.assertFalse(temporary.exists())
            self.assertTrue(persistent.exists())
            self.assertEqual(store.read(blob_id), b'pending voice')
            self.assertEqual(list((root / 'temporary').glob('*.tmp')), [])

    def test_blob_corruption_and_closed_runtime_fail_cleanly(self) -> None:
        """Verifies truncated objects and released runtime keys cannot be used.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = self._blob_store(root, b'e' * 32)
            blob_id = store.put(b'value')
            path = root / 'persistent' / f'{blob_id}.blob'
            path.write_bytes(BLOB_FORMAT_MAGIC)
            with self.assertRaises(BlobFormatError):
                store.read(blob_id)
            store.close()
            with self.assertRaises(RuntimeError):
                store.put(b'new')

    def test_blob_store_enforces_injected_size_limit(self) -> None:
        """Verifies object limits reject oversized plaintext before persistence.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = EncryptedBlobStore(
                root / 'persistent',
                root / 'temporary',
                b's' * 32,
                max_blob_bytes=4,
            )
            with self.assertRaises(ValueError):
                store.put(b'oversized')
            self.assertEqual(list((root / 'persistent').iterdir()), [])

    def test_key_destruction_precedes_filesystem_cleanup(self) -> None:
        """Verifies purge ordering keeps cleanup secondary to cryptographic erasure.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                pm = self._profile(Path(temp_dir))
                order: list[str] = []
                protector = Mock()
                protector.destroy.side_effect = lambda: order.append('key')

                with patch.object(
                    SqlManager,
                    'close_connection',
                    side_effect=lambda _path: order.append('db'),
                ):
                    destroy_profile_storage(
                        pm,
                        prepare_runtime=lambda: order.append('runtime'),
                        clear_runtime_keys=lambda: order.append('memory'),
                        protector=cast(KeyProtector, protector),
                        cleanup=lambda _path: order.append('filesystem'),
                    )
                self.assertEqual(
                    order, ['runtime', 'db', 'memory', 'key', 'filesystem']
                )
        finally:
            Constants.DATA = original_data

    def test_cleanup_failure_does_not_restore_destroyed_keyslot(self) -> None:
        """Verifies a post-erasure cleanup failure cannot recreate PMK access.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                pm = self._profile(Path(temp_dir))
                protector = PasswordKeyProtector(pm.paths.get_keyslot_file())
                protector.protect(b'z' * PROFILE_MASTER_KEY_BYTES, 'password')

                def fail_cleanup(_path: Path) -> None:
                    """Raises after logical key destruction.

                    Args:
                        _path (Path): Ignored profile path.

                    Returns:
                        None
                    """
                    raise OSError('simulated cleanup failure')

                with self.assertRaises(OSError):
                    destroy_profile_storage(
                        pm, protector=protector, cleanup=fail_cleanup
                    )
                self.assertFalse(pm.paths.get_keyslot_file().exists())
                with self.assertRaises(ProtectedKeyMissingError):
                    protector.unprotect('password')
        finally:
            Constants.DATA = original_data

    def test_self_destruct_uses_central_profile_destruction(self) -> None:
        """Verifies SelfDestruct delegates to the key-first purge path.

        Args:
            None

        Returns:
            None
        """
        daemon = Daemon.__new__(Daemon)
        daemon._pm = Mock()
        daemon._lock_runtime = Mock(return_value=True)
        daemon.stop = Mock()
        daemon._on_runtime_internal_error = Mock()
        with patch(
            'metor.core.daemon.managed.engine.destroy_profile_storage'
        ) as destroy:
            daemon._nuke_data()
        destroy.assert_called_once_with(
            daemon._pm,
            prepare_runtime=daemon._lock_runtime,
        )
        daemon.stop.assert_called_once_with()

    def test_profile_destruction_is_idempotent_when_files_are_missing(self) -> None:
        """Verifies repeated logical destruction safely tolerates absent storage.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                pm = self._profile(Path(temp_dir))
                destroy_profile_storage(pm)
                destroy_profile_storage(pm)
                self.assertFalse(pm.paths.get_config_dir().exists())
        finally:
            Constants.DATA = original_data

    def test_plaintext_profile_has_no_cryptographic_erase_claim(self) -> None:
        """Verifies explicit plaintext profiles have no keyslot or blob runtime.

        Args:
            None

        Returns:
            None
        """
        original_data = Constants.DATA
        try:
            with TemporaryDirectory() as temp_dir:
                pm = self._profile(Path(temp_dir))
                pm.config.set(
                    ProfileConfigKey.SECURITY_MODE,
                    ProfileSecurityMode.PLAINTEXT.value,
                    allow_mutating_structural_keys=True,
                )
                marker = pm.paths.get_config_dir() / 'plaintext.txt'
                marker.write_text('not cryptographically protected')
                km = KeyManager(pm)
                self.assertIsNone(km.get_database_key())
                self.assertFalse(pm.paths.get_keyslot_file().exists())
                with self.assertRaises(InvalidKeyslotError):
                    km.get_blob_key()
                destroy_profile_storage(pm)
                self.assertFalse(marker.exists())
        finally:
            Constants.DATA = original_data


if __name__ == '__main__':
    unittest.main()
