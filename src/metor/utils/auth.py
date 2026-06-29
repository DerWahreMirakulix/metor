"""Shared cryptographic helpers for local daemon session-auth proofs."""

import hashlib
import hmac
import secrets
from typing import Union

import nacl.pwhash

# Local Package Imports
from metor.utils.constants import Constants
from metor.utils.security import secure_clear_buffer


_SESSION_AUTH_PASSWORD_PREFIX: str = 'metor-ipc-auth:'
ProofKeyBuffer = Union[bytes, bytearray, memoryview]


def _decode_session_auth_salt(salt_hex: str) -> bytes:
    """
    Decodes and validates one session-auth salt from hexadecimal transport format.

    Args:
        salt_hex (str): The hexadecimal salt string.

    Raises:
        ValueError: If the salt is not valid hexadecimal or has the wrong length.

    Returns:
        bytes: The decoded salt bytes.
    """
    try:
        salt: bytes = bytes.fromhex(salt_hex)
    except ValueError as exc:
        raise ValueError('Invalid session auth salt.') from exc

    if len(salt) != nacl.pwhash.argon2i.SALTBYTES:
        raise ValueError('Invalid session auth salt length.')

    return salt


def _decode_session_auth_challenge(challenge_hex: str) -> bytes:
    """
    Decodes one daemon-issued session-auth challenge from hexadecimal transport format.

    Args:
        challenge_hex (str): The hexadecimal challenge string.

    Raises:
        ValueError: If the challenge is not valid hexadecimal or has the wrong length.

    Returns:
        bytes: The decoded challenge bytes.
    """
    try:
        challenge: bytes = bytes.fromhex(challenge_hex)
    except ValueError as exc:
        raise ValueError('Invalid session auth challenge.') from exc

    if len(challenge) != Constants.SESSION_AUTH_CHALLENGE_BYTES:
        raise ValueError('Invalid session auth challenge length.')

    return challenge


def create_session_auth_salt() -> bytes:
    """
    Creates one fresh salt for a single daemon runtime's session-auth proof key.

    Args:
        None

    Returns:
        bytes: The random Argon2 salt bytes.
    """
    return secrets.token_bytes(nacl.pwhash.argon2i.SALTBYTES)


def _scope_password(password: str) -> bytes:
    """
    Domain-separates one master password before deriving the session-auth proof key.

    Args:
        password (str): The master password.

    Returns:
        bytes: The scoped password bytes.
    """
    return f'{_SESSION_AUTH_PASSWORD_PREFIX}{password}'.encode('utf-8')


def derive_session_auth_proof_key(password: str, salt: bytes) -> bytearray:
    """
    Derives one password-scoped IPC session-auth proof key from the runtime salt.

    Args:
        password (str): The master password.
        salt (bytes): The persisted profile salt.

    Returns:
        bytearray: The derived proof key in a mutable buffer.
    """
    return bytearray(
        nacl.pwhash.argon2i.kdf(
            Constants.SESSION_AUTH_KEY_BYTES,
            _scope_password(password),
            salt,
            opslimit=nacl.pwhash.argon2i.OPSLIMIT_SENSITIVE,
            memlimit=nacl.pwhash.argon2i.MEMLIMIT_SENSITIVE,
        )
    )


def create_session_auth_challenge() -> str:
    """
    Creates one fresh random challenge for a single IPC session-auth attempt.

    Args:
        None

    Returns:
        str: The hexadecimal challenge string.
    """
    return secrets.token_hex(Constants.SESSION_AUTH_CHALLENGE_BYTES)


def build_session_auth_proof(
    password: str,
    challenge_hex: str,
    salt_hex: str,
) -> str:
    """
    Builds one HMAC proof from the supplied password, daemon challenge, and salt.

    Args:
        password (str): The master password.
        challenge_hex (str): The daemon-issued challenge.
        salt_hex (str): The daemon-issued salt.

    Returns:
        str: The hexadecimal proof digest.
    """
    salt: bytes = _decode_session_auth_salt(salt_hex)
    proof_key: bytearray = derive_session_auth_proof_key(password, salt)
    try:
        return build_session_auth_proof_from_key(proof_key, challenge_hex)
    finally:
        secure_clear_buffer(proof_key)


def build_session_auth_proof_from_key(
    proof_key: ProofKeyBuffer,
    challenge_hex: str,
) -> str:
    """
    Builds one HMAC proof from an already-derived session-auth proof key.

    Args:
        proof_key (ProofKeyBuffer): The derived proof key.
        challenge_hex (str): The daemon-issued challenge.

    Returns:
        str: The hexadecimal proof digest.
    """
    challenge: bytes = _decode_session_auth_challenge(challenge_hex)
    hmac_key: bytes | bytearray
    if isinstance(proof_key, memoryview):
        hmac_key = proof_key.tobytes()
    else:
        hmac_key = proof_key
    return hmac.new(hmac_key, challenge, hashlib.sha256).hexdigest()


def verify_session_auth_proof(
    proof_key: ProofKeyBuffer,
    challenge_hex: str,
    provided_proof: str,
) -> bool:
    """
    Verifies one client-supplied session-auth proof in constant time.

    Args:
        proof_key (ProofKeyBuffer): The daemon-side verifier key.
        challenge_hex (str): The currently active challenge.
        provided_proof (str): The proof provided by the client.

    Returns:
        bool: True if the proof matches, False otherwise.
    """
    try:
        expected_proof: str = build_session_auth_proof_from_key(
            proof_key,
            challenge_hex,
        )
    except ValueError:
        return False

    return hmac.compare_digest(expected_proof, provided_proof.lower())
