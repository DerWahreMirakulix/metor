"""
Module providing a cross-platform file locking mechanism via a Context Manager.
Ensures that files are not concurrently modified by different processes.
"""

import errno
import math
import os
import stat
import time
from pathlib import Path
from types import TracebackType
from typing import Callable, Optional, Type, cast

import psutil

# Local Package Imports
from metor.utils.constants import Constants
from metor.utils.security import _WINDOWS_OPEN_ALWAYS, _open_windows_file


def _current_posix_uid() -> int:
    """Returns the current POSIX user identity without Windows-only typing drift.

    Args:
        None

    Returns:
        int: Current effective process owner used for lock-file validation.

    Raises:
        OSError: If the running platform does not expose a POSIX user identity.
    """
    get_uid = getattr(os, 'getuid', None)
    if get_uid is None:
        raise OSError(errno.ENOTSUP, 'POSIX owner validation is unavailable.')
    return int(get_uid())


def _set_private_descriptor_mode(descriptor: int) -> None:
    """Applies owner-only POSIX permissions to an already opened descriptor.

    Args:
        descriptor (int): Exact lock descriptor to protect.

    Returns:
        None

    Raises:
        OSError: If descriptor-bound permission changes are unavailable or fail.
    """
    change_mode = getattr(os, 'fchmod', None)
    if change_mode is None:
        raise OSError(errno.ENOTSUP, 'Descriptor permission changes are unavailable.')
    change_mode(descriptor, 0o600)


