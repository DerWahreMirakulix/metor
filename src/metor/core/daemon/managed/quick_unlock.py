"""Salted memory-hard PIN verifier persistence and challenge proof checking."""

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Optional

from metor.core.auth import (
    PIN_SALT_BYTES,
    PIN_VERIFIER_BYTES,
    build_pin_unlock_proof,
    create_pin_verifier,
    derive_pin_verifier,
)

__all__ = [
    'PIN_SALT_BYTES',
    'PIN_VERIFIER_BYTES',
    'QuickUnlockStore',
    'build_pin_unlock_proof',
    'create_pin_verifier',
    'derive_pin_verifier',
]


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
        salt = bytes.fromhex(salt_hex)
        verifier = bytes.fromhex(verifier_hex)
        if len(salt) != PIN_SALT_BYTES or len(verifier) != PIN_VERIFIER_BYTES:
            raise ValueError('Invalid quick-unlock verifier material.')
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = self._path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as handle:
            json.dump(
                {'version': 1, 'salt': salt_hex, 'verifier': verifier_hex}, handle
            )
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(0o600)
        temp.replace(self._path)
        if os.name != 'nt':
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def remove(self) -> None:
        """Removes configured quick-unlock verifier material.

        Args:
            None

        Returns:
            None
        """
        self._path.unlink(missing_ok=True)

    def metadata(self) -> Optional[tuple[str, bytes]]:
        """Loads strict verifier metadata when configured.

        Args:
            None

        Returns:
            Optional[tuple[str, bytes]]: Salt and verifier bytes.
        """
        if not self._path.exists():
            return None
        with self._path.open('r', encoding='utf-8') as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or set(data) != {'version', 'salt', 'verifier'}:
            return None
        if data.get('version') != 1:
            return None
        try:
            salt = str(data['salt'])
            verifier = bytes.fromhex(str(data['verifier']))
            if (
                len(bytes.fromhex(salt)) != PIN_SALT_BYTES
                or len(verifier) != PIN_VERIFIER_BYTES
            ):
                return None
        except ValueError:
            return None
        return salt, verifier

    def verify(self, challenge_hex: str, proof: str) -> bool:
        """Verifies a one-use PIN HMAC proof in constant time.

        Args:
            challenge_hex (str): Issued random challenge.
            proof (str): Client proof digest.

        Returns:
            bool: True only for configured matching verifier material.
        """
        metadata = self.metadata()
        if metadata is None:
            return False
        try:
            expected = hmac.new(
                metadata[1], bytes.fromhex(challenge_hex), hashlib.sha256
            ).hexdigest()
        except ValueError:
            return False
        return hmac.compare_digest(expected, proof)
