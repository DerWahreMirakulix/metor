"""Salted memory-hard PIN verifier persistence and challenge proof checking."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from typing import Optional

import nacl.pwhash

PIN_VERIFIER_BYTES: int = 32
PIN_SALT_BYTES: int = nacl.pwhash.argon2id.SALTBYTES


def derive_pin_verifier(pin: str, salt_hex: str) -> bytearray:
    """Derives domain-separated memory-hard verifier material from a PIN.

    Args:
        pin (str): User PIN supplied outside logs and command repr output.
        salt_hex (str): Random Argon2id salt in hexadecimal.

    Returns:
        bytearray: Mutable verifier key material.
    """
    salt = bytes.fromhex(salt_hex)
    if len(salt) != PIN_SALT_BYTES:
        raise ValueError('Invalid PIN salt length.')
    return bytearray(
        nacl.pwhash.argon2id.kdf(
            PIN_VERIFIER_BYTES,
            f'metor-pin-quick-unlock:{pin}'.encode('utf-8'),
            salt,
            opslimit=nacl.pwhash.argon2id.OPSLIMIT_INTERACTIVE,
            memlimit=nacl.pwhash.argon2id.MEMLIMIT_INTERACTIVE,
        )
    )


def create_pin_verifier(pin: str) -> tuple[str, str]:
    """Creates client-side verifier material without transmitting the raw PIN.

    Args:
        pin (str): Optional quick-unlock PIN.

    Returns:
        tuple[str, str]: Salt and verifier hexadecimal strings.
    """
    salt = secrets.token_bytes(PIN_SALT_BYTES)
    verifier = derive_pin_verifier(pin, salt.hex())
    return salt.hex(), bytes(verifier).hex()


def build_pin_unlock_proof(pin: str, salt_hex: str, challenge_hex: str) -> str:
    """Builds a one-use HMAC proof from a memory-hard PIN verifier.

    Args:
        pin (str): User-entered PIN.
        salt_hex (str): Core-provided verifier salt.
        challenge_hex (str): Core-provided one-use challenge.

    Returns:
        str: HMAC-SHA256 proof digest.
    """
    verifier = derive_pin_verifier(pin, salt_hex)
    try:
        return hmac.new(
            verifier, bytes.fromhex(challenge_hex), hashlib.sha256
        ).hexdigest()
    finally:
        for index in range(len(verifier)):
            verifier[index] = 0


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
