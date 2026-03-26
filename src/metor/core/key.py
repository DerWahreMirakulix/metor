"""
Module for managing Ed25519 cryptographic keys for Tor and the Metor application.
Implements strong password-based encryption for keys at rest (Argon2i + SecretBox).
"""

import hashlib
import secrets
import nacl.bindings
import nacl.pwhash
import nacl.secret
import nacl.utils
from pathlib import Path
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

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._hs_dir: Path = Path(self._pm.get_hidden_service_dir())
        self._password: Optional[str] = password
        self._salt_file: Path = self._hs_dir / 'crypto.salt'

    def _get_encryption_box(self) -> Optional[nacl.secret.SecretBox]:
        """
        Derives an encryption key from the master password and returns a SecretBox.

        Args:
            None

        Returns:
            Optional[nacl.secret.SecretBox]: The encryption box, or None if no password exists.
        """
        if not self._password:
            return None

        if not self._salt_file.exists():
            salt: bytes = nacl.utils.random(nacl.pwhash.argon2i.SALTBYTES)
            with self._salt_file.open('wb') as f:
                f.write(salt)
            self._salt_file.chmod(0o600)
        else:
            with self._salt_file.open('rb') as f:
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
        Encrypts the keys on disk if a master password is set. Uses cryptographically secure PRNG.
        Tor keys are stored with an .enc extension to fulfill Data-At-Rest requirements.

        Args:
            None

        Returns:
            None
        """
        metor_key_path: Path = self._hs_dir / Constants.METOR_SECRET_KEY
        tor_sec_enc_path: Path = self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc'
        tor_pub_path: Path = self._hs_dir / Constants.TOR_PUBLIC_KEY

        # Fallback for older databases during migration
        legacy_tor_sec_path: Path = self._hs_dir / Constants.TOR_SECRET_KEY

        if (
            metor_key_path.exists()
            and (tor_sec_enc_path.exists() or legacy_tor_sec_path.exists())
            and tor_pub_path.exists()
        ):
            return

        seed: bytes = secrets.token_bytes(32)
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

        with metor_key_path.open('wb') as f:
            f.write(pynacl_secret_key)
        metor_key_path.chmod(0o600)

        # Always save the encrypted master key safely at rest
        with tor_sec_enc_path.open('wb') as f:
            f.write(raw_tor_sec)
        tor_sec_enc_path.chmod(0o600)

        # Write public key (plaintext, required by Tor alongside the secret key)
        with tor_pub_path.open('wb') as f:
            f.write(raw_tor_pub)
        tor_pub_path.chmod(0o600)

    def get_metor_key(self) -> bytes:
        """
        Retrieves and decrypts the Metor secret key from disk.

        Args:
            None

        Returns:
            bytes: The decrypted PyNaCl secret key.
        """
        key_path: Path = self._hs_dir / Constants.METOR_SECRET_KEY
        with key_path.open('rb') as f:
            data: bytes = f.read()

        box: Optional[nacl.secret.SecretBox] = self._get_encryption_box()
        if box:
            return box.decrypt(data)
        return data

    def get_decrypted_tor_key(self) -> bytes:
        """
        Retrieves and decrypts the Tor secret key.
        This is used for provisioning the plaintext key to Tor exclusively during runtime.

        Args:
            None

        Returns:
            bytes: The decrypted raw Tor secret key format.
        """
        key_path: Path = self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc'
        if not key_path.exists():
            # Support legacy paths if the `.enc` suffix hasn't been migrated
            key_path = self._hs_dir / Constants.TOR_SECRET_KEY

        with key_path.open('rb') as f:
            data: bytes = f.read()

        box: Optional[nacl.secret.SecretBox] = self._get_encryption_box()
        if box:
            return box.decrypt(data)
        return data
