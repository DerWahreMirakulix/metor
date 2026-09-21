"""
Module handling OPSEC and security-critical file operations.
Mitigates Data-At-Rest risks via cryptographic file shredding.
"""

import ctypes
import errno
import os
import secrets
import stat
from pathlib import Path

from metor.shared.security import secure_clear_buffer as secure_clear_buffer

# Local Package Imports
from metor.utils.constants import Constants


_WINDOWS_GENERIC_READ: int = 0x80000000
_WINDOWS_GENERIC_WRITE: int = 0x40000000
_WINDOWS_FILE_SHARE_READ: int = 0x00000001
_WINDOWS_FILE_SHARE_WRITE: int = 0x00000002
_WINDOWS_FILE_SHARE_DELETE: int = 0x00000004
_WINDOWS_OPEN_EXISTING: int = 3
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT: int = 0x00200000
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT: int = 0x00000400
_WINDOWS_FILE_ATTRIBUTE_TAG_INFO_CLASS: int = 9
_WINDOWS_INVALID_HANDLE_VALUE: int = ctypes.c_void_p(-1).value or -1


class _WindowsFileAttributeTagInfo(ctypes.Structure):
    """Carries Windows attributes for the exact opened filesystem handle."""

    _fields_ = [
        ('file_attributes', ctypes.c_ulong),
        ('reparse_tag', ctypes.c_ulong),
    ]


def _open_windows_file(file_path: Path) -> int | None:
    """Opens one Windows path without traversing a reparse point.

    Args:
        file_path (Path): Candidate sensitive file.

    Returns:
        int | None: Owned file descriptor, or None when the path is absent.

    Raises:
        OSError: If the path cannot be opened safely or is a reparse point.
    """
    import msvcrt  # Windows-only descriptor conversion is unavailable on POSIX.

    win_dll = getattr(ctypes, 'WinDLL')
    get_last_error = getattr(ctypes, 'get_last_error')
    kernel32 = win_dll('kernel32', use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int
    get_attributes = kernel32.GetFileInformationByHandleEx
    get_attributes.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
    )
    get_attributes.restype = ctypes.c_int

    handle = create_file(
        str(file_path),
        _WINDOWS_GENERIC_READ | _WINDOWS_GENERIC_WRITE,
        _WINDOWS_FILE_SHARE_READ
        | _WINDOWS_FILE_SHARE_WRITE
        | _WINDOWS_FILE_SHARE_DELETE,
        None,
        _WINDOWS_OPEN_EXISTING,
        _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == _WINDOWS_INVALID_HANDLE_VALUE:
        error_code = get_last_error()
        if error_code in (2, 3):
            return None
        raise OSError(
            error_code, 'Sensitive file could not be opened safely.', file_path
        )

    attributes = _WindowsFileAttributeTagInfo()
    if not get_attributes(
        handle,
        _WINDOWS_FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(attributes),
        ctypes.sizeof(attributes),
    ):
        error_code = get_last_error()
        close_handle(handle)
        raise OSError(error_code, 'Sensitive file attributes could not be read.')
    if attributes.file_attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT:
        close_handle(handle)
        raise OSError(errno.ELOOP, 'Refusing to shred a Windows reparse point.')

    try:
        open_osfhandle = getattr(msvcrt, 'open_osfhandle')
        binary_flag = getattr(os, 'O_BINARY', 0)
        return int(open_osfhandle(int(handle), os.O_RDWR | binary_flag))
    except Exception:
        close_handle(handle)
        raise


def _open_sensitive_file(file_path: Path) -> int | None:
    """Opens a sensitive path without following a direct link.

    Args:
        file_path (Path): Candidate file path.

    Returns:
        int | None: Owned descriptor, or None when the path is absent.

    Raises:
        OSError: If safe no-follow opening is unavailable or fails.
    """
    if os.name == 'nt':
        return _open_windows_file(file_path)

    no_follow = getattr(os, 'O_NOFOLLOW', None)
    if no_follow is None:
        raise OSError(errno.ENOTSUP, 'No-follow file opening is unavailable.')
    flags = os.O_RDWR | no_follow | getattr(os, 'O_CLOEXEC', 0)
    try:
        return os.open(file_path, flags)
    except FileNotFoundError:
        return None


def secure_shred_file(file_path: Path) -> None:
    """
    Securely overwrites a file with cryptographic random bytes before deleting it.
    Note: File shredding may be ineffective on modern SSDs due to wear-leveling.

    Args:
        file_path (Path): The path to the file to be shredded.

    Returns:
        None

    Raises:
        OSError: If the file cannot be safely validated, overwritten, synced, or
            removed.
    """
    descriptor = _open_sensitive_file(file_path)
    if descriptor is None:
        return

    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(errno.EINVAL, 'Refusing to shred a non-regular file.')
        if opened.st_nlink != 1:
            raise OSError(errno.EMLINK, 'Refusing to shred a multiply linked file.')

        remaining = opened.st_size
        while remaining > 0:
            block_size = min(remaining, Constants.SECURE_SHRED_BLOCK_BYTES)
            block = memoryview(secrets.token_bytes(block_size))
            written = 0
            while written < block_size:
                count = os.write(descriptor, block[written:])
                if count <= 0:
                    raise OSError(
                        errno.EIO, 'Sensitive file overwrite made no progress.'
                    )
                written += count
            remaining -= block_size
        os.fsync(descriptor)

        current = os.stat(file_path, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError(errno.ESTALE, 'Sensitive file path changed during cleanup.')
        os.unlink(file_path)
    finally:
        os.close(descriptor)


def secure_remove_path(path: Path) -> None:
    """
    Recursively removes one filesystem path while shredding regular files first.

    Args:
        path (Path): The filesystem path to remove.

    Returns:
        None

    Raises:
        OSError: If a path cannot be safely classified, traversed, shredded, or
            removed.
    """
    try:
        path_info = os.lstat(path)
    except FileNotFoundError:
        return

    if stat.S_ISLNK(path_info.st_mode):
        os.unlink(path)
        return

    file_attributes = getattr(path_info, 'st_file_attributes', 0)
    if file_attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT:
        raise OSError(errno.ELOOP, 'Refusing to traverse a Windows reparse point.')

    if stat.S_ISREG(path_info.st_mode):
        secure_shred_file(path)
        return

    if not stat.S_ISDIR(path_info.st_mode):
        raise OSError(errno.EINVAL, 'Refusing to remove an unsupported file type.')

    for child in path.iterdir():
        secure_remove_path(child)

    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR, follow_symlinks=False)
    os.rmdir(path)
