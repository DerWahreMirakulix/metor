"""Exact Windows PIN credential ACL policy and non-mutating native inspection."""

import ctypes
from contextlib import nullcontext
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from link_fixtures import create_directory_alias
from private_fixtures import PrivateTemporaryDirectory
from metor.core.daemon.managed.quick_unlock import QuickUnlockStore
from metor.utils import validate_private_windows_path
from metor.utils.windows_acl import (
    _AccessAllowedAce,
    _AclSizeInformation,
    _validate_private_dacl,
)


class WindowsCredentialPolicyTests(unittest.TestCase):
    """Exercise decoded native ACE policy independently of the host platform."""

    def _validate(
        self,
        trustees: tuple[int, ...],
        *,
        owner: int = 11,
        protected: bool = True,
        directory: bool = False,
        flags: int = 0,
        mask: int = 0x001F01FF,
        ace_type: int = 0,
    ) -> None:
        """Supply real ctypes ACE buffers through the native inspection boundary."""
        current_sid, owner_sid = (
            ctypes.c_ulong(11),
            ctypes.c_ulong(owner),
        )
        entries = []
        for trustee in trustees:
            entry = _AccessAllowedAce()
            entry.header.ace_type = ace_type
            entry.header.ace_flags = flags
            entry.mask = mask
            entry.sid_start = trustee
            entries.append(entry)

        def equal_sid(left: object, right: object) -> bool:
            """Compare the fixture's stable SID identities, not pointer addresses."""
            return ctypes.cast(left, ctypes.POINTER(ctypes.c_ulong)).contents.value == (
                ctypes.cast(right, ctypes.POINTER(ctypes.c_ulong)).contents.value
            )

        def control(_descriptor: object, output: object, _revision: object) -> int:
            """Publish the real protected-DACL bit through the output pointer."""
            ctypes.cast(output, ctypes.POINTER(ctypes.c_ushort)).contents.value = (
                0x1000 if protected else 0
            )
            return 1

        def information(
            _dacl: object, output: object, _size: object, _kind: object
        ) -> int:
            """Publish the ACE inventory length."""
            ctypes.cast(
                output, ctypes.POINTER(_AclSizeInformation)
            ).contents.ace_count = len(entries)
            return 1

        def get_ace(_dacl: object, index: int, output: object) -> int:
            """Return an owned native ACE buffer for inspection."""
            ctypes.cast(
                output, ctypes.POINTER(ctypes.c_void_p)
            ).contents.value = ctypes.addressof(entries[index])
            return 1

        api = SimpleNamespace(
            EqualSid=MagicMock(side_effect=equal_sid),
            GetSecurityDescriptorControl=MagicMock(side_effect=control),
            GetAclInformation=MagicMock(side_effect=information),
            GetAce=MagicMock(side_effect=get_ace),
        )
        with (
            patch(
                'metor.utils.windows_acl._windows_libraries', return_value=(None, api)
            ),
            patch(
                'metor.utils.windows_acl._current_user_sid',
                return_value=nullcontext(
                    ctypes.cast(ctypes.byref(current_sid), ctypes.c_void_p)
                ),
            ),
        ):
            _validate_private_dacl(
                ctypes.c_void_p(1),
                ctypes.cast(ctypes.byref(owner_sid), ctypes.c_void_p),
                ctypes.c_void_p(2),
                directory=directory,
            )

    def test_credential_uses_the_same_owner_only_policy_as_profile_data(self) -> None:
        """PIN storage and profile initialization accept the same protected objects."""
        self._validate((11,))
        self._validate((11,), directory=True, flags=3)

    def test_credential_rejects_missing_extra_duplicate_or_foreign_trustees(
        self,
    ) -> None:
        """Only the exact current-user ACE is accepted, including for legacy PINs."""
        for trustees in ((), (22,), (11, 22), (11, 22, 33), (11, 11), (11, 33)):
            with self.subTest(trustees=trustees), self.assertRaises(PermissionError):
                self._validate(trustees)
        with self.assertRaises(PermissionError):
            self._validate((11,), owner=33)

    def test_credential_rejects_weaker_rights_and_inheritance_or_deny_entries(
        self,
    ) -> None:
        """No inherited, unprotected, deny, or partial-control ACE is accepted."""
        invalid = (
            {'protected': False},
            {'flags': 0x10},
            {'mask': 0x00120089},
            {'ace_type': 1},
            {'directory': True},
            {'flags': 3},
        )
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(PermissionError):
                self._validate((11,), **options)


@unittest.skipUnless(os.name == 'nt', 'Windows-native credential ACL regression.')
class WindowsCredentialNativeTests(unittest.TestCase):
    """Verify real protected credentials through stable, read-only native handles."""

    def test_metadata_inspection_never_launches_helpers_or_rewrites_acl(self) -> None:
        """Native verification reads exact owner-only protection without mutating it."""
        with PrivateTemporaryDirectory(prefix='metor credential ü ') as directory:
            path = Path(directory) / 'credential ü' / 'pin.json'
            store = QuickUnlockStore(path)
            store.configure('01' * 16, '02' * 32)
            before = path.read_bytes()
            with (
                patch(
                    'subprocess.run',
                    side_effect=AssertionError('Validation must stay in process.'),
                ),
                patch(
                    'metor.utils.security.apply_private_windows_dacl',
                    side_effect=AssertionError('Validation must not change the DACL.'),
                ),
            ):
                self.assertEqual(
                    store.metadata(), ('01' * 16, bytes.fromhex('02' * 32))
                )
                validate_private_windows_path(path, directory=False)
                validate_private_windows_path(path.parent, directory=True)
            self.assertEqual(path.read_bytes(), before)

    def test_credential_validation_rejects_native_directory_alias(self) -> None:
        """A junction cannot substitute for the selected credential directory."""
        with PrivateTemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'credential' / 'pin.json'
            QuickUnlockStore(path).configure('01' * 16, '02' * 32)
            alias = root / 'alias'
            create_directory_alias(alias, path.parent)
            try:
                with self.assertRaises(OSError):
                    validate_private_windows_path(alias, directory=True)
                with self.assertRaises(OSError):
                    validate_private_windows_path(alias / path.name, directory=False)
            finally:
                alias.rmdir()


if __name__ == '__main__':
    unittest.main()
