"""Windows-native owner-only filesystem ACL regression tests."""

# ruff: noqa: E402

import ctypes
import os
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.utils.security import (
    _open_windows_directory_handle,
    _open_windows_file,
    create_private_directory_tree,
    open_private_binary_file,
    secure_remove_path,
)
from metor.utils.windows_acl import (
    _SecurityAttributes,
    apply_private_windows_dacl,
    validate_private_windows_dacl,
)


class WindowsAclFailureTests(unittest.TestCase):
    """Covers platform-independent propagation of native ACL failures."""

    def test_set_security_access_denial_is_visible(self) -> None:
        """A denied native DACL replacement cannot become successful setup.

        Args:
            None

        Returns:
            None
        """
        local_free = MagicMock(return_value=None)
        equal_sid = MagicMock(return_value=1)
        set_security = MagicMock(return_value=5)
        kernel32 = SimpleNamespace(LocalFree=local_free)
        advapi32 = SimpleNamespace(
            EqualSid=equal_sid,
            SetSecurityInfo=set_security,
        )
        attributes = _SecurityAttributes(
            ctypes.sizeof(_SecurityAttributes),
            ctypes.c_void_p(23),
            False,
        )
        attributes_pointer = ctypes.cast(
            ctypes.byref(attributes),
            ctypes.c_void_p,
        )
        with (
            patch(
                'metor.utils.windows_acl._windows_libraries',
                return_value=(kernel32, advapi32),
            ),
            patch(
                'metor.utils.windows_acl._read_handle_security',
                return_value=(
                    ctypes.c_void_p(11),
                    ctypes.c_void_p(12),
                    ctypes.c_void_p(13),
                ),
            ),
            patch(
                'metor.utils.windows_acl._current_user_sid',
                return_value=nullcontext(ctypes.c_void_p(11)),
            ),
            patch(
                'metor.utils.windows_acl.private_security_attributes',
                return_value=nullcontext(attributes_pointer),
            ),
            patch(
                'metor.utils.windows_acl._descriptor_dacl',
                return_value=ctypes.c_void_p(17),
            ),
            patch(
                'metor.utils.windows_acl._native_error',
                return_value=PermissionError('access denied'),
            ),
            self.assertRaisesRegex(PermissionError, 'access denied'),
        ):
            apply_private_windows_dacl(object(), directory=False)

        set_security.assert_called_once()
        local_free.assert_called_once()
        self.assertEqual(local_free.call_args.args[0].value, 13)


@unittest.skipUnless(os.name == 'nt', 'Windows-native ACL regression.')
class WindowsAclNativeTests(unittest.TestCase):
    """Exercises real Windows directory and file DACL lifecycle operations."""

    def test_private_tree_and_output_use_exact_owner_only_dacls(self) -> None:
        """Real directories and output files receive validated private DACLs.

        Args:
            None

        Returns:
            None
        """
        import msvcrt

        with TemporaryDirectory() as tmp_dir:
            profile = Path(tmp_dir) / 'profile'
            create_private_directory_tree(profile, (('blobs',),))

            for directory in (profile, profile / 'blobs'):
                handle, close_handle = _open_windows_directory_handle(directory)
                try:
                    validate_private_windows_dacl(handle, directory=True)
                finally:
                    close_handle(handle)

            output = profile / 'session-auth.bin'
            with open_private_binary_file(output) as output_file:
                output_file.write(b'generic-secret')
            descriptor = _open_windows_file(output)
            self.assertIsNotNone(descriptor)
            assert descriptor is not None
            try:
                validate_private_windows_dacl(
                    getattr(msvcrt, 'get_osfhandle')(descriptor),
                    directory=False,
                )
            finally:
                os.close(descriptor)

    def test_private_lifecycle_does_not_depend_on_path_chmod(self) -> None:
        """Creation and cleanup remain native when pathlib chmod is unsupported.

        Args:
            None

        Returns:
            None
        """
        with TemporaryDirectory() as tmp_dir:
            profile = Path(tmp_dir) / 'profile'
            with patch.object(
                Path,
                'chmod',
                side_effect=NotImplementedError('follow_symlinks unavailable'),
            ):
                create_private_directory_tree(profile, (('nested',),))
                with open_private_binary_file(
                    profile / 'nested' / 'secret.bin'
                ) as file:
                    file.write(b'generic-secret')
                secure_remove_path(profile)
            self.assertFalse(profile.exists())


if __name__ == '__main__':
    unittest.main()
