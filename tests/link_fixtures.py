"""Native alias fixtures with explicit Windows symlink capability handling."""

import os
import subprocess
import unittest
from pathlib import Path


_WINDOWS_SYMLINK_PRIVILEGE_NOT_HELD = 1314
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400


def create_directory_alias(link: Path, target: Path) -> None:
    """Create an actual directory alias on each supported test platform.

    Args:
        link (Path): New alias path.
        target (Path): Existing target directory.

    Returns:
        None

    Raises:
        OSError: If the native alias cannot be created.
    """
    if os.name != 'nt':
        link.symlink_to(target, target_is_directory=True)
        return

    result = subprocess.run(
        ['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(target)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise OSError('Windows junction fixture could not be created.')
    attributes = getattr(os.lstat(link), 'st_file_attributes', 0)
    if not attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError('Windows junction fixture is not a reparse point.')


def create_native_symlink_or_skip(
    case: unittest.TestCase,
    link: Path,
    target: Path,
    *,
    target_is_directory: bool = False,
) -> None:
    """Create a native symlink or report the precise Windows privilege gap.

    Args:
        case (unittest.TestCase): Owning test case for a visible capability skip.
        link (Path): New symbolic-link path.
        target (Path): Existing target file or directory.
        target_is_directory (bool): Whether the target is a directory.

    Returns:
        None

    Raises:
        OSError: If creation fails for a reason other than missing privilege.
    """
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as error:
        if os.name != 'nt' or getattr(error, 'winerror', None) != (
            _WINDOWS_SYMLINK_PRIVILEGE_NOT_HELD
        ):
            raise
        if any(
            os.environ.get(name, '').casefold() == 'true'
            for name in ('CI', 'GITHUB_ACTIONS')
        ):
            raise AssertionError(
                'CI must provide native Windows symbolic-link capability.'
            ) from error
        case.skipTest(
            'capability: Native Windows symlinks require Developer Mode or '
            'SeCreateSymbolicLinkPrivilege.'
        )
