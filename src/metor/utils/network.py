"""
Module containing network-related utility functions.
Isolates Tor and onion address formatting logic.
"""

import base64
import hashlib

# Local Package Imports
from metor.utils.constants import Constants


def clean_onion(onion: str) -> str:
    """
    Strips whitespace and the '.onion' suffix from a given onion address.

    Args:
        onion (str): The raw onion address string.

    Returns:
        str: The cleaned 56-character onion address.
    """
    onion = onion.strip().lower()
    if onion.endswith('.onion'):
        onion = onion[:-6]
    return onion


def decode_tor_v3_onion_public_key(onion: str) -> bytes:
    """
    Validates one Tor v3 onion address and returns its embedded Ed25519 public key.

    Args:
        onion (str): The raw onion address string.

    Raises:
        ValueError: If the address is not a valid Tor v3 onion identity.

    Returns:
        bytes: The embedded Ed25519 public key.
    """
    clean: str = clean_onion(onion)
    if len(clean) != Constants.TOR_V3_ONION_ADDRESS_LENGTH:
        raise ValueError('Invalid onion address length.')

    encoded: str = clean.upper() + ('=' * ((-len(clean)) % 8))

    try:
        raw: bytes = base64.b32decode(encoded)
    except Exception as exc:
        raise ValueError('Invalid onion address encoding.') from exc

    expected_raw_len: int = (
        Constants.TOR_V3_PUBLIC_KEY_BYTES + Constants.TOR_V3_CHECKSUM_BYTES + 1
    )
    if len(raw) != expected_raw_len:
        raise ValueError('Invalid onion address payload length.')

    public_key: bytes = raw[: Constants.TOR_V3_PUBLIC_KEY_BYTES]
    checksum: bytes = raw[
        Constants.TOR_V3_PUBLIC_KEY_BYTES : (
            Constants.TOR_V3_PUBLIC_KEY_BYTES + Constants.TOR_V3_CHECKSUM_BYTES
        )
    ]
    version: int = raw[-1]
    if version != Constants.TOR_V3_VERSION_BYTE:
        raise ValueError('Invalid onion address version.')

    expected_checksum: bytes = hashlib.sha3_256(
        b'.onion checksum' + public_key + bytes([version])
    ).digest()[: Constants.TOR_V3_CHECKSUM_BYTES]
    if checksum != expected_checksum:
        raise ValueError('Invalid onion address checksum.')

    return public_key


def ensure_onion_format(onion: str) -> str:
    """
    Ensures the given onion address has the correct '.onion' suffix.

    Args:
        onion (str): The onion address string.

    Returns:
        str: The fully formatted onion address.
    """
    clean: str = clean_onion(onion)
    return f'{clean}.onion'
