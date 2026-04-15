"""
Module handling OPSEC and security-critical file operations.
Mitigates Data-At-Rest risks via cryptographic file shredding.
"""

import os
import stat
import secrets
from pathlib import Path


def secure_clear_buffer(buffer: bytearray | memoryview) -> None:
    """
    Overwrites one mutable in-memory buffer with zero bytes in place.

    Args:
        buffer (bytearray | memoryview): The mutable buffer to clear.

    Returns:
        None
    """
    view: memoryview = buffer if isinstance(buffer, memoryview) else memoryview(buffer)
    view.cast('B')[:] = b'\x00' * len(view)


def secure_shred_file(file_path: Path) -> None:
    """
    Securely overwrites a file with cryptographic random bytes before deleting it.
    Note: File shredding may be ineffective on modern SSDs due to wear-leveling.

    Args:
        file_path (Path): The path to the file to be shredded.

    Returns:
        None
    """
    if not file_path.exists() or not file_path.is_file():
        return

    # Ensure the owner can both read and overwrite the file before shredding it.
    file_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    length: int = file_path.stat().st_size

    if length > 0:
        with file_path.open('r+b', buffering=0) as handle:
            handle.write(secrets.token_bytes(length))
            handle.flush()
            os.fsync(handle.fileno())

    file_path.unlink()


def secure_remove_path(path: Path) -> None:
    """
    Recursively removes one filesystem path while shredding regular files first.

    Args:
        path (Path): The filesystem path to remove.

    Returns:
        None
    """
    if not path.exists() and not path.is_symlink():
        return

    if path.is_symlink():
        path.unlink()
        return

    if path.is_file():
        secure_shred_file(path)
        return

    for child in path.iterdir():
        secure_remove_path(child)

    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    path.rmdir()
