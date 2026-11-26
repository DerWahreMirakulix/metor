"""
Module handling cryptographic operations for Tor connection handshakes.
Responsible for signing and verifying Ed25519 challenges.
"""

import nacl.bindings
from typing import Optional

from metor.core.key import KeyManager
from metor.shared import decode_tor_v3_onion_public_key


class Crypto:
    """Handles the cryptographic signing and verification for peer authentication."""

    def __init__(self, km: KeyManager) -> None:
        """
        Initializes the Crypto module.

        Args:
            km (KeyManager): The key manager to access local secret keys.

        Returns:
            None
        """
        self._km: KeyManager = km

    def sign_challenge(self, proof: bytes) -> Optional[str]:
        """
        Signs a cryptographic challenge using the local Ed25519 secret key.

        Args:
            proof: Canonical, domain-separated peer handshake transcript.

        Returns:
            Optional[str]: The resulting signature in hex format, or None if signing fails.
        """
        try:
            pynacl_secret_key: bytes = self._km.get_metor_key()
            signed_message: bytes = nacl.bindings.crypto_sign(proof, pynacl_secret_key)
            return signed_message[: nacl.bindings.crypto_sign_BYTES].hex()
        except Exception:
            return None

    def verify_signature(
        self, remote_onion: str, proof: bytes, signature_hex: str
    ) -> bool:
        """
        Verifies a signature payload received from a remote peer against their onion address.

        Args:
            remote_onion (str): The public .onion address of the remote peer.
            proof: Locally reconstructed, domain-separated peer handshake transcript.
            signature_hex (str): The signature provided by the remote peer.

        Returns:
            bool: True if the signature is valid and matches the onion address, False otherwise.
        """
        try:
            public_key: bytes = decode_tor_v3_onion_public_key(remote_onion)
            if len(signature_hex) != nacl.bindings.crypto_sign_BYTES * 2:
                return False
            signature: bytes = bytes.fromhex(signature_hex)
            if len(signature) != nacl.bindings.crypto_sign_BYTES:
                return False

            nacl.bindings.crypto_sign_open(signature + proof, public_key)
            return True

        except Exception:
            return False
