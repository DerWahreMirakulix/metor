"""Native owner-only Windows filesystem access-control helpers."""

import ctypes
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, cast


_TOKEN_QUERY: int = 0x0008
_TOKEN_USER_CLASS: int = 1
_ERROR_INSUFFICIENT_BUFFER: int = 122
_ERROR_ALREADY_EXISTS: int = 183
_SDDL_REVISION_1: int = 1
_SE_FILE_OBJECT: int = 1
_OWNER_SECURITY_INFORMATION: int = 0x00000001
_DACL_SECURITY_INFORMATION: int = 0x00000004
_PROTECTED_DACL_SECURITY_INFORMATION: int = 0x80000000
_SE_DACL_PROTECTED: int = 0x1000
_ACL_SIZE_INFORMATION_CLASS: int = 2
_ACCESS_ALLOWED_ACE_TYPE: int = 0
_OBJECT_INHERIT_ACE: int = 0x01
_CONTAINER_INHERIT_ACE: int = 0x02
_FILE_ALL_ACCESS: int = 0x001F01FF


class _SidAndAttributes(ctypes.Structure):
    """Windows token SID pointer plus its attribute flags."""

    _fields_ = [('sid', ctypes.c_void_p), ('attributes', ctypes.c_ulong)]


class _TokenUser(ctypes.Structure):
    """Windows TOKEN_USER representation."""

    _fields_ = [('user', _SidAndAttributes)]


class _SecurityAttributes(ctypes.Structure):
    """Windows SECURITY_ATTRIBUTES carrying an explicit descriptor."""

    _fields_ = [
        ('length', ctypes.c_ulong),
        ('security_descriptor', ctypes.c_void_p),
        ('inherit_handle', ctypes.c_int),
    ]


class _AclSizeInformation(ctypes.Structure):
    """Windows ACL_SIZE_INFORMATION result."""

    _fields_ = [
        ('ace_count', ctypes.c_ulong),
        ('acl_bytes_in_use', ctypes.c_ulong),
        ('acl_bytes_free', ctypes.c_ulong),
    ]


class _AceHeader(ctypes.Structure):
    """Common Windows ACE header."""

    _fields_ = [
        ('ace_type', ctypes.c_ubyte),
        ('ace_flags', ctypes.c_ubyte),
        ('ace_size', ctypes.c_ushort),
    ]


class _AccessAllowedAce(ctypes.Structure):
    """Windows ACCESS_ALLOWED_ACE prefix before its variable SID."""

    _fields_ = [
        ('header', _AceHeader),
        ('mask', ctypes.c_ulong),
        ('sid_start', ctypes.c_ulong),
    ]


def _windows_libraries() -> tuple[Any, Any]:
    """Loads the native libraries needed for filesystem ACL operations.

    Args:
        None

    Returns:
        tuple[object, object]: Kernel and advanced-security libraries.
    """
    win_dll = getattr(ctypes, 'WinDLL')
    return (
        win_dll('kernel32', use_last_error=True),
        win_dll('advapi32', use_last_error=True),
    )


def _native_error(code: int | None = None) -> OSError:
    """Builds one Windows error without requiring POSIX ctypes stubs to expose it.

    Args:
        code (int | None): Explicit native error code or the current last error.

    Returns:
        OSError: Platform-native Windows exception.
    """
    win_error = getattr(ctypes, 'WinError')
    if code is None:
        return cast(OSError, win_error(getattr(ctypes, 'get_last_error')()))
    return cast(OSError, win_error(code))


@contextmanager
def _current_user_sid() -> Iterator[ctypes.c_void_p]:
    """Yields the current process token's user SID from an owned buffer.

    Args:
        None

    Yields:
        ctypes.c_void_p: SID pointer valid for the context lifetime.

    Returns:
        None

    Raises:
        OSError: If the process token or its user information cannot be read.
    """
    kernel32, advapi32 = _windows_libraries()
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = ()
    get_current_process.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int
    open_process_token = advapi32.OpenProcessToken
    open_process_token.argtypes = (
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
    )
    open_process_token.restype = ctypes.c_int
    get_token_information = advapi32.GetTokenInformation
    get_token_information.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    )
    get_token_information.restype = ctypes.c_int

    token = ctypes.c_void_p()
    if not open_process_token(
        get_current_process(),
        _TOKEN_QUERY,
        ctypes.byref(token),
    ):
        raise _native_error()
    try:
        required = ctypes.c_ulong()
        if get_token_information(
            token,
            _TOKEN_USER_CLASS,
            None,
            0,
            ctypes.byref(required),
        ):
            raise OSError('Token user query unexpectedly accepted an empty buffer.')
        error_code = getattr(ctypes, 'get_last_error')()
        if error_code != _ERROR_INSUFFICIENT_BUFFER or required.value == 0:
            raise _native_error(error_code)
        buffer = ctypes.create_string_buffer(required.value)
        if not get_token_information(
            token,
            _TOKEN_USER_CLASS,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise _native_error()
        token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        if not token_user.user.sid:
            raise OSError('Current Windows token has no user SID.')
        yield ctypes.c_void_p(token_user.user.sid)
    finally:
        close_handle(token)


def _current_user_sid_string() -> str:
    """Returns the current process token's user SID in SDDL form.

    Args:
        None

    Returns:
        str: Stable textual SID for the current Windows user.

    Raises:
        OSError: If the SID cannot be converted.
    """
    kernel32, advapi32 = _windows_libraries()
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    )
    convert_sid.restype = ctypes.c_int
    local_free = kernel32.LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p

    with _current_user_sid() as sid:
        sid_text = ctypes.c_wchar_p()
        if not convert_sid(sid, ctypes.byref(sid_text)):
            raise _native_error()
        try:
            if sid_text.value is None:
                raise OSError('Windows returned an empty user SID string.')
            return sid_text.value
        finally:
            local_free(ctypes.cast(sid_text, ctypes.c_void_p))


