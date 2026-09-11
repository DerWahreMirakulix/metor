"""Shared client/Core proof construction without daemon-internal imports."""

import hashlib
import hmac
import secrets

import nacl.pwhash

from metor.shared.security import secure_clear_buffer

PIN_VERIFIER_BYTES: int = 32
PIN_SALT_BYTES: int = nacl.pwhash.argon2id.SALTBYTES


def derive_pin_verifier(pin: str, salt_hex: str) -> bytearray:
    """Derives domain-separated memory-hard verifier material from a PIN.

    Args:
        pin (str): User-entered quick-unlock PIN.
        salt_hex (str): Hexadecimal Argon2id salt.

    Returns:
        bytearray: Mutable verifier-key material for prompt proof construction.

    Raises:
        ValueError: If the salt is malformed or has the wrong size.
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

    The returned verifier is a usable authentication credential and requires
    the same protected-storage handling as a password-derived proof key.

    Args:
        pin (str): User-entered quick-unlock PIN.

    Returns:
        tuple[str, str]: Hexadecimal salt and verifier credential.
    """
    salt = secrets.token_bytes(PIN_SALT_BYTES)
    verifier = derive_pin_verifier(pin, salt.hex())
    try:
        return salt.hex(), bytes(verifier).hex()
    finally:
        secure_clear_buffer(verifier)


def build_pin_unlock_proof(pin: str, salt_hex: str, challenge_hex: str) -> str:
    """Builds a one-use HMAC proof from a memory-hard PIN verifier.

    Args:
        pin (str): User-entered quick-unlock PIN.
        salt_hex (str): Hexadecimal verifier salt supplied by Core.
        challenge_hex (str): Hexadecimal one-use authentication challenge.

    Returns:
        str: Hexadecimal HMAC proof digest.
    """
    verifier = derive_pin_verifier(pin, salt_hex)
    try:
        return hmac.new(
            verifier, bytes.fromhex(challenge_hex), hashlib.sha256
        ).hexdigest()
    finally:
        secure_clear_buffer(verifier)
