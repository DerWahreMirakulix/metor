"""
Module providing a cross-platform file locking mechanism via a Context Manager.
Ensures that files are not concurrently modified by different processes.
"""

import os
import time
from typing import Optional, Type
from types import TracebackType


class FileLock:
    """
    A context manager for providing cross-process file locking.
    Uses an atomic OS-level file creation flag (O_CREAT | O_EXCL).
    """

    def __init__(self, target_file_path: str, timeout: float = 5.0) -> None:
        """
        Initializes the FileLock instance.

        Args:
            target_file_path (str): The absolute path to the file that needs locking.
            timeout (float): Maximum time in seconds to wait for the lock to become available.
        """
        self.lock_path: str = f'{target_file_path}.lock'
        self.timeout: float = timeout

    def __enter__(self) -> 'FileLock':
        """
        Acquires an exclusive file lock.

        Raises:
            TimeoutError: If the lock cannot be acquired within the timeout period.

        Returns:
            FileLock: The current instance.
        """
        start_time: float = time.time()

        while (time.time() - start_time) < self.timeout:
            try:
                # O_CREAT | O_EXCL ensures atomic creation. Fails if the file already exists.
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                time.sleep(0.05)

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
        Releases the file lock by removing the lock file.
        Guaranteed to run even if exceptions occur inside the 'with' block.
        """
        try:
            if os.path.exists(self.lock_path):
                os.remove(self.lock_path)
        except OSError:
            pass
