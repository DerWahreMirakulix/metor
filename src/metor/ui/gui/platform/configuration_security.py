"""Native Windows trust checks for device configuration files."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
from typing import Any


_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_SE_FILE_OBJECT = 1
_TOKEN_QUERY = 0x0008
_TOKEN_USER_CLASS = 1
_ACL_SIZE_INFORMATION_CLASS = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_ACCESS_DENIED_ACE_TYPE = 1
_WIN_LOCAL_SYSTEM_SID = 22
_SECURITY_MAX_SID_SIZE = 68
_WRITE_RIGHTS = (
    0x00000002  # FILE_WRITE_DATA
    | 0x00000004  # FILE_APPEND_DATA
    | 0x00000010  # FILE_WRITE_EA
    | 0x00000100  # FILE_WRITE_ATTRIBUTES
    | 0x00010000  # DELETE
    | 0x00040000  # WRITE_DAC
    | 0x00080000  # WRITE_OWNER
    | 0x10000000  # GENERIC_ALL
    | 0x40000000  # GENERIC_WRITE
)


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [
        ('file_attributes', wintypes.DWORD),
        ('reparse_tag', wintypes.DWORD),
    ]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [('sid', wintypes.LPVOID), ('attributes', wintypes.DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [('user', _SidAndAttributes)]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [
        ('ace_count', wintypes.DWORD),
        ('acl_bytes_in_use', wintypes.DWORD),
        ('acl_bytes_free', wintypes.DWORD),
    ]


class _AceHeader(ctypes.Structure):
    _fields_ = [
        ('ace_type', ctypes.c_ubyte),
        ('ace_flags', ctypes.c_ubyte),
        ('ace_size', wintypes.WORD),
    ]


class _AccessAllowedAce(ctypes.Structure):
    _fields_ = [
        ('header', _AceHeader),
        ('mask', wintypes.DWORD),
        ('sid_start', wintypes.DWORD),
    ]


def _configure_apis(kernel32: Any, advapi32: Any) -> None:
    """Declare pointer-width-safe signatures for the Win32 calls used below."""
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.GetAclInformation.argtypes = [
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_int,
    ]
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.CreateWellKnownSid.argtypes = [
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.CreateWellKnownSid.restype = wintypes.BOOL


def _last_error() -> int:
    """Return the thread-local Win32 error without importing Windows-only stubs."""
    return int(getattr(ctypes, 'get_last_error')())


def _current_user_sid(kernel32: Any, advapi32: Any) -> tuple[Any, Any]:
    """Return a live token and buffer containing its user SID."""
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise OSError(_last_error(), 'OpenProcessToken failed')
    needed = wintypes.DWORD()
    advapi32.GetTokenInformation(
        token, _TOKEN_USER_CLASS, None, 0, ctypes.byref(needed)
    )
    if not needed.value:
        kernel32.CloseHandle(token)
        raise OSError(_last_error(), 'GetTokenInformation failed')
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.GetTokenInformation(
        token,
        _TOKEN_USER_CLASS,
        buffer,
        needed,
        ctypes.byref(needed),
    ):
        kernel32.CloseHandle(token)
        raise OSError(_last_error(), 'GetTokenInformation failed')
    return token, buffer


def _acl_is_private(handle: Any, kernel32: Any, advapi32: Any) -> bool:
    """Require current-user ownership and no foreign writable allow ACE."""
    token, token_buffer = _current_user_sid(kernel32, advapi32)
    descriptor = wintypes.LPVOID()
    owner = wintypes.LPVOID()
    dacl = wintypes.LPVOID()
    try:
        current_sid = ctypes.cast(
            token_buffer, ctypes.POINTER(_TokenUser)
        ).contents.user.sid
        result = advapi32.GetSecurityInfo(
            handle,
            _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if result or not owner or not dacl:
            return False
        if not advapi32.EqualSid(owner, current_sid):
            return False

        system_sid_buffer = ctypes.create_string_buffer(_SECURITY_MAX_SID_SIZE)
        system_sid_size = wintypes.DWORD(len(system_sid_buffer))
        if not advapi32.CreateWellKnownSid(
            _WIN_LOCAL_SYSTEM_SID,
            None,
            system_sid_buffer,
            ctypes.byref(system_sid_size),
        ):
            return False

        acl_info = _AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(acl_info),
            ctypes.sizeof(acl_info),
            _ACL_SIZE_INFORMATION_CLASS,
        ):
            return False
        for index in range(acl_info.ace_count):
            ace_pointer = wintypes.LPVOID()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
                return False
            ace = ctypes.cast(ace_pointer, ctypes.POINTER(_AccessAllowedAce)).contents
            if ace.header.ace_type == _ACCESS_DENIED_ACE_TYPE:
                continue
            if ace.header.ace_type != _ACCESS_ALLOWED_ACE_TYPE:
                return False
            if not ace.mask & _WRITE_RIGHTS:
                continue
            if ace_pointer.value is None:
                return False
            sid = ctypes.c_void_p(
                ace_pointer.value + _AccessAllowedAce.sid_start.offset
            )
            if not (
                advapi32.EqualSid(sid, current_sid)
                or advapi32.EqualSid(sid, system_sid_buffer)
            ):
                return False
        return True
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)
        kernel32.CloseHandle(token)


def open_windows_configuration(path: Path) -> int:
    """Open one non-reparse file and validate the ACL on that exact handle."""
    if os.name != 'nt':
        raise OSError('Windows secure opener is unavailable on this platform')
    import msvcrt

    win_dll = getattr(ctypes, 'WinDLL')
    kernel32 = win_dll('kernel32', use_last_error=True)
    advapi32 = win_dll('advapi32', use_last_error=True)
    _configure_apis(kernel32, advapi32)
    invalid_handle = wintypes.HANDLE(-1).value
    handle = kernel32.CreateFileW(
        str(path),
        _GENERIC_READ,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == invalid_handle:
        raise OSError(_last_error(), 'CreateFileW failed')
    try:
        attributes = _FileAttributeTagInfo()
        if not kernel32.GetFileInformationByHandleEx(
            handle,
            _FILE_ATTRIBUTE_TAG_INFO_CLASS,
            ctypes.byref(attributes),
            ctypes.sizeof(attributes),
        ):
            raise OSError(_last_error(), 'GetFileInformationByHandleEx failed')
        if attributes.file_attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError('Device configuration must not be a reparse point')
        if not _acl_is_private(handle, kernel32, advapi32):
            raise OSError('Device configuration ACL is not private')
        descriptor = int(getattr(msvcrt, 'open_osfhandle')(handle, os.O_RDONLY))
        handle = invalid_handle
        return descriptor
    finally:
        if handle != invalid_handle:
            kernel32.CloseHandle(handle)
