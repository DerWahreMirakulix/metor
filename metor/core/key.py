"""
Module for managing Ed25519 cryptographic keys for Tor and the Metor application.
"""

import hashlib
import os
import nacl.bindings

from metor.data.profile import ProfileManager
from metor.utils.constants import Constants


class KeyManager:
    """Manages Ed25519 cryptographic key generation and retrieval."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the KeyManager for a specific profile.

        Args:
            pm (ProfileManager): The profile manager instance to determine directory paths.
        """
        self._pm: ProfileManager = pm
        self._hs_dir: str = self._pm.get_hidden_service_dir()

    def generate_keys(self) -> None:
        """
        Generates both Metor application keys and Tor hidden service keys if they do not exist.
        """
        metor_key_path: str = os.path.join(self._hs_dir, Constants.METOR_SECRET_KEY)
        tor_sec_path: str = os.path.join(self._hs_dir, Constants.TOR_SECRET_KEY)
        tor_pub_path: str = os.path.join(self._hs_dir, Constants.TOR_PUBLIC_KEY)

        if os.path.exists(metor_key_path) and os.path.exists(tor_sec_path):
            return

        seed: bytes = os.urandom(32)
        public_key, pynacl_secret_key = nacl.bindings.crypto_sign_seed_keypair(seed)

        h: bytes = hashlib.sha512(seed).digest()
        scalar: bytearray = bytearray(h[:32])
        scalar[0] &= 248
        scalar[31] &= 127
        scalar[31] |= 64
        expanded_key: bytes = bytes(scalar) + h[32:]

        with open(metor_key_path, 'wb') as f:
            f.write(pynacl_secret_key)

        with open(tor_sec_path, 'wb') as f:
            f.write(b'== ed25519v1-secret: type0 ==\x00\x00\x00')
            f.write(expanded_key)

        with open(tor_pub_path, 'wb') as f:
            f.write(b'== ed25519v1-public: type0 ==\x00\x00\x00')
            f.write(public_key)

    def get_metor_key(self) -> bytes:
        """
        Retrieves the Metor secret key from disk.

        Returns:
            bytes: The PyNaCl secret key.
        """
        key_path: str = os.path.join(self._hs_dir, Constants.METOR_SECRET_KEY)
        with open(key_path, 'rb') as f:
            return f.read()
