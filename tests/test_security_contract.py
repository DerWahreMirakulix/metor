"""Regression tests for security-critical local file destruction helpers."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.utils.security import secure_remove_path, secure_shred_file


class SecurityContractTests(unittest.TestCase):
    """
    Covers security contract regression scenarios.
    """

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

            with patch.object(Path, 'open', side_effect=OSError('denied')):
                with self.assertRaises(OSError):
                    secure_shred_file(file_path)

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


if __name__ == '__main__':
    unittest.main()