@contextmanager
def private_security_attributes(
    *,
    directory: bool,
) -> Iterator[ctypes.c_void_p]:
    """Yields creation attributes with a protected current-user-only DACL.

    Args:
        directory (bool): Whether child objects must inherit the owner-only ACE.

    Yields:
        ctypes.c_void_p: Pointer to native SECURITY_ATTRIBUTES.

    Returns:
        None

    Raises:
        OSError: If the native security descriptor cannot be constructed.
    """
    kernel32, advapi32 = _windows_libraries()
    convert_descriptor = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert_descriptor.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_ulong),
    )
    convert_descriptor.restype = ctypes.c_int
    local_free = kernel32.LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p

    sid = _current_user_sid_string()
    inheritance = 'OICI' if directory else ''
    sddl = f'O:{sid}D:P(A;{inheritance};FA;;;{sid})'
    descriptor = ctypes.c_void_p()
    if not convert_descriptor(
        sddl,
        _SDDL_REVISION_1,
        ctypes.byref(descriptor),
        None,
    ):
        raise _native_error()
    attributes = _SecurityAttributes(
        ctypes.sizeof(_SecurityAttributes),
        descriptor,
        False,
    )
    try:
        yield ctypes.cast(ctypes.byref(attributes), ctypes.c_void_p)
    finally:
        local_free(descriptor)


def create_private_windows_directory(directory_path: Path) -> None:
    """Creates a directory with an atomic current-user-only Windows DACL.

    Args:
        directory_path (Path): Exact directory to create without parent creation.

    Returns:
        None

    Raises:
        OSError: If creation fails for a reason other than prior existence.
    """
    kernel32, _ = _windows_libraries()
    create_directory = kernel32.CreateDirectoryW
    create_directory.argtypes = (ctypes.c_wchar_p, ctypes.c_void_p)
    create_directory.restype = ctypes.c_int
    with private_security_attributes(directory=True) as attributes:
        if create_directory(str(directory_path), attributes):
            return
        error_code = getattr(ctypes, 'get_last_error')()
        if error_code != _ERROR_ALREADY_EXISTS:
            raise OSError(
                error_code, 'Private directory could not be created.', directory_path
            )


def _descriptor_dacl(descriptor: ctypes.c_void_p) -> ctypes.c_void_p:
    """Returns the non-null DACL from a Windows security descriptor.

    Args:
        descriptor (ctypes.c_void_p): Native security descriptor pointer.

    Returns:
        ctypes.c_void_p: Present non-null DACL pointer.

    Raises:
        OSError: If the descriptor has no restrictive DACL.
    """
    _, advapi32 = _windows_libraries()
    get_dacl = advapi32.GetSecurityDescriptorDacl
    get_dacl.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_int),
    )
    get_dacl.restype = ctypes.c_int
    present = ctypes.c_int()
    defaulted = ctypes.c_int()
    dacl = ctypes.c_void_p()
    if not get_dacl(
        descriptor,
        ctypes.byref(present),
        ctypes.byref(dacl),
        ctypes.byref(defaulted),
    ):
        raise _native_error()
    if not present.value or not dacl.value:
        raise PermissionError('Windows private object has no restrictive DACL.')
    return dacl


