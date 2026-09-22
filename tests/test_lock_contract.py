"""Regression tests for cross-platform file-lock lifecycle behavior."""

# ruff: noqa: E402

import os
import stat
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.utils import Constants
from metor.utils.lock import FileLock


class LockContractTests(unittest.TestCase):
    """
    Covers file-lock regression scenarios.
    """

    def test_file_lock_rolls_back_write_and_fsync_failures(self) -> None:
        """Failed metadata persistence releases but retains the stable object.

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
                self.assertTrue(lock.lock_path.exists())
                with FileLock(Path(temp_dir) / 'config.json', timeout=0.5):
                    pass

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

    def test_file_lock_creation_uses_owner_only_mode_under_permissive_umask(
        self,
    ) -> None:
        """Atomic creation supplies an explicit private POSIX mode.

        Args:
            None

        Returns:
            None
        """
        if os.name == 'nt':
            self.skipTest('POSIX permission regression.')
        with TemporaryDirectory() as temp_dir:
            previous_umask = os.umask(0o022)
            try:
                with FileLock(Path(temp_dir) / 'config.json') as lock:
                    mode = stat.S_IMODE(lock.lock_path.stat().st_mode)
                    self.assertEqual(mode, 0o600)
            finally:
                os.umask(previous_umask)

    def test_acquisition_rejects_fifo_link_hardlink_and_oversized_metadata(
        self,
    ) -> None:
        """Special, linked, and unbounded lock objects fail before ownership.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / 'config.json'
            lock = FileLock(target)
            oversized = '7:10.0' + ('x' * Constants.FILE_LOCK_METADATA_MAX_BYTES)
            lock.lock_path.write_text(oversized)
            lock.lock_path.chmod(0o600)
            with self.assertRaises(OSError):
                lock.__enter__()
            self.assertTrue(lock.lock_path.exists())

            lock.lock_path.unlink()
            real = root / 'real.lock'
            real.write_text('7:10.0')
            real.chmod(0o600)
            lock.lock_path.symlink_to(real)
            with self.assertRaises(OSError):
                lock.__enter__()
            self.assertEqual(real.read_text(), '7:10.0')

            lock.lock_path.unlink()
            lock.lock_path.write_text('7:10.0')
            linked = root / 'linked.lock'
            os.link(lock.lock_path, linked)
            with self.assertRaises(OSError):
                lock.__enter__()
            self.assertEqual(linked.read_text(), '7:10.0')

            if hasattr(os, 'mkfifo') and os.name != 'nt':
                lock.lock_path.unlink()
                linked.unlink()
                os.mkfifo(lock.lock_path)
                with self.assertRaises(OSError):
                    lock.__enter__()

            with (
                patch.object(
                    lock,
                    '_open_lock_descriptor',
                    side_effect=PermissionError('lock unreadable'),
                ),
                self.assertRaisesRegex(PermissionError, 'lock unreadable'),
            ):
                lock.__enter__()

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
            self.assertTrue(lock.lock_path.exists())

    def test_file_lock_close_failure_is_visible_without_descriptor_retry(self) -> None:
        """An unconfirmed close leaves recovery metadata but never reuses the FD.

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

            self.assertIsNone(lock._lock_fd)
            self.assertTrue(lock.lock_path.exists())
            with patch('metor.utils.lock.os.close') as repeated_close:
                lock.__exit__(None, None, None)
            repeated_close.assert_not_called()

            os.close(descriptor)
            lock.lock_path.unlink()

    def test_file_lock_unlock_failure_is_visible_and_descriptor_is_closed(
        self,
    ) -> None:
        """A native unlock error propagates after bounded descriptor cleanup.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / 'config.json'
            lock = FileLock(target)
            lock.__enter__()
            with (
                patch(
                    'metor.utils.lock._unlock_descriptor',
                    side_effect=OSError('unlock failed'),
                ),
                self.assertRaisesRegex(OSError, 'unlock failed'),
            ):
                lock.__exit__(None, None, None)

            self.assertIsNone(lock._lock_fd)
            with FileLock(target, timeout=0.5):
                pass

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

    def test_file_lock_rejects_exchange_during_native_acquisition(self) -> None:
        """A path exchanged after opening cannot become an acquired lock.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lock = FileLock(root / 'config.json')
            displaced = root / 'opened.lock'

            def exchange(_descriptor: int) -> bool:
                """Exchanges the canonical name at the native lock boundary.

                Args:
                    _descriptor (int): Opened descriptor being tested.

                Returns:
                    bool: Simulated successful native lock acquisition.
                """
                lock.lock_path.rename(displaced)
                lock.lock_path.write_text('foreign')
                return True

            with (
                patch('metor.utils.lock._try_lock_descriptor', side_effect=exchange),
                self.assertRaisesRegex(OSError, 'changed during acquisition'),
            ):
                lock.__enter__()

            self.assertIsNone(lock._lock_fd)
            self.assertEqual(lock.lock_path.read_text(), 'foreign')
            self.assertTrue(displaced.exists())

    def test_file_lock_timeout_uses_monotonic_clock(self) -> None:
        """Wall-clock jumps cannot extend the acquisition deadline.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            lock = FileLock(Path(temp_dir) / 'config.json', timeout=1.0)
            monotonic_values = iter((0.0, 0.4, 0.8, 1.2))
            with (
                patch(
                    'metor.utils.lock.time.monotonic',
                    side_effect=lambda: next(monotonic_values),
                ) as monotonic,
                patch('metor.utils.lock._try_lock_descriptor', return_value=False),
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

    def test_crashed_owner_and_two_contenders_never_overlap(self) -> None:
        """Crash recovery and synchronized contenders share one stable OS lock.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / 'config.json'
            ready = root / 'owner-ready'
            start = root / 'start'
            attempted = root / 'attempted'
            entered = root / 'entered'
            released = root / 'released'
            critical = root / 'critical'
            violation = root / 'violation'
            for directory in (attempted, entered, released):
                directory.mkdir()

            source_root = Path(__file__).resolve().parents[1] / 'src'
            environment = os.environ.copy()
            existing_path = environment.get('PYTHONPATH')
            environment['PYTHONPATH'] = (
                f'{source_root}{os.pathsep}{existing_path}'
                if existing_path
                else str(source_root)
            )
            owner_code = (
                'import sys, time\n'
                'from pathlib import Path\n'
                'from metor.utils.lock import FileLock\n'
                'with FileLock(Path(sys.argv[1]), timeout=2.0):\n'
                '    Path(sys.argv[2]).write_text("ready")\n'
                '    while True: time.sleep(0.01)\n'
            )
            contender_code = (
                'import os, sys, time\n'
                'from pathlib import Path\n'
                'from metor.utils.lock import FileLock\n'
                'target, start, attempted, entered, released, critical, violation = '
                'map(Path, sys.argv[1:])\n'
                'while not start.exists(): time.sleep(0.005)\n'
                'identity = str(os.getpid())\n'
                '(attempted / identity).write_text("attempted")\n'
                'with FileLock(target, timeout=5.0):\n'
                '    try:\n'
                '        critical.mkdir()\n'
                '    except FileExistsError:\n'
                '        violation.write_text(identity)\n'
                '    (entered / identity).write_text("entered")\n'
                '    while not (released / identity).exists(): time.sleep(0.005)\n'
                '    if critical.exists(): critical.rmdir()\n'
            )

            def wait_for_count(directory: Path, count: int) -> tuple[Path, ...]:
                """Waits for an exact minimum count of process marker files.

                Args:
                    directory (Path): Marker directory written by child processes.
                    count (int): Minimum marker count required.

                Returns:
                    tuple[Path, ...]: Current markers after the condition is met.

                Raises:
                    AssertionError: If child synchronization exceeds its deadline.
                """
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    markers = tuple(directory.iterdir())
                    if len(markers) >= count:
                        return markers
                    time.sleep(0.005)
                self.fail(f'Timed out waiting for {count} markers in {directory}.')

            owner = subprocess.Popen(
                [sys.executable, '-c', owner_code, str(target), str(ready)],
                env=environment,
            )
            contenders: list[subprocess.Popen[str]] = []
            try:
                deadline = time.monotonic() + 5.0
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertTrue(ready.exists())
                stable_identity = Path(f'{target}.lock').stat()
                owner.terminate()
                self.assertNotEqual(owner.wait(timeout=5.0), 0)

                arguments = tuple(
                    str(path)
                    for path in (
                        target,
                        start,
                        attempted,
                        entered,
                        released,
                        critical,
                        violation,
                    )
                )
                contenders = [
                    subprocess.Popen(
                        [sys.executable, '-c', contender_code, *arguments],
                        env=environment,
                        text=True,
                    )
                    for _ in range(2)
                ]
                start.write_text('start')
                wait_for_count(attempted, 2)
                first_markers = wait_for_count(entered, 1)
                self.assertEqual(len(first_markers), 1)
                self.assertFalse(violation.exists())
                time.sleep(0.05)
                self.assertEqual(len(tuple(entered.iterdir())), 1)

                first_identity = first_markers[0].name
                (released / first_identity).write_text('release')
                second_markers = wait_for_count(entered, 2)
                second_identity = next(
                    marker.name
                    for marker in second_markers
                    if marker.name != first_identity
                )
                self.assertFalse(violation.exists())
                (released / second_identity).write_text('release')
                for contender in contenders:
                    self.assertEqual(contender.wait(timeout=5.0), 0)

                final_identity = Path(f'{target}.lock').stat()
                self.assertEqual(
                    (stable_identity.st_dev, stable_identity.st_ino),
                    (final_identity.st_dev, final_identity.st_ino),
                )
                self.assertFalse(violation.exists())
            finally:
                if owner.poll() is None:
                    owner.terminate()
                    owner.wait(timeout=5.0)
                for contender in contenders:
                    if contender.poll() is None:
                        contender.terminate()
                        contender.wait(timeout=5.0)

    def test_file_lock_retains_and_reuses_one_stable_object(self) -> None:
        """Release leaves one stable object for every later native acquisition.

        Args:
            None

        Returns:
            None
        """

        with TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / 'config.json'
            with FileLock(target) as first:
                first_identity = first.lock_path.stat()
            self.assertTrue(first.lock_path.exists())
            with FileLock(target) as second:
                second_identity = second.lock_path.stat()
            self.assertEqual(
                (first_identity.st_dev, first_identity.st_ino),
                (second_identity.st_dev, second_identity.st_ino),
            )


if __name__ == '__main__':
    unittest.main()
