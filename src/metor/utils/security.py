"""
Module handling OPSEC and security-critical file operations.
Mitigates Data-At-Rest risks via cryptographic file shredding.
"""

import ctypes
import errno
import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, cast

from metor.shared.security import secure_clear_buffer as secure_clear_buffer

# Local Package Imports
from metor.utils.constants import Constants


_WINDOWS_GENERIC_READ: int = 0x80000000
_WINDOWS_GENERIC_WRITE: int = 0x40000000
_WINDOWS_FILE_SHARE_READ: int = 0x00000001
_WINDOWS_FILE_SHARE_WRITE: int = 0x00000002
_WINDOWS_FILE_SHARE_DELETE: int = 0x00000004
_WINDOWS_OPEN_EXISTING: int = 3
_WINDOWS_OPEN_ALWAYS: int = 4
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT: int = 0x00200000
_WINDOWS_FILE_FLAG_BACKUP_SEMANTICS: int = 0x02000000
_WINDOWS_FILE_ATTRIBUTE_DIRECTORY: int = 0x00000010
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT: int = 0x00000400
_WINDOWS_FILE_ATTRIBUTE_TAG_INFO_CLASS: int = 9
_WINDOWS_INVALID_HANDLE_VALUE: int = ctypes.c_void_p(-1).value or -1


def _set_descriptor_mode(descriptor: int, mode: int) -> None:
    """Applies POSIX mode bits without assuming Windows exports fchmod."""
    change_mode = getattr(os, 'fchmod', None)
    if change_mode is None:
        raise OSError(errno.ENOTSUP, 'Descriptor permission changes are unavailable.')
    change_mode(descriptor, mode)


class _WindowsFileAttributeTagInfo(ctypes.Structure):
    """Carries Windows attributes for the exact opened filesystem handle."""

    _fields_ = [
        ('file_attributes', ctypes.c_ulong),
        ('reparse_tag', ctypes.c_ulong),
    ]


