"""
Module for managing Ed25519 cryptographic keys for Tor and the Metor application.
Implements strong password-based encryption for keys at rest (Argon2i + SecretBox).
"""

import hashlib
import os
import nacl.bindings
import nacl.pwhash
import nacl.secret
import nacl.utils
from typing import Optional

from metor.data.profile import ProfileManager
from metor.utils.constants import Constants


class KeyManager:
    """Manages Ed25519 cryptographic key generation, encryption, and retrieval."""

    def __init__(self, pm: ProfileManager, password: Optional[str] = None) -> None:
        """
        Initializes the KeyManager for a specific profile.

        Args:
            pm (ProfileManager): The profile manager instance to determine directory paths.
            password (Optional[str]): Master password for key encryption/decryption.
        """
        self._pm: ProfileManager = pm
        self._hs_dir: str = self._pm.get_hidden_service_dir()
        self._password: Optional[str] = password
        self._salt_file: str = os.path.join(self._hs_dir, 'crypto.salt')

    def _get_encryption_box(self) -> Optional[nacl.secret.SecretBox]:
        """
        Derives an encryption key from the master password and returns a SecretBox.

        Returns:
            Optional[nacl.secret.SecretBox]: The encryption box, or None if no password exists.
        """
        if not self._password:
            return None

        if not os.path.exists(self._salt_file):
            salt: bytes = nacl.utils.random(nacl.pwhash.argon2i.SALTBYTES)
            with open(self._salt_file, 'wb') as f:
                f.write(salt)
        else:
            with open(self._salt_file, 'rb') as f:
                salt = f.read()

        key: bytes = nacl.pwhash.argon2i.kdf(
            nacl.secret.SecretBox.KEY_SIZE,
            self._password.encode('utf-8'),
            salt,
            opslimit=nacl.pwhash.argon2i.OPSLIMIT_SENSITIVE,
            memlimit=nacl.pwhash.argon2i.MEMLIMIT_SENSITIVE,
        )
        return nacl.secret.SecretBox(key)

    def generate_keys(self) -> None:
        """
        Generates Metor application keys and Tor hidden service keys if they do not exist.
        Encrypts the keys on disk if a master password is set.
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

        box: Optional[nacl.secret.SecretBox] = self._get_encryption_box()

        raw_tor_sec: bytes = b'== ed25519v1-secret: type0 ==\x00\x00\x00' + expanded_key
        raw_tor_pub: bytes = b'== ed25519v1-public: type0 ==\x00\x00\x00' + public_key

        if box:
            pynacl_secret_key = box.encrypt(pynacl_secret_key)
            raw_tor_sec = box.encrypt(raw_tor_sec)

        with open(metor_key_path, 'wb') as f:
            f.write(pynacl_secret_key)

        with open(tor_sec_path, 'wb') as f:
            f.write(raw_tor_sec)

        with open(tor_pub_path, 'wb') as f:
            f.write(raw_tor_pub)

    def get_metor_key(self) -> bytes:
        """
        Retrieves and decrypts the Metor secret key from disk.

        Returns:
            bytes: The decrypted PyNaCl secret key.
        """
        key_path: str = os.path.join(self._hs_dir, Constants.METOR_SECRET_KEY)
        with open(key_path, 'rb') as f:
            data: bytes = f.read()

        box: Optional[nacl.secret.SecretBox] = self._get_encryption_box()
        if box:
            return box.decrypt(data)
        return data

    def get_decrypted_tor_key(self) -> bytes:
        """
        Retrieves and decrypts the Tor secret key.
        This is used for memory-injecting the key securely to the Tor process.

        Returns:
            bytes: The decrypted raw Tor secret key format.
        """
        key_path: str = os.path.join(self._hs_dir, Constants.TOR_SECRET_KEY)
        with open(key_path, 'rb') as f:
            data: bytes = f.read()

        box: Optional[nacl.secret.SecretBox] = self._get_encryption_box()
        if box:
            return box.decrypt(data)
        return data
