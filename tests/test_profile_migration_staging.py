"""Private migration generations preserve payloads and reject unsafe sources."""

# ruff: noqa: E402

import os
import stat
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.data.profile.migration.staging import copy_private_profile_tree
from metor.utils import create_private_directory_tree, secure_remove_path
from private_fixtures import PrivateTemporaryDirectory


class ProfileMigrationStagingTests(unittest.TestCase):
    """Exercises actual copied generations independently of the key transform."""

    def test_nested_generation_is_private_readable_and_removable(self) -> None:
        """Elevated Windows tokens must not assign default group owners to copies."""
        with PrivateTemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'target'
            create_private_directory_tree(source, (('nested', 'blobs'),))
            payload = bytes(range(256)) * 2048
            (source / 'nested' / 'blobs' / 'payload').write_bytes(payload)
            (source / 'metadata').write_bytes(b'metadata')

            copy_private_profile_tree(source, target)

            self.assertEqual(
                (target / 'nested' / 'blobs' / 'payload').read_bytes(), payload
            )
            self.assertEqual((target / 'metadata').read_bytes(), b'metadata')
            for entry in (target, *target.rglob('*')):
                self._assert_private(entry)
            secure_remove_path(target)
            self.assertFalse(target.exists())
            self.assertEqual(
                (source / 'nested' / 'blobs' / 'payload').read_bytes(), payload
            )

    def test_hardlink_source_is_rejected_without_touching_shared_content(self) -> None:
        """A profile link cannot import or alter content outside its generation."""
        with PrivateTemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'target'
            create_private_directory_tree(source, ())
            outside = root / 'outside'
            outside.write_bytes(b'outside')
            os.link(outside, source / 'linked')
            with self.assertRaises(OSError):
                copy_private_profile_tree(source, target)
            secure_remove_path(target)
            self.assertEqual(outside.read_bytes(), b'outside')

    def test_replaced_source_is_rejected_before_content_is_copied(self) -> None:
        """Opened file identity must match the entry classified by the transaction."""
        with PrivateTemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'target'
            create_private_directory_tree(source, ())
            payload = source / 'payload'
            payload.write_bytes(b'original')
            replacement = root / 'replacement'
            replacement.write_bytes(b'other-file')
            original_open = os.open

            def replaced_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                """Substitutes only the source descriptor after its lstat check."""
                if path == payload:
                    return original_open(replacement, flags)
                return original_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

            with (
                patch(
                    'metor.data.profile.migration.staging.os.open',
                    side_effect=replaced_open,
                ),
                self.assertRaises(OSError),
            ):
                copy_private_profile_tree(source, target)
            self.assertFalse((target / 'payload').exists())
            self.assertEqual(replacement.read_bytes(), b'other-file')
            secure_remove_path(target)

    @unittest.skipIf(os.name == 'nt', 'POSIX link and FIFO source regression.')
    def test_symlink_and_fifo_sources_are_rejected(self) -> None:
        """Staging never follows a symbolic link or reads a blocking special file."""
        with PrivateTemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'target'
            create_private_directory_tree(source, ())
            outside = root / 'outside'
            outside.write_bytes(b'outside')
            linked = source / 'linked'
            linked.symlink_to(outside)
            with self.assertRaises(OSError):
                copy_private_profile_tree(source, target)
            linked.unlink()
            getattr(os, 'mkfifo')(source / 'fifo')
            with self.assertRaises(OSError):
                copy_private_profile_tree(source, target)
            secure_remove_path(target)
            self.assertEqual(outside.read_bytes(), b'outside')

    def _assert_private(self, path: Path) -> None:
        """Checks exact native ownership and access on every copied object."""
        if os.name != 'nt':
            info = path.stat()
            self.assertEqual(info.st_uid, getattr(os, 'getuid')())
            self.assertEqual(
                stat.S_IMODE(info.st_mode), 0o700 if path.is_dir() else 0o600
            )
            return
        import msvcrt

        from metor.utils.security import (
            _open_windows_directory_handle,
            _open_windows_file,
        )
        from metor.utils.windows_acl import validate_private_windows_dacl

        if path.is_dir():
            handle, close = _open_windows_directory_handle(path)
            try:
                validate_private_windows_dacl(handle, directory=True)
            finally:
                close(handle)
        else:
            descriptor = _open_windows_file(path)
            self.assertIsNotNone(descriptor)
            assert descriptor is not None
            try:
                validate_private_windows_dacl(
                    getattr(msvcrt, 'get_osfhandle')(descriptor), directory=False
                )
            finally:
                os.close(descriptor)
