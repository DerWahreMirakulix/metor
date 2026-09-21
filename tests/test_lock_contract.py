"""Regression tests for cross-platform file-lock lifecycle behavior."""

# ruff: noqa: E402

import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.utils.lock import FileLock


class LockContractTests(unittest.TestCase):
    """
    Covers file-lock regression scenarios.
    """

    def test_file_lock_rolls_back_write_and_fsync_failures(self) -> None:
        """Failed metadata persistence closes and removes only the owned lock.

        Args:
            None

        Returns:
            None
        """
        for operation in ('write', 'fsync'):
            with self.subTest(operation=operation), TemporaryDirectory() as temp_dir:
                lock = FileLock(Path(temp_dir) / 'config.json')
                target = f'metor.utils.lock.os.{operation}'
                with (
                    patch(target, side_effect=OSError(f'{operation} failed')),
                    self.assertRaisesRegex(OSError, f'{operation} failed'),
                ):
                    lock.__enter__()

                self.assertIsNone(lock._lock_fd)
                self.assertFalse(lock.lock_path.exists())

    def test_file_lock_completes_partial_metadata_writes(self) -> None:
        """Short writes cannot leave truncated owner metadata behind.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            lock = FileLock(Path(temp_dir) / 'config.json')
            original_write = os.write

            def short_write(descriptor: int, data: bytes | memoryview) -> int:
                """Writes at most three metadata bytes per call.

                Args:
                    descriptor (int): Owned lock descriptor.
                    data (bytes | memoryview): Remaining metadata.

                Returns:
                    int: Actual number of bytes written.
                """
                return original_write(descriptor, data[:3])

            with patch('metor.utils.lock.os.write', side_effect=short_write):
                with lock:
                    expected = f'{lock._pid}:{lock._pid_create_time}'
                    self.assertEqual(lock.lock_path.read_text(), expected)

    def test_file_lock_rejects_zero_progress_and_cleans_up(self) -> None:
        """A zero-length metadata write cannot become a successful lock.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            lock = FileLock(Path(temp_dir) / 'config.json')
            with (
                patch('metor.utils.lock.os.write', return_value=0),
                self.assertRaisesRegex(OSError, 'made no progress'),
            ):
                lock.__enter__()

            self.assertIsNone(lock._lock_fd)
            self.assertFalse(lock.lock_path.exists())

    def test_file_lock_close_failure_is_visible_and_retryable(self) -> None:
        """An unconfirmed close retains ownership and never reports release.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            lock = FileLock(Path(temp_dir) / 'config.json')
            lock.__enter__()
            descriptor = lock._lock_fd
            self.assertIsNotNone(descriptor)

            with (
                patch('metor.utils.lock.os.close', side_effect=OSError('close failed')),
                self.assertRaisesRegex(OSError, 'close failed'),
            ):
                lock.__exit__(None, None, None)

            self.assertEqual(lock._lock_fd, descriptor)
            self.assertTrue(lock.lock_path.exists())
            lock.__exit__(None, None, None)
            self.assertFalse(lock.lock_path.exists())

    def test_file_lock_preserves_exchanged_foreign_lock(self) -> None:
        """Release cannot unlink a replacement created under the same pathname.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            lock = FileLock(Path(temp_dir) / 'config.json')
            displaced = Path(temp_dir) / 'owned.lock'
            lock.__enter__()
            lock.lock_path.rename(displaced)
            lock.lock_path.write_text('foreign-owner')

            lock.__exit__(None, None, None)

            self.assertEqual(lock.lock_path.read_text(), 'foreign-owner')
            self.assertTrue(displaced.exists())

    def test_file_lock_rollback_preserves_exchanged_foreign_lock(self) -> None:
        """Acquisition rollback removes no replacement from another owner.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            lock = FileLock(Path(temp_dir) / 'config.json')
            displaced = Path(temp_dir) / 'incomplete-owned.lock'

            def exchange_then_fail(
                descriptor: int,
                data: bytes | memoryview,
            ) -> int:
                """Replaces the path and fails the owned metadata write.

                Args:
                    descriptor (int): Owned lock descriptor.
                    data (bytes | memoryview): Metadata pending write.

                Returns:
                    int: This callback never returns.

                Raises:
                    OSError: Always, after exchanging the lock path.
                """
                del descriptor, data
                lock.lock_path.rename(displaced)
                lock.lock_path.write_text('foreign-owner')
                raise OSError('write failed after exchange')

            with (
                patch('metor.utils.lock.os.write', side_effect=exchange_then_fail),
                self.assertRaisesRegex(OSError, 'write failed after exchange'),
            ):
                lock.__enter__()

            self.assertEqual(lock.lock_path.read_text(), 'foreign-owner')
            self.assertTrue(displaced.exists())
            self.assertIsNone(lock._lock_fd)

    def test_process_identity_distinguishes_live_dead_reused_and_unknown(self) -> None:
        """Only definite absence or lifetime mismatch proves a stale owner.

        Args:
            None

        Returns:
            None
        """
        current = psutil.Process()
        self.assertTrue(FileLock._is_same_process(current.pid, current.create_time()))

        with patch(
            'metor.utils.lock.psutil.Process', side_effect=psutil.NoSuchProcess(7)
        ):
            self.assertFalse(FileLock._is_same_process(7, 1.0))

        reused = SimpleNamespace(create_time=lambda: 20.0, is_running=lambda: True)
        with patch('metor.utils.lock.psutil.Process', return_value=reused):
            self.assertFalse(FileLock._is_same_process(7, 10.0))

        with patch(
            'metor.utils.lock.psutil.Process', side_effect=psutil.AccessDenied(7)
        ):
            self.assertIsNone(FileLock._is_same_process(7, 10.0))

        self.assertIsNone(FileLock._is_same_process(current.pid, None))

    def test_file_lock_timeout_uses_monotonic_clock(self) -> None:
        """Wall-clock jumps cannot extend the acquisition deadline.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            lock = FileLock(Path(temp_dir) / 'config.json', timeout=1.0)
            lock.lock_path.write_text('')
            monotonic_values = iter((0.0, 0.4, 0.8, 1.2))
            with (
                patch(
                    'metor.utils.lock.time.monotonic',
                    side_effect=lambda: next(monotonic_values),
                ) as monotonic,
                patch(
                    'metor.utils.lock.time.time',
                    side_effect=(100.0, 0.0, 0.0, 101.1),
                ),
                patch('metor.utils.lock.time.sleep'),
                self.assertRaises(TimeoutError),
            ):
                lock.__enter__()

            self.assertGreater(monotonic.call_count, 0)
            self.assertTrue(lock.lock_path.exists())

    def test_file_lock_excludes_a_real_child_process(self) -> None:
        """Atomic ownership excludes another process and releases after exit.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / 'config.json'
            source_root = Path(__file__).resolve().parents[1] / 'src'
            environment = os.environ.copy()
            existing_path = environment.get('PYTHONPATH')
            environment['PYTHONPATH'] = (
                f'{source_root}{os.pathsep}{existing_path}'
                if existing_path
                else str(source_root)
            )
            child_code = (
                'import sys\n'
                'from metor.utils.lock import FileLock\n'
                'with FileLock(sys.argv[1], timeout=1.0):\n'
                "    print('ready', flush=True)\n"
                '    sys.stdin.readline()\n'
            )
            child = subprocess.Popen(
                [sys.executable, '-c', child_code, str(target)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            try:
                if child.stdout is None:
                    self.fail('Child stdout pipe is unavailable.')
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                with self.assertRaises(TimeoutError):
                    FileLock(target, timeout=0.1).__enter__()

                if child.stdin is None:
                    self.fail('Child stdin pipe is unavailable.')
                child.stdin.write('\n')
                child.stdin.flush()
                self.assertEqual(child.wait(timeout=5.0), 0)

                with FileLock(target, timeout=0.5):
                    self.assertTrue(Path(f'{target}.lock').exists())
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5.0)
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream is not None:
                        stream.close()

    def test_file_lock_closes_handle_before_unlink(self) -> None:
        """
        Verifies that file lock closes handle before unlink.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            target_file = Path(temp_dir) / 'config.json'
            lock = FileLock(target_file)
            original_unlink = Path.unlink

            def guarded_unlink(path: Path, missing_ok: bool = False) -> None:
                """
                Simulates Windows refusing to delete an open file handle.

                Args:
                    path (Path): The path being unlinked.
                    missing_ok (bool): Whether missing paths are tolerated.

                Returns:
                    None
                """

                if path == lock.lock_path and lock._lock_fd is not None:
                    raise PermissionError('file is still open')

                original_unlink(path, missing_ok=missing_ok)

            with patch.object(Path, 'unlink', new=guarded_unlink):
                with lock:
                    self.assertTrue(lock.lock_path.exists())

            self.assertFalse(lock.lock_path.exists())


if __name__ == '__main__':
    unittest.main()
