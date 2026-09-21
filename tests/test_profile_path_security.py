"""Regression tests for public profile identities and internal staging paths."""

# ruff: noqa: E402

import stat
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.data.profile.manager import ProfileManager
from metor.data.profile.migration.journal import migration_paths
from metor.data.profile.models import ProfileOperationType
from metor.data.profile.support import (
    is_valid_profile_name,
    validate_profile_directory,
)
from metor.utils import Constants


class ProfilePathSecurityTests(unittest.TestCase):
    """Covers exact public names and transaction-only internal paths."""

    def test_public_profile_names_are_exact_and_unicode_aware(self) -> None:
        """Only bounded alphanumeric, dash, and underscore names are accepted.

        Args:
            None

        Returns:
            None
        """
        for name in ('default', 'Travel_2026', 'Málaga-東京', 'Ö2'):
            with self.subTest(name=name):
                self.assertTrue(is_valid_profile_name(name))

        invalid = (
            '',
            '..',
            '../outside',
            r'..\outside',
            'nested/profile',
            r'nested\profile',
            '/absolute',
            'profile.name',
            'x' * 256,
        )
        for name in invalid:
            with self.subTest(name=name):
                self.assertFalse(is_valid_profile_name(name))

    def test_profile_manager_rejects_path_names_before_external_io(self) -> None:
        """Raw path identities cannot escape or alias the configured data root.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            sandbox = Path(temp_dir)
            data_root = sandbox / 'data'
            data_root.mkdir()
            outside = sandbox / 'outside'
            outside.mkdir()
            marker = outside / 'keep.txt'
            marker.write_text('keep')
            invalid = ('../outside', str(outside), 'nested/profile', r'nested\profile')

            with patch.object(Constants, 'DATA', data_root):
                for name in invalid:
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        ProfileManager(name)

            self.assertEqual(marker.read_text(), 'keep')
            self.assertEqual(list(data_root.iterdir()), [])

    def test_public_mutation_rejects_instead_of_normalizing_identity(self) -> None:
        """Invalid input cannot silently select an existing normalized profile.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            existing = data_root / 'alpha'
            existing.mkdir()
            marker = existing / 'keep.txt'
            marker.write_text('keep')

            with patch.object(Constants, 'DATA', data_root):
                result = ProfileManager.add_profile_folder('a.lpha')

            self.assertFalse(result.success)
            self.assertEqual(result.operation_type, ProfileOperationType.INVALID_NAME)
            self.assertEqual(marker.read_text(), 'keep')

    def test_profile_directory_rejects_links_and_windows_reparse_points(self) -> None:
        """Catalog paths cannot traverse aliases outside profile ownership.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = root / 'outside'
            outside.mkdir()
            link = root / 'linked'
            link.symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, 'link'):
                validate_profile_directory(link)

        reparse_info = SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_file_attributes=0x00000400,
        )
        with (
            patch('metor.data.profile.support.os.lstat', return_value=reparse_info),
            self.assertRaisesRegex(ValueError, 'reparse'),
        ):
            validate_profile_directory(Path('simulated-reparse'))

    def test_migration_staging_manager_is_bound_to_exact_transaction_path(self) -> None:
        """Dotted staging names work only through the verified internal factory.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            source_name = 'Málaga_2'
            with patch.object(Constants, 'DATA', data_root):
                _, staged_path, _ = migration_paths(source_name)
                staged_path.mkdir()
                staged = ProfileManager.for_migration_staging(
                    source_name,
                    staged_path,
                )
                self.assertEqual(staged.paths.get_config_dir(), staged_path)
                self.assertEqual(staged.profile_name, staged_path.name)

                with self.assertRaises(ValueError):
                    ProfileManager.for_migration_staging(
                        source_name,
                        data_root / '.different.staged',
                    )


if __name__ == '__main__':
    unittest.main()
