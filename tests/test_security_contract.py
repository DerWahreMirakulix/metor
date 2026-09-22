"""Regression tests for security-critical local file destruction helpers."""

# ruff: noqa: E402

import os
import secrets
import stat
import sys
import unittest
from array import array
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.utils import Constants
from metor.shared.security import secure_clear_buffer
from metor.utils.security import secure_remove_path, secure_shred_file


class SecurityContractTests(unittest.TestCase):
    """
    Covers security contract regression scenarios.
    """

    def test_secure_clear_buffer_clears_bytearray_and_repeated_empty_views(
        self,
    ) -> None:
        """Mutable byte buffers support complete and idempotent clearing.

        Args:
            None

        Returns:
            None
        """
        secret = bytearray(b'secret')
        secure_clear_buffer(secret)
        secure_clear_buffer(secret)
        self.assertEqual(secret, bytearray(len(secret)))

        empty = memoryview(bytearray())
        secure_clear_buffer(empty)
        secure_clear_buffer(empty)
        self.assertEqual(empty.nbytes, 0)

    def test_secure_clear_buffer_clears_complete_typed_view(self) -> None:
        """Every byte in a contiguous typed memory view is overwritten.

        Args:
            None

        Returns:
            None
        """
        values = array('I', [0xFFFFFFFF, 0xAAAAAAAA])
        view = memoryview(values)
        self.assertEqual(len(view), 2)
        self.assertEqual(view.nbytes, values.itemsize * 2)

        secure_clear_buffer(view)
        secure_clear_buffer(view)

        self.assertEqual(values.tobytes(), bytes(view.nbytes))

    def test_secure_clear_buffer_rejects_unsafe_views_without_mutation(self) -> None:
        """Readonly and strided views report failure and retain their bytes.

        Args:
            None

        Returns:
            None
        """
        readonly = memoryview(b'secret')
        with self.assertRaisesRegex(TypeError, 'read-only'):
            secure_clear_buffer(readonly)
        self.assertEqual(readonly.tobytes(), b'secret')

        owner = bytearray(b'01234567')
        non_contiguous = memoryview(owner)[::2]
        with self.assertRaisesRegex(BufferError, 'contiguous'):
            secure_clear_buffer(non_contiguous)
        self.assertEqual(owner, bytearray(b'01234567'))

    def test_secure_shred_file_raises_when_overwrite_fails(self) -> None:
        """
        Verifies that secure shred file raises when overwrite fails.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / 'secret.bin'
            file_path.write_bytes(b'secret')

            with patch('metor.utils.security.os.write', side_effect=OSError('denied')):
                with self.assertRaises(OSError):
                    secure_shred_file(file_path)

            self.assertTrue(file_path.exists())

    def test_secure_shred_file_uses_fixed_blocks_and_handles_short_writes(
        self,
    ) -> None:
        """Large files use bounded randomness and every partial write completes.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / 'secret.bin'
            size = (Constants.SECURE_SHRED_BLOCK_BYTES * 2) + 17
            file_path.write_bytes(b'x' * size)
            original_write = os.write

            def short_write(descriptor: int, data: bytes | memoryview) -> int:
                """Writes at most one quarter-block through the real descriptor.

                Args:
                    descriptor (int): Open sensitive-file descriptor.
                    data (bytes | memoryview): Remaining random overwrite bytes.

                Returns:
                    int: Actual short write length.
                """
                short_length = max(1, Constants.SECURE_SHRED_BLOCK_BYTES // 4)
                return original_write(descriptor, data[:short_length])

            with (
                patch(
                    'metor.utils.security.secrets.token_bytes',
                    wraps=secrets.token_bytes,
                ) as token_bytes,
                patch('metor.utils.security.os.write', side_effect=short_write),
            ):
                secure_shred_file(file_path)

            self.assertFalse(file_path.exists())
            self.assertEqual(
                [call.args[0] for call in token_bytes.call_args_list],
                [
                    Constants.SECURE_SHRED_BLOCK_BYTES,
                    Constants.SECURE_SHRED_BLOCK_BYTES,
                    17,
                ],
            )

    def test_secure_shred_file_rejects_zero_progress(self) -> None:
        """A zero-length write leaves the path present and reports failure.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / 'secret.bin'
            file_path.write_bytes(b'secret')

            with (
                patch('metor.utils.security.os.write', return_value=0),
                self.assertRaisesRegex(OSError, 'made no progress'),
            ):
                secure_shred_file(file_path)

            self.assertTrue(file_path.exists())

    def test_secure_shred_file_reports_fsync_and_unlink_failures(self) -> None:
        """Durability and removal errors cannot become successful cleanup.

        Args:
            None

        Returns:
            None
        """
        for operation in ('fsync', 'unlink'):
            with self.subTest(operation=operation), TemporaryDirectory() as tmp_dir:
                file_path = Path(tmp_dir) / 'secret.bin'
                file_path.write_bytes(b'secret')
                target = f'metor.utils.security.os.{operation}'
                with (
                    patch(target, side_effect=OSError(f'{operation} denied')),
                    self.assertRaisesRegex(OSError, f'{operation} denied'),
                ):
                    secure_shred_file(file_path)
                self.assertTrue(file_path.exists())

    def test_secure_shred_file_rejects_direct_symlink_and_hardlink(self) -> None:
        """Link aliases cannot redirect or multiply a sensitive overwrite.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target = root / 'target.bin'
            target.write_bytes(b'outside')
            symlink = root / 'secret-link.bin'
            symlink.symlink_to(target)

            with self.assertRaises(OSError):
                secure_shred_file(symlink)
            self.assertEqual(target.read_bytes(), b'outside')
            self.assertTrue(symlink.is_symlink())

            hardlink = root / 'secret-hardlink.bin'
            os.link(target, hardlink)
            with self.assertRaisesRegex(OSError, 'multiply linked'):
                secure_shred_file(hardlink)
            self.assertEqual(target.read_bytes(), b'outside')
            self.assertEqual(hardlink.read_bytes(), b'outside')

    def test_secure_shred_file_detects_path_exchange_before_unlink(self) -> None:
        """A replacement path is preserved instead of unlinked as the opened file.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            file_path = root / 'secret.bin'
            opened_path = root / 'opened.bin'
            file_path.write_bytes(b'secret')
            original_fsync = os.fsync

            def exchange_path(descriptor: int) -> None:
                """Swaps the pathname after syncing the opened original.

                Args:
                    descriptor (int): Open sensitive-file descriptor.

                Returns:
                    None
                """
                original_fsync(descriptor)
                file_path.rename(opened_path)
                file_path.write_bytes(b'replacement')

            with (
                patch('metor.utils.security.os.fsync', side_effect=exchange_path),
                self.assertRaisesRegex(OSError, 'changed during cleanup'),
            ):
                secure_shred_file(file_path)

            self.assertEqual(file_path.read_bytes(), b'replacement')
            self.assertTrue(opened_path.exists())

    def test_secure_shred_file_removes_empty_regular_file(self) -> None:
        """An empty ordinary file is synced and removed successfully.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / 'empty.bin'
            file_path.touch()
            secure_shred_file(file_path)
            self.assertFalse(file_path.exists())

    def test_secure_remove_path_recursively_removes_nested_tree(self) -> None:
        """
        Verifies that secure remove path recursively removes nested tree.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / 'profile'
            nested = root / 'hidden_service'
            nested.mkdir(parents=True)
            (root / 'storage.db').write_bytes(b'db')
            (nested / 'metor_secret.key').write_bytes(b'key')

            secure_remove_path(root)

            self.assertFalse(root.exists())

    def test_secure_remove_path_unlinks_symlink_without_touching_target(self) -> None:
        """Recursive cleanup removes a link rather than traversing its target.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            target = root / 'outside'
            target.mkdir()
            marker = target / 'keep.bin'
            marker.write_bytes(b'outside')
            link = root / 'profile-link'
            link.symlink_to(target, target_is_directory=True)

            secure_remove_path(link)

            self.assertFalse(link.exists())
            self.assertEqual(marker.read_bytes(), b'outside')

    def test_secure_remove_path_rejects_root_exchange_before_directory_open(
        self,
    ) -> None:
        """A root swap to an outside link cannot redirect recursive cleanup.

        Args:
            None

        Returns:
            None
        """
        if os.name == 'nt':
            self.skipTest('POSIX descriptor-relative regression.')
        with TemporaryDirectory() as tmp_dir:
            sandbox = Path(tmp_dir)
            profile = sandbox / 'profile'
            moved = sandbox / 'moved-profile'
            outside = sandbox / 'outside'
            profile.mkdir()
            outside.mkdir()
            (profile / 'owned.bin').write_bytes(b'owned')
            sentinel = outside / 'sentinel.bin'
            sentinel.write_bytes(b'outside')
            original_open = os.open
            exchanged = False

            def exchange_before_open(
                path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                """Swaps the selected leaf immediately before its safe open.

                Args:
                    path (str | bytes | os.PathLike[str] | os.PathLike[bytes]): Open target.
                    flags (int): Open flags.
                    mode (int): Optional creation mode.
                    dir_fd (int | None): Anchored parent descriptor.

                Returns:
                    int: Descriptor returned by the real open.
                """
                nonlocal exchanged
                if path == 'profile' and dir_fd is not None and not exchanged:
                    exchanged = True
                    profile.rename(moved)
                    profile.symlink_to(outside, target_is_directory=True)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with (
                patch('metor.utils.security.os.open', side_effect=exchange_before_open),
                self.assertRaises(OSError),
            ):
                secure_remove_path(profile)

            self.assertEqual(sentinel.read_bytes(), b'outside')
            self.assertTrue(profile.is_symlink())
            self.assertTrue((moved / 'owned.bin').exists())

    def test_secure_remove_path_keeps_outside_tree_after_opened_root_exchange(
        self,
    ) -> None:
        """Recursion remains bound to its opened directory after a pathname swap.

        Args:
            None

        Returns:
            None
        """
        if os.name == 'nt':
            self.skipTest('POSIX descriptor-relative regression.')
        with TemporaryDirectory() as tmp_dir:
            sandbox = Path(tmp_dir)
            profile = sandbox / 'profile'
            moved = sandbox / 'moved-profile'
            outside = sandbox / 'outside'
            profile.mkdir()
            outside.mkdir()
            (profile / 'owned.bin').write_bytes(b'owned')
            sentinel = outside / 'sentinel.bin'
            sentinel.write_bytes(b'outside')
            original_listdir = os.listdir
            exchanged = False

            def exchange_during_listdir(descriptor: int) -> list[str]:
                """Moves the opened root and replaces its pathname with a link.

                Args:
                    descriptor (int): Opened directory descriptor.

                Returns:
                    list[str]: Real entries from the still-open directory.
                """
                nonlocal exchanged
                if not exchanged:
                    exchanged = True
                    profile.rename(moved)
                    profile.symlink_to(outside, target_is_directory=True)
                return list(original_listdir(descriptor))

            with (
                patch(
                    'metor.utils.security.os.listdir',
                    side_effect=exchange_during_listdir,
                ),
                self.assertRaisesRegex(OSError, 'changed during cleanup'),
            ):
                secure_remove_path(profile)

            self.assertEqual(sentinel.read_bytes(), b'outside')
            self.assertTrue(profile.is_symlink())

    def test_secure_remove_path_reports_partial_owned_cleanup(self) -> None:
        """An unsupported later entry leaves a visible failure after owned work.

        Args:
            None

        Returns:
            None
        """
        if os.name == 'nt' or not hasattr(os, 'mkfifo'):
            self.skipTest('POSIX FIFO regression.')
        with TemporaryDirectory() as tmp_dir:
            profile = Path(tmp_dir) / 'profile'
            profile.mkdir()
            owned = profile / 'owned.bin'
            owned.write_bytes(b'owned')
            fifo = profile / 'blocked.fifo'
            os.mkfifo(fifo)
            original_listdir = os.listdir

            def owned_first(descriptor: int) -> list[str]:
                """Returns a deterministic partial-cleanup traversal order.

                Args:
                    descriptor (int): Open directory descriptor.

                Returns:
                    list[str]: Owned regular file before the unsupported FIFO.
                """
                entries = list(original_listdir(descriptor))
                return sorted(entries, key=lambda name: name != 'owned.bin')

            with (
                patch('metor.utils.security.os.listdir', side_effect=owned_first),
                self.assertRaisesRegex(OSError, 'unsupported file type'),
            ):
                secure_remove_path(profile)

            self.assertFalse(owned.exists())
            self.assertTrue(fifo.exists())
            self.assertTrue(profile.exists())

    def test_secure_remove_path_rejects_windows_reparse_point(self) -> None:
        """A Windows reparse attribute produces a visible bounded failure.

        Args:
            None

        Returns:
            None
        """
        reparse_info = SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_file_attributes=0x00000400,
        )
        simulated_path = Path('simulated-reparse-point')
        with (
            patch('metor.utils.security.os.name', 'nt'),
            patch('metor.utils.security.os.lstat', return_value=reparse_info),
            self.assertRaisesRegex(OSError, 'reparse point'),
        ):
            secure_remove_path(simulated_path)


if __name__ == '__main__':
    unittest.main()
