"""
Module handling cryptographic operations for Tor connection handshakes.
Responsible for signing and verifying Ed25519 challenges.
"""

import base64
import nacl.bindings
from typing import Optional

from metor.core import KeyManager
from metor.utils import clean_onion


class Crypto:
    """Handles the cryptographic signing and verification for peer authentication."""

    def __init__(self, km: KeyManager) -> None:
        """
        Initializes the Crypto module.

        Args:
            km (KeyManager): The key manager to access local secret keys.
        """
        self._km: KeyManager = km

    def sign_challenge(self, challenge_hex: str) -> Optional[str]:
        """
        Signs a cryptographic challenge using the local Ed25519 secret key.

        Args:
            challenge_hex (str): The random challenge string in hexadecimal format.

        Returns:
            Optional[str]: The resulting signature in hex format, or None if signing fails.
        """
        try:
            pynacl_secret_key: bytes = self._km.get_metor_key()
            signed_message: bytes = nacl.bindings.crypto_sign(
                challenge_hex.encode('utf-8'), pynacl_secret_key
            )
            return signed_message[:64].hex()
        except Exception:
            return None

    def verify_signature(
        self, remote_onion: str, challenge_hex: str, signature_hex: str
    ) -> bool:
        """
        Verifies a signature payload received from a remote peer against their onion address.

        Args:
            remote_onion (str): The public .onion address of the remote peer.
            challenge_hex (str): The original challenge string that was sent.
            signature_hex (str): The signature provided by the remote peer.

        Returns:
            bool: True if the signature is valid and matches the onion address, False otherwise.
        """
        try:
            onion_str: str = clean_onion(remote_onion).upper()

            if len(onion_str) != 56:
                return False

            pad_len: int = 8 - (len(onion_str) % 8)
            if pad_len != 8:
                onion_str += '=' * pad_len

            public_key: bytes = base64.b32decode(onion_str)[:32]
            signature: bytes = bytes.fromhex(signature_hex)

            nacl.bindings.crypto_sign_open(
                signature + challenge_hex.encode('utf-8'), public_key
            )
            return True

        except Exception:
            return False
