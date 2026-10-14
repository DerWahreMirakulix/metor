"""Credential atomic replacement and profile lifecycle protection compatibility."""

import hmac
import os
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from private_fixtures import PrivateTemporaryDirectory
from metor.core.daemon.managed.quick_unlock import (
    QuickUnlockStorageError,
    QuickUnlockStore,
)
from metor.data import SettingKey, Settings, SqlManager
from metor.data.profile import ProfileManager, ProfileSecurityMode
from metor.data.profile.migration.journal import write_migration_journal
from metor.utils import Constants, open_private_binary_file


class QuickUnlockStorageTests(unittest.TestCase):
    """Exercise unchanged PIN proofs across real filesystem lifecycle operations."""

    def test_reinitialize_and_migrate_profile_preserves_pin_credential(self) -> None:
        """Reopening key directories and generation swaps share one ACL policy."""
        with PrivateTemporaryDirectory(prefix='metor pin ü ') as directory:
            with patch.object(Constants, 'DATA', Path(directory)):
                result = ProfileManager.add_profile_folder(
                    'credential', master_password='old-password'
                )
                self.assertTrue(result.success)
                profile = ProfileManager('credential')
                salt, verifier, challenge = '01' * 16, '02' * 32, '03' * 32
                proof = hmac.new(
                    bytes.fromhex(verifier), bytes.fromhex(challenge), 'sha256'
                ).hexdigest()
                path = profile.paths.get_quick_unlock_file()
                store = QuickUnlockStore(path)
                try:
                    store.configure(salt, verifier)
                    profile.paths.create_directories()
                    ProfileManager('credential').initialize()
                    self.assertTrue(QuickUnlockStore(path).verify(challenge, proof))
                    original_get_bool = Settings.get_bool

                    def allow_plaintext(
                        key: SettingKey, *args: object, **kwargs: object
                    ) -> bool:
                        """Enable only explicit fixture conversion to plaintext."""
                        if key is SettingKey.ALLOW_PLAINTEXT_PROFILES:
                            return True
                        return original_get_bool(key)

                    with patch.object(
                        Settings, 'get_bool', side_effect=allow_plaintext
                    ):
                        result = ProfileManager.migrate_profile_security(
                            'credential',
                            ProfileSecurityMode.PLAINTEXT,
                            current_password='old-password',
                        )
                    self.assertTrue(result.success)
                    self.assertTrue(QuickUnlockStore(path).verify(challenge, proof))
                    result = ProfileManager.migrate_profile_security(
                        'credential',
                        ProfileSecurityMode.ENCRYPTED,
                        new_password='new-password',
                    )
                    self.assertTrue(result.success)
                    self.assertTrue(QuickUnlockStore(path).verify(challenge, proof))
                    store.remove()
                    self.assertIsNone(store.metadata())
                finally:
                    SqlManager.close_connection(profile.paths.get_db_file())

    @unittest.skipIf(os.name == 'nt', 'POSIX FIFO read-boundary regression.')
    def test_metadata_rejects_fifo_without_blocking(self) -> None:
        """Malformed local storage cannot indefinitely occupy an auth worker."""
        with PrivateTemporaryDirectory() as directory:
            path = Path(directory) / 'pin.json'
            getattr(os, 'mkfifo')(path, 0o600)
            child = subprocess.run(
                [
                    sys.executable,
                    '-c',
                    'from pathlib import Path; import sys; '
                    'from metor.core.daemon.managed.quick_unlock import '
                    'QuickUnlockStore, QuickUnlockStorageError\n'
                    'try: QuickUnlockStore(Path(sys.argv[1])).metadata()\n'
                    'except QuickUnlockStorageError: sys.exit(0)\n'
                    'sys.exit(1)\n',
                    str(path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=Constants.DEFAULT_IPC_TIMEOUT,
                check=False,
            )
            self.assertEqual(child.returncode, 0)
            self.assertTrue(path.exists())

    @unittest.skipIf(os.name == 'nt', 'POSIX replacement read-boundary regression.')
    def test_metadata_rejects_replacement_before_read_without_blocking(self) -> None:
        """Validation cannot be raced with a FIFO, alias or unsafe file permissions."""
        for replacement in ('fifo', 'symlink', 'hardlink', 'public-file'):
            with self.subTest(replacement=replacement):
                child = subprocess.run(
                    [
                        sys.executable,
                        '-c',
                        'import sys; sys.path.insert(0, sys.argv[1]); '
                        'from test_quick_unlock_storage import QuickUnlockStorageTests; '
                        'QuickUnlockStorageTests()._assert_replacement_rejected(sys.argv[2])',
                        str(Path(__file__).parent),
                        replacement,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=Constants.DEFAULT_IPC_TIMEOUT,
                    check=False,
                )
                self.assertEqual(child.returncode, 0, child.stdout[-4096:])

    def _assert_replacement_rejected(self, replacement: str) -> None:
        """Run one actual leaf replacement in a child with a parent-owned deadline."""
        with PrivateTemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'pin.json'
            store = QuickUnlockStore(path)
            original_open = os.open
            store.configure('01' * 16, '02' * 32)
            original = path.read_bytes()
            saved = root / 'saved'
            swapped = False

            def swap_before_open(
                target: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                """Replace the exact leaf after validation at the kernel-open boundary."""
                nonlocal swapped
                if target == path and not swapped:
                    swapped = True
                    path.replace(saved)
                    if replacement == 'fifo':
                        getattr(os, 'mkfifo')(path, 0o600)
                    elif replacement == 'symlink':
                        path.symlink_to(saved)
                    elif replacement == 'hardlink':
                        os.link(saved, path)
                    else:
                        path.write_bytes(saved.read_bytes())
                        path.chmod(0o644)
                return original_open(target, flags, *args, **kwargs)  # type: ignore[arg-type]

            try:
                with (
                    patch(
                        'metor.core.daemon.managed.quick_unlock.os.open',
                        side_effect=swap_before_open,
                    ),
                    self.assertRaises(QuickUnlockStorageError),
                ):
                    store.metadata()
                self.assertTrue(swapped)
                self.assertEqual(saved.read_bytes(), original)
            finally:
                path.unlink(missing_ok=True)
                saved.unlink(missing_ok=True)

    def test_private_exclusive_output_preserves_existing_entry(self) -> None:
        """A random-name collision cannot modify contents, ACLs, or file identity."""
        with PrivateTemporaryDirectory() as directory:
            path = Path(directory) / 'collision'
            with open_private_binary_file(path, exclusive=True) as stream:
                stream.write(b'owned-existing')
            before = path.stat()
            with self.assertRaises(FileExistsError):
                with open_private_binary_file(path, exclusive=True):
                    self.fail('Existing entry must never be opened for output.')
            self.assertEqual(path.read_bytes(), b'owned-existing')
            self.assertEqual(path.stat().st_ino, before.st_ino)
            self.assertEqual(path.stat().st_mode, before.st_mode)

    def test_credential_temp_collision_preserves_existing_file_and_verifier(
        self,
    ) -> None:
        """A failed exclusive create must not unlink a file owned by another write."""
        with PrivateTemporaryDirectory() as directory:
            path = Path(directory) / 'pin.json'
            store = QuickUnlockStore(path)
            store.configure('01' * 16, '02' * 32)
            collision = path.parent / '.pin.json.fixed.tmp'
            collision.write_bytes(b'other-write')
            with (
                patch(
                    'metor.core.daemon.managed.quick_unlock.secrets.token_hex',
                    return_value='fixed',
                ),
                self.assertRaises(QuickUnlockStorageError),
            ):
                store.configure('03' * 16, '04' * 32)
            self.assertEqual(collision.read_bytes(), b'other-write')
            self.assertEqual(store.metadata(), ('01' * 16, bytes.fromhex('02' * 32)))

    def test_migration_journal_temp_collision_preserves_existing_transaction(
        self,
    ) -> None:
        """Journal replacement retains exclusive staging and leaves collisions alone."""
        with PrivateTemporaryDirectory() as directory:
            path = Path(directory) / 'journal.json'
            write_migration_journal(path, 'fixture', 'prepared')
            before = path.read_bytes()
            collision = path.parent / '.journal.json.fixed.tmp'
            collision.write_bytes(b'other-transaction')
            with (
                patch(
                    'metor.data.profile.migration.journal.secrets.token_hex',
                    return_value='fixed',
                ),
                self.assertRaises(FileExistsError),
            ):
                write_migration_journal(path, 'fixture', 'committed')
            self.assertEqual(collision.read_bytes(), b'other-transaction')
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
