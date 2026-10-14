"""Copies an offline profile into a freshly owned private migration generation."""

import errno
import os
import shutil
import stat
from pathlib import Path

from metor.utils import create_private_directory_tree, open_private_binary_file


def copy_private_profile_tree(source: Path, target: Path) -> None:
    """Copies regular profile content without inheriting default Windows owners.

    The caller holds the profile lifecycle and migration locks. Each destination
    directory and file is created through the common private-storage boundary;
    ordinary copytree creation can assign an elevated token's group as owner.
    Links, reparse points and special objects cannot become a staged generation.

    Args:
        source (Path): Offline profile directory owned by the transaction.
        target (Path): Fresh sibling generation to populate.

    Returns:
        None

    Raises:
        OSError: If a source entry is unsafe or copying private storage fails.
    """
    source_info = source.lstat()
    _reject_link(source_info)
    if not stat.S_ISDIR(source_info.st_mode):
        raise OSError(errno.ENOTDIR, 'Profile generation must be a directory.')
    create_private_directory_tree(target, ())
    for entry in source.iterdir():
        entry_info = entry.lstat()
        _reject_link(entry_info)
        destination = target / entry.name
        if stat.S_ISDIR(entry_info.st_mode):
            copy_private_profile_tree(entry, destination)
        elif stat.S_ISREG(entry_info.st_mode) and entry_info.st_nlink == 1:
            _copy_private_file(entry, destination, entry_info)
        else:
            raise OSError(errno.EINVAL, 'Profile generation contains an unsafe entry.')


def _reject_link(info: os.stat_result) -> None:
    """Rejects symbolic links and Windows reparse points before traversal.

    Args:
        info (os.stat_result): Non-following filesystem entry metadata.

    Returns:
        None
    """
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(
        stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0
    ):
        raise OSError(errno.ELOOP, 'Profile migration cannot copy links.')


def _copy_private_file(source: Path, target: Path, expected: os.stat_result) -> None:
    """Streams one verified regular source into a freshly private output file.

    Args:
        source (Path): Source regular file checked without following links.
        target (Path): Destination within the private staged generation.
        expected (os.stat_result): Identity checked before opening the source.

    Returns:
        None
    """
    flags = (
        os.O_RDONLY
        | getattr(os, 'O_BINARY', 0)
        | getattr(os, 'O_CLOEXEC', 0)
        | getattr(os, 'O_NOFOLLOW', 0)
        | getattr(os, 'O_NONBLOCK', 0)
    )
    descriptor = os.open(source, flags)
    with os.fdopen(descriptor, 'rb') as incoming:
        opened = os.fstat(incoming.fileno())
        _reject_link(opened)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino)
        ):
            raise OSError(
                errno.ESTALE, 'Profile migration source changed while opening.'
            )
        with open_private_binary_file(target) as outgoing:
            shutil.copyfileobj(incoming, outgoing)
