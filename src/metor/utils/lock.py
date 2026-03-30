"""
Module providing a cross-platform file locking mechanism via a Context Manager.
Ensures that files are not concurrently modified by different processes.
"""

import os
import time
from typing import Optional, Type
from types import TracebackType
from pathlib import Path


class FileLock:
    """
    A context manager for providing cross-process file locking.
    Uses an atomic OS-level file creation flag. Cleans up stale ghost locks
    by validating the stored Process ID (PID).
    """

    def __init__(
        self,
        target_file_path: str | Path,
        timeout: float = 5.0,
        stale_age: float = 10.0,
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
        import psutil  # Local import to prevent cyclic top-level load

        start_time: float = time.time()

        while (time.time() - start_time) < self.timeout:
            try:
                # O_CREAT | O_EXCL ensures atomic creation. Fails if the file already exists.
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, 'w') as f:
                    f.write(str(self._pid))
                return self
            except FileExistsError:
                # Check if the lock file is old (crashed process)
                try:
                    if time.time() - self.lock_path.stat().st_mtime > self.stale_age:
                        with self.lock_path.open('r') as f:
                            pid_str: str = f.read().strip()

                        if pid_str.isdigit() and not psutil.pid_exists(int(pid_str)):
                            self.lock_path.unlink(missing_ok=True)
                            continue  # Try acquiring again immediately
                except (OSError, ValueError):
                    pass

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
        try:
            with self.lock_path.open('r') as f:
                pid_str: str = f.read().strip()
            if pid_str == str(self._pid):
                self.lock_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
