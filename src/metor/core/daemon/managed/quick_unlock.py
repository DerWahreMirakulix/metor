"""Salted memory-hard PIN verifier persistence and challenge proof checking."""

import hashlib
import base64
import hmac
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from metor.core.auth import (
    PIN_SALT_BYTES,
    PIN_VERIFIER_BYTES,
    build_pin_unlock_proof,
    create_pin_verifier,
    derive_pin_verifier,
)
from metor.utils import Constants

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
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f'.{self._path.name}.',
            suffix='.tmp',
            dir=self._path.parent,
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            if os.name == 'nt':
                self._protect_windows_path(temp_path, directory=False)
            else:
                self._fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                descriptor = -1
                json.dump(
                    {'version': 1, 'salt': salt_hex, 'verifier': verifier_hex},
                    handle,
                    separators=(',', ':'),
                )
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(self._path)
            self._validate_protection(self._path, directory=False)
            self._sync_parent()
        except (OSError, subprocess.SubprocessError) as exc:
            raise QuickUnlockStorageError(
                'Could not persist a protected quick-unlock credential.'
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
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
            if self._path.stat().st_size > Constants.QUICK_UNLOCK_METADATA_MAX_BYTES:
                raise QuickUnlockStorageError(
                    'Quick-unlock credential metadata exceeds its size limit.'
                )
            with self._path.open('rb') as handle:
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

    def verify(self, challenge_hex: str, proof: str) -> bool:
        """Verifies a one-use PIN HMAC proof in constant time.

        Args:
            challenge_hex (str): Issued random challenge.
            proof (str): Client proof digest.

        Returns:
            bool: True only for configured matching verifier material.
        """
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
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = self._path.parent.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(
                info, 'st_file_attributes', 0
            ) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
                raise QuickUnlockStorageError('Credential directory cannot be a link.')
            if os.name == 'nt':
                self._protect_windows_path(self._path.parent, directory=True)
            self._validate_protection(self._path.parent, directory=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise QuickUnlockStorageError(
                'Quick-unlock credential directory is not private.'
            ) from exc

    @staticmethod
    def _protect_windows_path(path: Path, *, directory: bool) -> None:
        """Replaces Windows ACLs with exact current-user and SYSTEM access.

        Args:
            path (Path): File or directory to protect.
            directory (bool): Whether child inheritance is required.

        Returns:
            None
        """
        inheritance = (
            '[System.Security.AccessControl.InheritanceFlags]::ContainerInherit '
            '-bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit'
            if directory
            else '[System.Security.AccessControl.InheritanceFlags]::None'
        )
        script = (
            ''
            '$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User; '
            '$system=New-Object System.Security.Principal.SecurityIdentifier('
            "'S-1-5-18'); "
            + (
                '$acl=New-Object System.Security.AccessControl.DirectorySecurity; '
                if directory
                else '$acl=New-Object System.Security.AccessControl.FileSecurity; '
            )
            + '$acl.SetOwner($sid); $acl.SetAccessRuleProtection($true,$false); '
            f'$inherit={inheritance}; '
            '$prop=[System.Security.AccessControl.PropagationFlags]::None; '
            '$rights=[System.Security.AccessControl.FileSystemRights]::FullControl; '
            '$allow=[System.Security.AccessControl.AccessControlType]::Allow; '
            '$acl.AddAccessRule((New-Object System.Security.AccessControl.'
            'FileSystemAccessRule($sid,$rights,$inherit,$prop,$allow))); '
            '$acl.AddAccessRule((New-Object System.Security.AccessControl.'
            'FileSystemAccessRule($system,$rights,$inherit,$prop,$allow))); '
            + (
                '[System.IO.Directory]::SetAccessControl($Target,$acl)'
                if directory
                else '[System.IO.File]::SetAccessControl($Target,$acl)'
            )
        )
        QuickUnlockStore._run_acl_helper(path, script, 'protect')

    @staticmethod
    def _validate_windows_acl(path: Path) -> None:
        """Verifies effective trustees after the ACL replacement."""
        script = (
            ''
            '$current=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; '
            '$acl=Get-Acl -LiteralPath $Target -ErrorAction Stop; '
            '$rules=@($acl.Access | ForEach-Object { [pscustomobject]@{ '
            'Sid=$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value; '
            'Inherited=$_.IsInherited; Type=$_.AccessControlType.ToString(); '
            'Rights=$_.FileSystemRights.ToString() } }); '
            '[pscustomobject]@{ Protected=$acl.AreAccessRulesProtected; '
            'Current=$current; Owner=$acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value; Rules=$rules } | ConvertTo-Json -Compress -Depth 4'
        )
        completed = QuickUnlockStore._run_acl_helper(path, script, 'validate')
        try:
            result = json.loads(completed.stdout)
            current = result['Current']
            rules = result['Rules']
            if isinstance(rules, dict):
                rules = [rules]
            if (
                result.get('Protected') is not True
                or result.get('Owner') != current
                or not isinstance(current, str)
                or not isinstance(rules, list)
                or len(rules) != 2
            ):
                raise ValueError
            expected = {current, 'S-1-5-18'}
            actual = {rule.get('Sid') for rule in rules if isinstance(rule, dict)}
            if actual != expected or any(
                not isinstance(rule, dict)
                or rule.get('Inherited') is not False
                or rule.get('Type') != 'Allow'
                or 'FullControl' not in str(rule.get('Rights'))
                for rule in rules
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise QuickUnlockStorageError(
                'Windows ACL protection is not private.'
            ) from exc

    @staticmethod
    def _run_acl_helper(
        path: Path, script: str, phase: str
    ) -> subprocess.CompletedProcess[str]:
        """Runs constant PowerShell code with path data on standard input.

        Args:
            path (Path): Target path, never interpolated into executable code.
            script (str): Constant ACL operation.
            phase (str): Non-secret diagnostic phase.

        Returns:
            subprocess.CompletedProcess[str]: Successful bounded helper result.
        """
        preamble = (
            "$ErrorActionPreference='Stop'; "
            '$utf8=New-Object System.Text.UTF8Encoding($false); '
            '[Console]::InputEncoding=$utf8; [Console]::OutputEncoding=$utf8; '
            '$Target=[Console]::In.ReadToEnd(); '
        )
        encoded = base64.b64encode((preamble + script).encode('utf-16-le')).decode(
            'ascii'
        )
        try:
            completed = subprocess.run(
                [
                    'powershell.exe',
                    '-NoProfile',
                    '-NonInteractive',
                    '-EncodedCommand',
                    encoded,
                ],
                input=str(path),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                check=False,
                timeout=Constants.QUICK_UNLOCK_HELPER_TIMEOUT_SEC,
            )
        except (OSError, subprocess.SubprocessError):
            raise QuickUnlockStorageError(
                f'Windows ACL {phase}: helper unavailable or timed out.'
            ) from None
        if completed.returncode != 0:
            raise QuickUnlockStorageError(
                f'Windows ACL {phase}: helper exited {completed.returncode}.'
            )
        return completed

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
        status = path.stat(follow_symlinks=False)
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
    def _fchmod(descriptor: int, mode: int) -> None:
        """Invokes the POSIX-only descriptor permission primitive safely."""
        fchmod = getattr(os, 'fchmod', None)
        if not callable(fchmod):
            raise OSError('Descriptor permissions are unavailable on this platform.')
        fchmod(descriptor, mode)

    @staticmethod
    def _getuid() -> int:
        """Returns the POSIX owner id without exposing it to Windows type checking."""
        getuid = getattr(os, 'getuid', None)
        if not callable(getuid):
            raise OSError('Owner validation is unavailable on this platform.')
        return int(getuid())
