"""Salted memory-hard PIN verifier persistence and challenge proof checking."""

import hashlib
import hmac
import json
import os
import stat
import secrets
from pathlib import Path
from typing import BinaryIO, Optional

from metor.core.auth import (
    PIN_SALT_BYTES,
    PIN_VERIFIER_BYTES,
    build_pin_unlock_proof,
    create_pin_verifier,
    derive_pin_verifier,
)
from metor.utils import (
    Constants,
    create_private_directory_tree,
    open_private_binary_file,
    validate_private_windows_path,
)

__all__ = [
    'PIN_SALT_BYTES',
    'PIN_VERIFIER_BYTES',
    'QuickUnlockStore',
    'QuickUnlockStorageError',
    'build_pin_unlock_proof',
    'create_pin_verifier',
    'derive_pin_verifier',
]


class QuickUnlockStorageError(ValueError):
    """Reports malformed or insufficiently protected credential storage."""


class QuickUnlockStore:
    """Persists only salted PIN verifier material in protected profile storage."""

    def __init__(self, path: Path) -> None:
        """Initializes the quick-unlock store.

        Args:
            path (Path): Protected verifier metadata path.

        Returns:
            None
        """
        self._path = path

    def configure(self, salt_hex: str, verifier_hex: str) -> None:
        """Validates and atomically stores PIN verifier material.

        Args:
            salt_hex (str): Argon2id salt.
            verifier_hex (str): Derived verifier key.

        Returns:
            None
        """
        try:
            salt = bytes.fromhex(salt_hex)
            verifier = bytes.fromhex(verifier_hex)
        except ValueError as exc:
            raise QuickUnlockStorageError(
                'Invalid quick-unlock verifier encoding.'
            ) from exc
        if len(salt) != PIN_SALT_BYTES or len(verifier) != PIN_VERIFIER_BYTES:
            raise QuickUnlockStorageError('Invalid quick-unlock verifier material.')
        self._prepare_private_parent()
        temp_path = self._path.parent / (
            f'.{self._path.name}.{secrets.token_hex(Constants.PRIVATE_TEMP_TOKEN_BYTES)}.tmp'
        )
        payload = json.dumps(
            {'version': 1, 'salt': salt_hex, 'verifier': verifier_hex},
            separators=(',', ':'),
        ).encode('utf-8')
        temp_created = False
        try:
            with open_private_binary_file(temp_path, exclusive=True) as handle:
                temp_created = True
                handle.write(payload)
            self._validate_protection(temp_path, directory=False)
            temp_path.replace(self._path)
            self._validate_protection(self._path, directory=False)
            self._sync_parent()
        except OSError as exc:
            raise QuickUnlockStorageError(
                'Could not persist a protected quick-unlock credential.'
            ) from exc
        finally:
            if temp_created:
                temp_path.unlink(missing_ok=True)

    def remove(self) -> None:
        """Removes configured quick-unlock verifier material.

        Args:
            None

        Returns:
            None
        """
        try:
            self._path.unlink(missing_ok=True)
            self._sync_parent()
        except OSError as exc:
            raise QuickUnlockStorageError(
                'Could not remove the quick-unlock credential.'
            ) from exc

    def metadata(self) -> Optional[tuple[str, bytes]]:
        """Loads strict verifier metadata when configured.

        Args:
            None

        Returns:
            Optional[tuple[str, bytes]]: Salt and verifier bytes.
        """
        if not self._path.exists():
            return None
        self._validate_protection(self._path.parent, directory=True)
        self._validate_protection(self._path, directory=False)
        try:
            with self._open_metadata() as handle:
                if (
                    os.fstat(handle.fileno()).st_size
                    > Constants.QUICK_UNLOCK_METADATA_MAX_BYTES
                ):
                    raise QuickUnlockStorageError(
                        'Quick-unlock credential metadata exceeds its size limit.'
                    )
                payload = handle.read(Constants.QUICK_UNLOCK_METADATA_MAX_BYTES + 1)
            if len(payload) > Constants.QUICK_UNLOCK_METADATA_MAX_BYTES:
                raise QuickUnlockStorageError(
                    'Quick-unlock credential metadata exceeds its size limit.'
                )
            data = json.loads(payload.decode('utf-8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QuickUnlockStorageError(
                'Quick-unlock credential metadata is unreadable or malformed.'
            ) from exc
        if not isinstance(data, dict) or set(data) != {'version', 'salt', 'verifier'}:
            raise QuickUnlockStorageError('Invalid quick-unlock credential shape.')
        if data.get('version') != 1:
            raise QuickUnlockStorageError(
                'Unsupported quick-unlock credential version.'
            )
        try:
            if not isinstance(data['salt'], str) or not isinstance(
                data['verifier'], str
            ):
                raise ValueError('Credential fields must be hexadecimal strings.')
            salt = data['salt']
            verifier = bytes.fromhex(data['verifier'])
            if (
                len(bytes.fromhex(salt)) != PIN_SALT_BYTES
                or len(verifier) != PIN_VERIFIER_BYTES
            ):
                raise ValueError('Credential field length is invalid.')
        except ValueError as exc:
            raise QuickUnlockStorageError(
                'Invalid quick-unlock credential material.'
            ) from exc
        return salt, verifier

    def _open_metadata(self) -> BinaryIO:
        """Opens the bounded credential read without blocking on a replaced POSIX leaf.

        The opened POSIX descriptor is checked again because the entry can change
        after path validation. No-follow and nonblocking open reject links and
        allow special-file refusal before any read occurs.
        """
        if os.name == 'nt':
            return self._path.open('rb')
        no_follow = getattr(os, 'O_NOFOLLOW', None)
        nonblock = getattr(os, 'O_NONBLOCK', None)
        if no_follow is None or nonblock is None:
            raise OSError('Safe credential read flags are unavailable.')
        descriptor = os.open(
            self._path,
            os.O_RDONLY | no_follow | nonblock | getattr(os, 'O_CLOEXEC', 0),
        )
        try:
            self._validate_posix_status(os.fstat(descriptor), directory=False)
            return os.fdopen(descriptor, 'rb')
        except BaseException:
            os.close(descriptor)
            raise

    def verify(self, challenge_hex: str, proof: str) -> bool:
        """Verifies a one-use PIN HMAC proof in constant time.

        Args:
            challenge_hex (str): Issued random challenge.
            proof (str): Client proof digest.

        Returns:
            bool: True only for configured matching verifier material.
        """
        if not proof.isascii():
            return False
        try:
            metadata = self.metadata()
        except QuickUnlockStorageError:
            return False
        if metadata is None:
            return False
        try:
            expected = hmac.new(
                metadata[1], bytes.fromhex(challenge_hex), hashlib.sha256
            ).hexdigest()
        except ValueError:
            return False
        return hmac.compare_digest(expected, proof)

    def _prepare_private_parent(self) -> None:
        """Creates and validates the immediate credential directory.

        Args:
            None

        Returns:
            None
        """
        try:
            credential_exists: bool = self._path.exists()
            if not credential_exists:
                create_private_directory_tree(self._path.parent, ())
            info = self._path.parent.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(
                info, 'st_file_attributes', 0
            ) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
                raise QuickUnlockStorageError('Credential directory cannot be a link.')
            self._validate_protection(self._path.parent, directory=True)
        except OSError as exc:
            raise QuickUnlockStorageError(
                'Quick-unlock credential directory is not private.'
            ) from exc

    @staticmethod
    def _validate_windows_acl(path: Path) -> None:
        """Verifies exact credential trustees through native read-only handles.

        Args:
            path (Path): Credential file whose effective trustees must be private.

        Returns:
            None
        """
        try:
            validate_private_windows_path(path, directory=path.is_dir())
        except OSError as exc:
            raise QuickUnlockStorageError(
                'Windows ACL protection is not private.'
            ) from exc

    @staticmethod
    def _validate_protection(path: Path, *, directory: bool) -> None:
        """Validates the supported platform's credential protection boundary.

        Args:
            path (Path): Protected file or directory.
            directory (bool): Whether the target must be a directory.

        Returns:
            None
        """
        if path.is_symlink():
            raise QuickUnlockStorageError('Credential paths must not be symlinks.')
        if directory != path.is_dir():
            raise QuickUnlockStorageError('Credential path type is invalid.')
        if os.name == 'nt':
            QuickUnlockStore._validate_windows_acl(path)
            return
        QuickUnlockStore._validate_posix_status(
            path.stat(follow_symlinks=False), directory=directory
        )

    @staticmethod
    def _validate_posix_status(status: os.stat_result, *, directory: bool) -> None:
        """Requires private ownership and a directory or uniquely linked regular file."""
        if directory:
            valid_type = stat.S_ISDIR(status.st_mode)
        else:
            valid_type = stat.S_ISREG(status.st_mode) and status.st_nlink == 1
        if not valid_type:
            raise QuickUnlockStorageError(
                'Credential path type or link count is invalid.'
            )
        if status.st_uid != QuickUnlockStore._getuid():
            raise QuickUnlockStorageError('Credential path has an unsafe owner.')
        forbidden = stat.S_IRWXG | stat.S_IRWXO
        if status.st_mode & forbidden:
            raise QuickUnlockStorageError(
                'Credential path permissions are not private.'
            )

    def _sync_parent(self) -> None:
        """Persists directory metadata on platforms supporting directory fsync.

        Args:
            None

        Returns:
            None
        """
        if os.name == 'nt' or not self._path.parent.exists():
            return
        directory_fd = os.open(self._path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _getuid() -> int:
        """Returns the POSIX owner id without exposing it to Windows type checking.

        Args:
            None

        Returns:
            int: Current effective POSIX user identity.
        """
        getuid = getattr(os, 'getuid', None)
        if not callable(getuid):
            raise OSError('Owner validation is unavailable on this platform.')
        return int(getuid())