def _read_handle_security(
    handle: object,
) -> tuple[ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]:
    """Reads owner and DACL pointers plus their owned descriptor from a handle.

    Args:
        handle (object): Stable native filesystem handle with READ_CONTROL.

    Returns:
        tuple[ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]: Owner, DACL, and descriptor.

    Raises:
        OSError: If native security information cannot be read.
    """
    _, advapi32 = _windows_libraries()
    get_security = advapi32.GetSecurityInfo
    get_security.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    )
    get_security.restype = ctypes.c_ulong
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = get_security(
        handle,
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        raise _native_error(result)
    if not descriptor.value or not owner.value or not dacl.value:
        kernel32, _ = _windows_libraries()
        if descriptor.value:
            kernel32.LocalFree(descriptor)
        raise PermissionError('Windows private object lacks an owner or DACL.')
    return owner, dacl, descriptor


def _validate_private_dacl(
    descriptor: ctypes.c_void_p,
    owner: ctypes.c_void_p,
    dacl: ctypes.c_void_p,
    *,
    directory: bool,
) -> None:
    """Validates one exact protected owner-only access-control entry.

    Args:
        descriptor (ctypes.c_void_p): Complete native security descriptor.
        owner (ctypes.c_void_p): Descriptor owner SID.
        dacl (ctypes.c_void_p): Descriptor discretionary ACL.
        directory (bool): Whether inheritance flags are required.

    Returns:
        None

    Raises:
        PermissionError: If owner or DACL grants a broader or weaker policy.
        OSError: If native ACL inspection fails.
    """
    _, advapi32 = _windows_libraries()
    equal_sid = advapi32.EqualSid
    equal_sid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    equal_sid.restype = ctypes.c_int
    get_control = advapi32.GetSecurityDescriptorControl
    get_control.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ushort),
        ctypes.POINTER(ctypes.c_ulong),
    )
    get_control.restype = ctypes.c_int
    get_acl_information = advapi32.GetAclInformation
    get_acl_information.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
    )
    get_acl_information.restype = ctypes.c_int
    get_ace = advapi32.GetAce
    get_ace.argtypes = (
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_void_p),
    )
    get_ace.restype = ctypes.c_int

    with _current_user_sid() as current_sid:
        if not equal_sid(owner, current_sid):
            raise PermissionError('Windows private object is not owned by this user.')
        control = ctypes.c_ushort()
        revision = ctypes.c_ulong()
        if not get_control(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise _native_error()
        if not control.value & _SE_DACL_PROTECTED:
            raise PermissionError('Windows private DACL is not protected.')
        acl_info = _AclSizeInformation()
        if not get_acl_information(
            dacl,
            ctypes.byref(acl_info),
            ctypes.sizeof(acl_info),
            _ACL_SIZE_INFORMATION_CLASS,
        ):
            raise _native_error()
        if acl_info.ace_count != 1:
            raise PermissionError('Windows private DACL must contain exactly one ACE.')
        ace_pointer = ctypes.c_void_p()
        if not get_ace(dacl, 0, ctypes.byref(ace_pointer)):
            raise _native_error()
        ace = ctypes.cast(ace_pointer, ctypes.POINTER(_AccessAllowedAce)).contents
        required_flags = (
            _OBJECT_INHERIT_ACE | _CONTAINER_INHERIT_ACE if directory else 0
        )
        if (
            ace.header.ace_type != _ACCESS_ALLOWED_ACE_TYPE
            or ace.header.ace_flags != required_flags
            or ace.mask != _FILE_ALL_ACCESS
        ):
            raise PermissionError('Windows private DACL has an unexpected ACE.')
        ace_sid = ctypes.c_void_p(
            (ace_pointer.value or 0) + _AccessAllowedAce.sid_start.offset
        )
        if not equal_sid(ace_sid, current_sid):
            raise PermissionError('Windows private DACL grants another identity.')


def validate_private_windows_dacl(handle: object, *, directory: bool) -> None:
    """Validates the exact owner-only DACL currently attached to a handle.

    Args:
        handle (object): Stable filesystem handle with READ_CONTROL.
        directory (bool): Whether child-object inheritance flags are required.

    Returns:
        None

    Raises:
        PermissionError: If owner or DACL grants a broader or weaker policy.
        OSError: If native security information cannot be read.
    """
    kernel32, _ = _windows_libraries()
    local_free = kernel32.LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p
    owner, dacl, descriptor = _read_handle_security(handle)
    try:
        _validate_private_dacl(
            descriptor,
            owner,
            dacl,
            directory=directory,
        )
    finally:
        local_free(descriptor)


def apply_private_windows_dacl(handle: object, *, directory: bool) -> None:
    """Applies and verifies the owner-only DACL through one stable handle.

    Args:
        handle (object): Stable filesystem handle with READ_CONTROL and WRITE_DAC.
        directory (bool): Whether child objects must inherit the owner-only ACE.

    Returns:
        None

    Raises:
        PermissionError: If the object is not owned by the current user.
        OSError: If applying or validating the native DACL fails.
    """
    kernel32, advapi32 = _windows_libraries()
    local_free = kernel32.LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p
    equal_sid = advapi32.EqualSid
    equal_sid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    equal_sid.restype = ctypes.c_int
    set_security = advapi32.SetSecurityInfo
    set_security.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    set_security.restype = ctypes.c_ulong

    owner, _, current_descriptor = _read_handle_security(handle)
    try:
        with _current_user_sid() as current_sid:
            if not equal_sid(owner, current_sid):
                raise PermissionError(
                    'Refusing to change a foreign-owned Windows object.'
                )
    finally:
        local_free(current_descriptor)

    with private_security_attributes(directory=directory) as attributes_pointer:
        attributes = ctypes.cast(
            attributes_pointer,
            ctypes.POINTER(_SecurityAttributes),
        ).contents
        desired_dacl = _descriptor_dacl(attributes.security_descriptor)
        result = set_security(
            handle,
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            desired_dacl,
            None,
        )
        if result != 0:
            raise _native_error(result)

    validate_private_windows_dacl(handle, directory=directory)