def _try_lock_descriptor(descriptor: int) -> bool:
    """Attempts one nonblocking exclusive operating-system file lock.

    Args:
        descriptor (int): Stable lock-object descriptor.

    Returns:
        bool: True when the exclusive lock was acquired, otherwise False.

    Raises:
        OSError: If the native lock operation fails for another reason.
    """
    if os.name == 'nt':
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        locking = cast(Callable[[int, int, int], None], getattr(msvcrt, 'locking'))
        nonblocking_mode = int(getattr(msvcrt, 'LK_NBLCK'))
        try:
            locking(descriptor, nonblocking_mode, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            raise
        return True

    import fcntl

    flock = cast(Callable[[int, int], None], getattr(fcntl, 'flock'))
    exclusive = int(getattr(fcntl, 'LOCK_EX'))
    nonblocking = int(getattr(fcntl, 'LOCK_NB'))
    try:
        flock(descriptor, exclusive | nonblocking)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return False
        raise
    return True


def _unlock_descriptor(descriptor: int) -> None:
    """Releases one descriptor's native exclusive lock.

    Args:
        descriptor (int): Owned locked descriptor.

    Returns:
        None

    Raises:
        OSError: If the native unlock operation fails.
    """
    if os.name == 'nt':
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        locking = cast(Callable[[int, int, int], None], getattr(msvcrt, 'locking'))
        unlock_mode = int(getattr(msvcrt, 'LK_UNLCK'))
        locking(descriptor, unlock_mode, 1)
        return

    import fcntl

    flock = cast(Callable[[int, int], None], getattr(fcntl, 'flock'))
    unlock = int(getattr(fcntl, 'LOCK_UN'))
    flock(descriptor, unlock)


class FileLock:
    """
    A context manager for providing cross-process file locking.
    Uses one persistent private lock object and an OS-level exclusive lock.
    Process exit releases ownership without renaming or unlinking that object.
    """

    def __init__(
        self,
        target_file_path: str | Path,
        timeout: float = Constants.FILE_LOCK_TIMEOUT_SEC,
    ) -> None:
        """
        Initializes the FileLock instance.

        Args:
            target_file_path (str | Path): The absolute path to the file that needs locking.
            timeout (float): Maximum time in seconds to wait for the lock to become available.

        Returns:
            None
        """
        self.lock_path: Path = Path(f'{target_file_path}.lock')
        self.timeout: float = timeout
        self._pid: int = os.getpid()
        self._pid_create_time: float = psutil.Process(self._pid).create_time()
        if not math.isfinite(self._pid_create_time) or self._pid_create_time <= 0:
            raise RuntimeError('Current process lifetime is unavailable.')
        self._lock_fd: Optional[int] = None

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

    def _open_lock_descriptor(self) -> int:
        """Opens or creates the stable private lock object without link traversal.

        Args:
            None

        Returns:
            int: Owned descriptor for the persistent lock object.

        Raises:
            OSError: If the object is unsafe or cannot be opened.
        """
        if os.name == 'nt':
            descriptor = _open_windows_file(
                self.lock_path,
                _WINDOWS_OPEN_ALWAYS,
                share_delete=False,
            )
            if descriptor is None:
                raise FileNotFoundError(self.lock_path)
            return descriptor

        no_follow = getattr(os, 'O_NOFOLLOW', None)
        if no_follow is None:
            raise OSError(errno.ENOTSUP, 'No-follow lock opening is unavailable.')
        return os.open(
            self.lock_path,
            os.O_RDWR
            | os.O_CREAT
            | no_follow
            | int(getattr(os, 'O_CLOEXEC', 0))
            | int(getattr(os, 'O_NONBLOCK', 0)),
            0o600,
        )

    def _validate_lock_descriptor(self, descriptor: int) -> os.stat_result:
        """Validates type, ownership, permissions, and bounded metadata size.

        Args:
            descriptor (int): Exact opened lock descriptor.

        Returns:
            os.stat_result: Stable identity of the validated lock object.

        Raises:
            OSError: If the object is linked, unsafe, or outside resource limits.
        """
        opened = os.fstat(descriptor)
        file_attributes = int(getattr(opened, 'st_file_attributes', 0))
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(errno.EINVAL, 'Lock object is not a regular file.')
        if opened.st_nlink != 1:
            raise OSError(errno.EMLINK, 'Lock object has multiple links.')
        if file_attributes & 0x00000400:
            raise OSError(errno.ELOOP, 'Lock object is a reparse point.')
        if opened.st_size > Constants.FILE_LOCK_METADATA_MAX_BYTES:
            raise OSError(errno.EFBIG, 'Lock metadata exceeds its bounded size.')
        if os.name != 'nt':
            if opened.st_uid != _current_posix_uid():
                raise OSError(errno.EPERM, 'Lock object belongs to another user.')
            _set_private_descriptor_mode(descriptor)
        return os.fstat(descriptor)

    def _validate_path_identity(
        self,
        opened: os.stat_result,
    ) -> None:
        """Requires the canonical name to retain the exact opened lock object.

        Args:
            opened (os.stat_result): Identity of the locked descriptor.

        Returns:
            None

        Raises:
            OSError: If the path was replaced during acquisition.
        """
        current = self.lock_path.lstat()
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError(errno.ESTALE, 'Lock object changed during acquisition.')

    def _write_metadata(self, descriptor: int) -> None:
        """Replaces bounded informational owner metadata under the native lock.

        Args:
            descriptor (int): Exclusively locked stable descriptor.

        Returns:
            None

        Raises:
            OSError: If bounded metadata persistence fails.
        """
        payload = f'{self._pid}:{self._pid_create_time}'.encode('utf-8')
        if len(payload) > Constants.FILE_LOCK_METADATA_MAX_BYTES:
            raise OSError(errno.EFBIG, 'Lock metadata exceeds its bounded size.')
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        self._write_all(descriptor, payload)
        os.fsync(descriptor)

    def _release_owned_lock(self) -> None:
        """Releases this instance's OS lock and closes its owned descriptor.

        Args:
            None

        Returns:
            None

        Raises:
            OSError: If native unlock or descriptor close fails.
        """
        if self._lock_fd is None:
            return

        descriptor = self._lock_fd
        self._lock_fd = None
        unlock_error: Optional[BaseException] = None
        try:
            _unlock_descriptor(descriptor)
        except BaseException as exc:
            unlock_error = exc
        try:
            os.close(descriptor)
        except BaseException as close_error:
            if unlock_error is not None:
                raise close_error from unlock_error
            raise
        if unlock_error is not None:
            raise unlock_error

    def __enter__(self) -> 'FileLock':
        """
        Acquires the stable lock object's exclusive operating-system lock.

        Args:
            None

        Raises:
            TimeoutError: If the lock cannot be acquired within the timeout period.

        Returns:
            FileLock: The current instance.
        """
        start_time: float = time.monotonic()

        while (time.monotonic() - start_time) < self.timeout:
            descriptor: Optional[int] = None
            try:
                descriptor = self._open_lock_descriptor()
                opened = self._validate_lock_descriptor(descriptor)
                if not _try_lock_descriptor(descriptor):
                    waiting_descriptor = descriptor
                    descriptor = None
                    os.close(waiting_descriptor)
                    time.sleep(Constants.LOCK_SLEEP_SEC)
                    continue
                locked_descriptor = descriptor
                self._lock_fd = locked_descriptor
                descriptor = None
                try:
                    self._validate_path_identity(opened)
                    self._write_metadata(locked_descriptor)
                except BaseException as acquisition_error:
                    try:
                        self._release_owned_lock()
                    except BaseException as cleanup_error:
                        raise cleanup_error from acquisition_error
                    raise
                return self
            except BaseException as acquisition_error:
                if descriptor is None:
                    raise
                failed_descriptor = descriptor
                descriptor = None
                try:
                    os.close(failed_descriptor)
                except BaseException as close_error:
                    raise close_error from acquisition_error
                raise

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
        Releases the descriptor's OS lock while retaining the stable lock object.
        Guaranteed to run even if exceptions occur inside the with block.

        Args:
            exc_type (Optional[Type[BaseException]]): Exception type if raised.
            exc_val (Optional[BaseException]): Exception value if raised.
            exc_tb (Optional[TracebackType]): Traceback if raised.

        Returns:
            None
        """
        self._release_owned_lock()
