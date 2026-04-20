"""Regression tests for cross-platform file-lock lifecycle behavior."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.utils.lock import FileLock


class LockContractTests(unittest.TestCase):
    """
    Covers file-lock regression scenarios.
    """

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
