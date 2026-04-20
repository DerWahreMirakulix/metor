"""
Module providing a cross-platform file locking mechanism via a Context Manager.
Ensures that files are not concurrently modified by different processes.
"""

import os
import time
import psutil
from typing import Optional, Type
from types import TracebackType
from pathlib import Path

# Local Package Imports
from metor.utils.constants import Constants


class FileLock:
    """
    A context manager for providing cross-process file locking.
    Uses an atomic OS-level file creation flag. Cleans up stale ghost locks
    by validating the stored Process ID (PID).
    """

    def __init__(
        self,
        target_file_path: str | Path,
        timeout: float = Constants.FILE_LOCK_TIMEOUT_SEC,
        stale_age: float = Constants.FILE_LOCK_STALE_AGE_SEC,
    ) -> None:
        """
        Initializes the FileLock instance.

        Args:
            target_file_path (str | Path): The absolute path to the file that needs locking.
            timeout (float): Maximum time in seconds to wait for the lock to become available.
            stale_age (float): Seconds before a lock is considered a 'ghost lock' from a crashed process.

        Returns:
            None
        """
        self.lock_path: Path = Path(f'{target_file_path}.lock')
        self.timeout: float = timeout
        self.stale_age: float = stale_age
        self._pid: int = os.getpid()
        self._pid_create_time: float = psutil.Process(self._pid).create_time()
        self._lock_fd: Optional[int] = None

    @staticmethod
    def _parse_lock_metadata(raw_text: str) -> tuple[Optional[int], Optional[float]]:
        """
        Parses one lockfile metadata payload.

        Args:
            raw_text (str): The raw lockfile text.

        Returns:
            tuple[Optional[int], Optional[float]]: The parsed PID and create time.
        """
        content: str = raw_text.strip()
        if not content:
            return None, None

        if ':' not in content:
            if content.isdigit():
                return int(content), None
            return None, None

        pid_text, created_text = content.split(':', 1)
        try:
            return int(pid_text), float(created_text)
        except ValueError:
            return None, None

    @staticmethod
    def _is_same_process(pid: int, create_time: Optional[float]) -> bool:
        """
        Checks whether one PID still refers to the same process instance.

        Args:
            pid (int): The process ID to inspect.
            create_time (Optional[float]): The expected process create time.

        Returns:
            bool: True if the process still exists and matches the expected lifetime.
        """
        try:
            proc = psutil.Process(pid)
            if create_time is None:
                return bool(proc.is_running())
            return bool(abs(proc.create_time() - create_time) < 0.01)
        except (psutil.Error, ValueError):
            return False

    def _unlink_if_unchanged(self, expected_stat: os.stat_result) -> bool:
        """
        Removes the lock path only if it still references the expected inode.

        Args:
            expected_stat (os.stat_result): The previously observed file stat.

        Returns:
            bool: True if the lock path was removed.
        """
        try:
            current_stat: os.stat_result = self.lock_path.stat()
        except OSError:
            return False

        if (
            current_stat.st_ino != expected_stat.st_ino
            or current_stat.st_dev != expected_stat.st_dev
        ):
            return False

        self.lock_path.unlink(missing_ok=True)
        return True

    def __enter__(self) -> 'FileLock':
        """
        Acquires an exclusive file lock. Removes stale locks if necessary
        by verifying if the owning PID is still alive.

        Args:
            None

        Raises:
            TimeoutError: If the lock cannot be acquired within the timeout period.

        Returns:
            FileLock: The current instance.
        """
        start_time: float = time.time()

        while (time.time() - start_time) < self.timeout:
            try:
                # O_CREAT | O_EXCL ensures atomic creation. Fails if the file already exists.
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                self._lock_fd = fd
                lock_payload: str = f'{self._pid}:{self._pid_create_time}'
                os.write(fd, lock_payload.encode('utf-8'))
                os.fsync(fd)
                return self
            except FileExistsError:
                # Check if the lock file is old (crashed process)
                try:
                    stat_before: os.stat_result = self.lock_path.stat()
                    if time.time() - stat_before.st_mtime > self.stale_age:
                        with self.lock_path.open('r') as f:
                            pid, create_time = self._parse_lock_metadata(f.read())

                        stat_after: os.stat_result = self.lock_path.stat()
                        if (
                            stat_after.st_ino != stat_before.st_ino
                            or stat_after.st_dev != stat_before.st_dev
                        ):
                            continue

                        if pid is not None and not self._is_same_process(
                            pid,
                            create_time,
                        ):
                            if self._unlink_if_unchanged(stat_before):
                                continue
                except (OSError, ValueError):
                    pass

            time.sleep(Constants.LOCK_SLEEP_SEC)

        raise TimeoutError(
            f'Could not acquire lock for {self.lock_path}. Another process is currently writing.'
        )

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """
        Releases the file lock by removing the lock file safely.
        Guaranteed to run even if exceptions occur inside the 'with' block.
        Verifies PID ownership before deletion to prevent race conditions.

        Args:
            exc_type (Optional[Type[BaseException]]): Exception type if raised.
            exc_val (Optional[BaseException]): Exception value if raised.
            exc_tb (Optional[TracebackType]): Traceback if raised.

        Returns:
            None
        """
        fd_stat: Optional[os.stat_result] = None
        try:
            if self._lock_fd is None:
                return

            fd_stat = os.fstat(self._lock_fd)
        except (OSError, ValueError):
            pass
        finally:
            if self._lock_fd is not None:
                try:
                    os.close(self._lock_fd)
                except OSError:
                    pass
                self._lock_fd = None

        if fd_stat is None:
            return

        try:
            self._unlink_if_unchanged(fd_stat)
        except (OSError, ValueError):
            pass
