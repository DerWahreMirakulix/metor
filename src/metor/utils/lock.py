"""
Module providing a cross-platform file locking mechanism via a Context Manager.
Ensures that files are not concurrently modified by different processes.
"""

import errno
import math
import os
import secrets
import stat
import time
import psutil
from typing import Optional, Type
from types import TracebackType
from pathlib import Path

# Local Package Imports
from metor.utils.constants import Constants
from metor.utils.security import _open_windows_file


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
            return None, None

        pid_text, created_text = content.split(':', 1)
        try:
            pid = int(pid_text)
            create_time = float(created_text)
            if pid <= 0 or not math.isfinite(create_time) or create_time <= 0:
                return None, None
            return pid, create_time
        except ValueError:
            return None, None

    @staticmethod
    def _is_same_process(
        pid: int,
        create_time: Optional[float],
    ) -> Optional[bool]:
        """
        Checks whether one PID still refers to the same process instance.

        Args:
            pid (int): The process ID to inspect.
            create_time (Optional[float]): The expected process create time.

        Returns:
            Optional[bool]: True for the same process, False for a definite stale
                owner, or None when ownership cannot be established safely.
        """
        if (
            pid <= 0
            or create_time is None
            or not math.isfinite(create_time)
            or create_time <= 0
        ):
            return None

        try:
            proc = psutil.Process(pid)
            if not proc.is_running():
                return False
            observed_create_time = float(proc.create_time())
            if not math.isfinite(observed_create_time) or observed_create_time <= 0:
                return None
            return bool(
                abs(observed_create_time - create_time)
                < Constants.PROCESS_CREATE_TIME_TOLERANCE_SEC
            )
        except psutil.NoSuchProcess:
            return False
        except (psutil.AccessDenied, psutil.Error, ValueError):
            return None

    @staticmethod
    def _write_all(descriptor: int, payload: bytes) -> None:
        """Writes one complete lock metadata payload.

        Args:
            descriptor (int): Owned lock descriptor.
            payload (bytes): Metadata bytes to persist.

        Returns:
            None

        Raises:
            OSError: If writing fails or makes no progress.
        """
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError(errno.EIO, 'Lock metadata write made no progress.')
            remaining = remaining[written:]

    def _read_lock_metadata(
        self,
    ) -> tuple[Optional[int], Optional[float], Optional[os.stat_result]]:
        """Reads bounded metadata and identity from one safe regular descriptor.

        Args:
            None

        Returns:
            tuple[Optional[int], Optional[float], Optional[os.stat_result]]: Parsed owner metadata and exact opened-file identity, or unknown values.
        """
        descriptor: Optional[int] = None
        try:
            if os.name == 'nt':
                descriptor = _open_windows_file(self.lock_path)
                if descriptor is None:
                    return None, None, None
            else:
                no_follow = getattr(os, 'O_NOFOLLOW', None)
                if no_follow is None:
                    return None, None, None
                descriptor = os.open(
                    self.lock_path,
                    os.O_RDONLY
                    | no_follow
                    | int(getattr(os, 'O_CLOEXEC', 0))
                    | int(getattr(os, 'O_NONBLOCK', 0)),
                )
            opened = os.fstat(descriptor)
            file_attributes: int = int(getattr(opened, 'st_file_attributes', 0))
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or file_attributes & 0x00000400
                or opened.st_size > Constants.FILE_LOCK_METADATA_MAX_BYTES
            ):
                return None, None, opened
            if os.name != 'nt' and (
                opened.st_uid != os.getuid() or opened.st_mode & 0o077
            ):
                return None, None, opened
            raw_payload = os.read(
                descriptor,
                Constants.FILE_LOCK_METADATA_MAX_BYTES + 1,
            )
            if len(raw_payload) > Constants.FILE_LOCK_METADATA_MAX_BYTES:
                return None, None, opened
            try:
                raw_text = raw_payload.decode('utf-8')
            except UnicodeError:
                return None, None, opened
            pid, create_time = self._parse_lock_metadata(raw_text)
            return pid, create_time, opened
        except OSError:
            return None, None, None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _unlink_if_unchanged(self, expected_stat: os.stat_result) -> bool:
        """
        Removes the lock path only if it still references the expected inode.

        Args:
            expected_stat (os.stat_result): The previously observed file stat.

        Returns:
            bool: True if the lock path was removed.
        """
        try:
            current_stat: os.stat_result = self.lock_path.lstat()
            if (
                current_stat.st_ino != expected_stat.st_ino
                or current_stat.st_dev != expected_stat.st_dev
            ):
                return False

            quarantine = self.lock_path.with_name(
                f'.{self.lock_path.name}.remove-{secrets.token_hex(16)}'
            )
            self.lock_path.rename(quarantine)
            quarantined_stat = quarantine.lstat()
            if (
                quarantined_stat.st_ino != expected_stat.st_ino
                or quarantined_stat.st_dev != expected_stat.st_dev
            ):
                if not self.lock_path.exists():
                    quarantine.rename(self.lock_path)
                return False
            quarantine.unlink()
            return True
        except OSError:
            return False

    def _release_owned_lock(self) -> None:
        """Closes and removes only this instance's confirmed lock file.

        Args:
            None

        Returns:
            None

        Raises:
            OSError: If descriptor inspection, close, or removal fails.
        """
        if self._lock_fd is None:
            return

        descriptor = self._lock_fd
        try:
            fd_stat = os.fstat(descriptor)
        except OSError:
            self._lock_fd = None
            os.close(descriptor)
            raise

        self._lock_fd = None
        os.close(descriptor)
        self._unlink_if_unchanged(fd_stat)

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
        start_time: float = time.monotonic()

        while (time.monotonic() - start_time) < self.timeout:
            try:
                # O_CREAT | O_EXCL ensures atomic creation. Fails if the file already exists.
                fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                self._lock_fd = fd
                try:
                    if os.name != 'nt':
                        os.fchmod(fd, 0o600)
                    lock_payload: str = f'{self._pid}:{self._pid_create_time}'
                    self._write_all(fd, lock_payload.encode('utf-8'))
                    os.fsync(fd)
                except BaseException as acquisition_error:
                    try:
                        self._release_owned_lock()
                    except BaseException as cleanup_error:
                        raise cleanup_error from acquisition_error
                    raise
                return self
            except FileExistsError:
                # Check if the lock file is old (crashed process)
                try:
                    stat_before: os.stat_result = self.lock_path.lstat()
                    lock_age = time.time() - stat_before.st_mtime
                    if math.isfinite(lock_age) and lock_age > self.stale_age:
                        pid, create_time, opened_stat = self._read_lock_metadata()
                        if (
                            opened_stat is not None
                            and opened_stat.st_ino == stat_before.st_ino
                            and opened_stat.st_dev == stat_before.st_dev
                            and pid is not None
                            and self._is_same_process(pid, create_time) is False
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
        self._release_owned_lock()