def _open_windows_directory_handle(
    directory_path: Path,
) -> tuple[object, Callable[[object], int]]:
    """Opens and locks one Windows directory against rename and reparse traversal.

    Args:
        directory_path (Path): Directory to lock for an anchored operation.

    Returns:
        tuple[object, Callable[[object], int]]: Native handle and configured CloseHandle callable.

    Raises:
        OSError: If the directory is missing, reparsed, or cannot be locked.
    """
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
        str(directory_path),
        _WINDOWS_GENERIC_READ,
        _WINDOWS_FILE_SHARE_READ | _WINDOWS_FILE_SHARE_WRITE,
        None,
        _WINDOWS_OPEN_EXISTING,
        _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT | _WINDOWS_FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle == _WINDOWS_INVALID_HANDLE_VALUE:
        error_code = get_last_error()
        raise OSError(
            error_code,
            'Directory could not be opened without rename sharing.',
            directory_path,
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
        raise OSError(error_code, 'Directory attributes could not be read.')
    if attributes.file_attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT:
        close_handle(handle)
        raise OSError(errno.ELOOP, 'Refusing a Windows directory reparse point.')
    if not attributes.file_attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY:
        close_handle(handle)
        raise OSError(errno.ENOTDIR, 'Expected a Windows directory.')
    return handle, cast(Callable[[object], int], close_handle)


def _open_windows_file(
    file_path: Path,
    creation_disposition: int = _WINDOWS_OPEN_EXISTING,
    *,
    share_delete: bool = True,
) -> int | None:
    """Opens one Windows path without traversing a reparse point.

    Args:
        file_path (Path): Candidate sensitive file.
        creation_disposition (int): Native create/open disposition.
        share_delete (bool): Whether another process may rename/delete the path while this handle is open.

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

    share_mode = _WINDOWS_FILE_SHARE_READ | _WINDOWS_FILE_SHARE_WRITE
    if share_delete:
        share_mode |= _WINDOWS_FILE_SHARE_DELETE
    handle = create_file(
        str(file_path),
        _WINDOWS_GENERIC_READ | _WINDOWS_GENERIC_WRITE,
        share_mode,
        None,
        creation_disposition,
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


def _directory_open_flags() -> int:
    """Returns flags for a non-following directory descriptor.

    Args:
        None

    Returns:
        int: Platform-supported directory open flags.
    """
    no_follow: int | None = getattr(os, 'O_NOFOLLOW', None)
    directory: int | None = getattr(os, 'O_DIRECTORY', None)
    if no_follow is None or directory is None:
        raise OSError(errno.ENOTSUP, 'Anchored directory opening is unavailable.')
    return os.O_RDONLY | no_follow | directory | int(getattr(os, 'O_CLOEXEC', 0))


@contextmanager
def _open_anchored_parent(path: Path) -> Iterator[tuple[int, str]]:
    """Opens every POSIX parent component without following links.

    Args:
        path (Path): Leaf path whose stable parent is required.

    Yields:
        tuple[int, str]: Owned parent descriptor and exact leaf name.

    Raises:
        OSError: If a parent is missing, linked, or not a directory.

    Returns:
        None
    """
    absolute = path if path.is_absolute() else Path.cwd() / path
    if absolute.name in ('', '.', '..'):
        raise OSError(errno.EINVAL, 'A removable leaf path is required.')
    parent_parts = absolute.parent.parts
    if not parent_parts:
        raise OSError(errno.EINVAL, 'A filesystem parent is required.')

    flags = _directory_open_flags()
    descriptor = os.open(absolute.anchor or '.', flags)
    try:
        start_index = 1 if absolute.anchor else 0
        for component in parent_parts[start_index:]:
            if component in ('', '.'):
                continue
            if component == '..':
                raise OSError(errno.EINVAL, 'Parent traversal is not allowed.')
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        yield descriptor, absolute.name
    finally:
        os.close(descriptor)


def _same_entry(parent_descriptor: int, name: str, opened: os.stat_result) -> bool:
    """Checks that one anchored directory entry still names an opened object.

    Args:
        parent_descriptor (int): Stable parent directory descriptor.
        name (str): Direct child name.
        opened (os.stat_result): Metadata from the opened object.

    Returns:
        bool: Whether device and inode identity remain unchanged.
    """
    current = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    return (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino)


def _secure_shred_entry(parent_descriptor: int, name: str) -> None:
    """Shreds one regular file relative to a stable parent descriptor.

    Args:
        parent_descriptor (int): Stable parent directory descriptor.
        name (str): Direct child name.

    Returns:
        None

    Raises:
        OSError: If the entry is unsafe, changes identity, or cannot be removed.
    """
    no_follow = getattr(os, 'O_NOFOLLOW', None)
    if no_follow is None:
        raise OSError(errno.ENOTSUP, 'No-follow file opening is unavailable.')
    flags = os.O_RDWR | no_follow | getattr(os, 'O_CLOEXEC', 0)
    descriptor = os.open(name, flags, dir_fd=parent_descriptor)
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

        if not _same_entry(parent_descriptor, name, opened):
            raise OSError(errno.ESTALE, 'Sensitive file path changed during cleanup.')
        os.unlink(name, dir_fd=parent_descriptor)
    finally:
        os.close(descriptor)


def _secure_remove_entry(parent_descriptor: int, name: str) -> None:
    """Recursively removes one direct child of an anchored directory.

    Args:
        parent_descriptor (int): Stable parent directory descriptor.
        name (str): Direct child name.

    Returns:
        None

    Raises:
        OSError: If classification, traversal, shredding, or removal is unsafe.
    """
    try:
        path_info = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return

    if stat.S_ISLNK(path_info.st_mode):
        os.unlink(name, dir_fd=parent_descriptor)
        return
    if stat.S_ISREG(path_info.st_mode):
        _secure_shred_entry(parent_descriptor, name)
        return
    if not stat.S_ISDIR(path_info.st_mode):
        raise OSError(errno.EINVAL, 'Refusing to remove an unsupported file type.')

    directory_descriptor = os.open(
        name,
        _directory_open_flags(),
        dir_fd=parent_descriptor,
    )
    try:
        opened = os.fstat(directory_descriptor)
        if (opened.st_dev, opened.st_ino) != (path_info.st_dev, path_info.st_ino):
            raise OSError(errno.ESTALE, 'Directory path changed during cleanup.')
        for child_name in os.listdir(directory_descriptor):
            _secure_remove_entry(directory_descriptor, child_name)
        _set_descriptor_mode(
            directory_descriptor,
            stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR,
        )
        if not _same_entry(parent_descriptor, name, opened):
            raise OSError(errno.ESTALE, 'Directory path changed during cleanup.')
    finally:
        os.close(directory_descriptor)
    os.rmdir(name, dir_fd=parent_descriptor)


def _open_or_create_private_directory(
    parent_descriptor: int,
    name: str,
) -> int:
    """Creates or opens one private child directory relative to its parent.

    Args:
        parent_descriptor (int): Stable parent directory descriptor.
        name (str): Exact direct child name.

    Returns:
        int: Owned descriptor for the validated child directory.

    Raises:
        OSError: If the child is linked, changes identity, or is not a directory.
    """
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
    except FileExistsError:
        pass
    descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_descriptor)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise OSError(errno.ENOTDIR, 'Private path is not a directory.')
        _set_descriptor_mode(descriptor, 0o700)
        if not _same_entry(parent_descriptor, name, opened):
            raise OSError(errno.ESTALE, 'Private directory changed during creation.')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _create_private_directory_tree_posix(
    base_dir: Path,
    relative_directories: tuple[tuple[str, ...], ...],
) -> None:
    """Creates one private directory tree through anchored POSIX descriptors.

    Args:
        base_dir (Path): Root directory to create below an existing parent.
        relative_directories (tuple[tuple[str, ...], ...]): Relative directory component sequences.

    Returns:
        None
    """
    with _open_anchored_parent(base_dir) as (parent_descriptor, base_name):
        base_descriptor = _open_or_create_private_directory(
            parent_descriptor,
            base_name,
        )
        try:
            for components in relative_directories:
                current_descriptor = os.dup(base_descriptor)
                try:
                    for component in components:
                        if (
                            component in ('', '.', '..')
                            or Path(component).name != component
                        ):
                            raise OSError(
                                errno.EINVAL,
                                'Private directory component is invalid.',
                            )
                        next_descriptor = _open_or_create_private_directory(
                            current_descriptor,
                            component,
                        )
                        os.close(current_descriptor)
                        current_descriptor = next_descriptor
                finally:
                    os.close(current_descriptor)
        finally:
            os.close(base_descriptor)


def _create_private_directory_tree_windows(
    base_dir: Path,
    relative_directories: tuple[tuple[str, ...], ...],
) -> None:
    """Creates a Windows tree while locked handles prevent ancestor renames.

    Args:
        base_dir (Path): Root directory to create below an existing parent.
        relative_directories (tuple[tuple[str, ...], ...]): Relative directory component sequences.

    Returns:
        None
    """
    parent_handle, close_parent = _open_windows_directory_handle(base_dir.parent)
    try:
        base_dir.mkdir(mode=0o700, exist_ok=True)
        base_handle, close_base = _open_windows_directory_handle(base_dir)
        try:
            base_dir.chmod(0o700, follow_symlinks=False)
            for components in relative_directories:
                current_path = base_dir
                handles: list[tuple[object, Callable[[object], int]]] = []
                try:
                    for component in components:
                        if (
                            component in ('', '.', '..')
                            or Path(component).name != component
                        ):
                            raise OSError(
                                errno.EINVAL,
                                'Private directory component is invalid.',
                            )
                        current_path = current_path / component
                        current_path.mkdir(mode=0o700, exist_ok=True)
                        handle, close_handle = _open_windows_directory_handle(
                            current_path
                        )
                        handles.append((handle, close_handle))
                        current_path.chmod(0o700, follow_symlinks=False)
                finally:
                    for handle, close_handle in reversed(handles):
                        close_handle(handle)
        finally:
            close_base(base_handle)
    finally:
        close_parent(parent_handle)


def create_private_directory_tree(
    base_dir: Path,
    relative_directories: tuple[tuple[str, ...], ...],
) -> None:
    """Creates a private owned tree without following replaceable directories.

    Args:
        base_dir (Path): Root directory beneath an existing trusted parent.
        relative_directories (tuple[tuple[str, ...], ...]): Relative directory component sequences.

    Returns:
        None
    """
    if os.name == 'nt':
        _create_private_directory_tree_windows(base_dir, relative_directories)
        return
    _create_private_directory_tree_posix(base_dir, relative_directories)


@contextmanager
def open_private_binary_file(file_path: Path) -> Iterator[BinaryIO]:
    """Opens one private regular output file under a locked anchored parent.

    Args:
        file_path (Path): Exact internal file to create or replace.

    Yields:
        BinaryIO: Binary output stream bound to the validated file descriptor.

    Returns:
        None

    Raises:
        OSError: If a parent or leaf is linked, reparsed, or not regular.
    """
    if os.name == 'nt':
        parent_handle, close_parent = _open_windows_directory_handle(file_path.parent)
        try:
            descriptor = _open_windows_file(file_path, _WINDOWS_OPEN_ALWAYS)
            if descriptor is None:
                raise OSError(errno.ENOENT, 'Private output file could not be created.')
            with os.fdopen(descriptor, 'wb') as handle:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                    raise OSError(errno.EINVAL, 'Private output is not a regular file.')
                os.ftruncate(descriptor, 0)
                yield handle
                handle.flush()
                os.fsync(descriptor)
                current = os.stat(file_path, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (
                    opened.st_dev,
                    opened.st_ino,
                ):
                    raise OSError(
                        errno.ESTALE,
                        'Private output path changed during write.',
                    )
        finally:
            close_parent(parent_handle)
        return

    with _open_anchored_parent(file_path) as (parent_descriptor, name):
        no_follow = getattr(os, 'O_NOFOLLOW', None)
        if no_follow is None:
            raise OSError(errno.ENOTSUP, 'No-follow file opening is unavailable.')
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | no_follow | int(getattr(os, 'O_CLOEXEC', 0)),
            0o600,
            dir_fd=parent_descriptor,
        )
        with os.fdopen(descriptor, 'wb') as handle:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise OSError(errno.EINVAL, 'Private output is not a regular file.')
            _set_descriptor_mode(descriptor, 0o600)
            if not _same_entry(parent_descriptor, name, opened):
                raise OSError(errno.ESTALE, 'Private output path changed during open.')
            os.ftruncate(descriptor, 0)
            yield handle
            handle.flush()
            os.fsync(descriptor)
            if not _same_entry(parent_descriptor, name, opened):
                raise OSError(errno.ESTALE, 'Private output path changed during write.')


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
    if os.name != 'nt':
        with _open_anchored_parent(file_path) as (parent_descriptor, name):
            try:
                _secure_shred_entry(parent_descriptor, name)
            except FileNotFoundError:
                return
        return

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
    if os.name != 'nt':
        with _open_anchored_parent(path) as (parent_descriptor, name):
            _secure_remove_entry(parent_descriptor, name)
        return

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

    directory_handle, close_directory = _open_windows_directory_handle(path)
    try:
        for child in path.iterdir():
            secure_remove_path(child)
        path.chmod(
            stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR,
            follow_symlinks=False,
        )
    finally:
        close_directory(directory_handle)

    current = os.lstat(path)
    current_attributes = getattr(current, 'st_file_attributes', 0)
    if (
        stat.S_ISLNK(current.st_mode)
        or current_attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
        or not stat.S_ISDIR(current.st_mode)
    ):
        raise OSError(errno.ESTALE, 'Directory path changed during cleanup.')
    os.rmdir(path)
