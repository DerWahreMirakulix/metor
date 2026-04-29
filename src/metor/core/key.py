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
from metor.utils import Constants, secure_clear_buffer


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
        self._hs_dir: Path = self._pm.paths.get_hidden_service_dir()
        self._password: Optional[bytearray] = None
        if password is not None:
            self._password = bytearray(password.encode('utf-8'))
        self._salt_file: Path = self._hs_dir / 'crypto.salt'

    def get_or_create_password_salt(self) -> bytes:
        """
        Loads the persisted password salt or creates it on first encrypted use.

        Args:
            None

        Returns:
            bytes: The persisted salt bytes.
        """
        if not self._salt_file.exists():
            salt: bytes = nacl.utils.random(nacl.pwhash.argon2i.SALTBYTES)
            with self._salt_file.open('wb') as f:
                f.write(salt)
            self._salt_file.chmod(0o600)
            return salt

        with self._salt_file.open('rb') as f:
            return f.read()

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

        salt: bytes = self.get_or_create_password_salt()

        derived_key: bytearray = bytearray(
            nacl.pwhash.argon2i.kdf(
                nacl.secret.SecretBox.KEY_SIZE,
                bytes(self._password),
                salt,
                opslimit=nacl.pwhash.argon2i.OPSLIMIT_SENSITIVE,
                memlimit=nacl.pwhash.argon2i.MEMLIMIT_SENSITIVE,
            )
        )
        try:
            return nacl.secret.SecretBox(bytes(derived_key))
        finally:
            secure_clear_buffer(derived_key)

    def clear_sensitive_state(self) -> None:
        """
        Overwrites any retained password-derived runtime state before release.

        Args:
            None

        Returns:
            None
        """
        if self._password is None:
            return

        secure_clear_buffer(self._password)
        self._password = None

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

        if (
            metor_key_path.exists()
            and tor_sec_enc_path.exists()
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

    def has_metor_key(self) -> bool:
        """
        Checks whether the encrypted Metor secret key already exists on disk.

        Args:
            None

        Returns:
            bool: True if the key file exists.
        """
        key_path: Path = self._hs_dir / Constants.METOR_SECRET_KEY
        return key_path.exists()

    def has_any_key_material(self) -> bool:
        """
        Checks whether any persisted key material already exists on disk.

        Args:
            None

        Returns:
            bool: True if any key file exists.
        """
        key_paths: tuple[Path, ...] = (
            self._hs_dir / Constants.METOR_SECRET_KEY,
            self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc',
            self._hs_dir / Constants.TOR_PUBLIC_KEY,
            self._salt_file,
        )
        return any(path.exists() for path in key_paths)

    def has_complete_key_material(self) -> bool:
        """
        Checks whether the full persisted key set exists on disk.

        Args:
            None

        Returns:
            bool: True if all required persisted key files exist.
        """
        required_paths: tuple[Path, ...] = (
            self._hs_dir / Constants.METOR_SECRET_KEY,
            self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc',
            self._hs_dir / Constants.TOR_PUBLIC_KEY,
        )
        return all(path.exists() for path in required_paths)

    def rewrite_password_protection(self, new_password: Optional[str]) -> None:
        """
        Rewrites the persisted key material using a new storage protection mode.

        Args:
            new_password (Optional[str]): The target password, or None for plaintext storage.

        Raises:
            ValueError: If key material is incomplete.

        Returns:
            None
        """
        if not self.has_any_key_material():
            return
        if not self.has_complete_key_material():
            raise ValueError('Incomplete key material cannot be migrated safely.')

        metor_key_path: Path = self._hs_dir / Constants.METOR_SECRET_KEY
        tor_key_path: Path = self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc'
        tor_pub_path: Path = self._hs_dir / Constants.TOR_PUBLIC_KEY

        metor_secret: bytes = self.get_metor_key()
        tor_secret: bytes = self.get_decrypted_tor_key()
        tor_public: bytes = tor_pub_path.read_bytes()

        self._salt_file.unlink(missing_ok=True)
        target_box: Optional[nacl.secret.SecretBox] = KeyManager(
            self._pm,
            new_password,
        )._get_encryption_box()

        persisted_metor: bytes = (
            target_box.encrypt(metor_secret) if target_box else metor_secret
        )
        persisted_tor: bytes = (
            target_box.encrypt(tor_secret) if target_box else tor_secret
        )

        with metor_key_path.open('wb') as handle:
            handle.write(persisted_metor)
        metor_key_path.chmod(0o600)

        with tor_key_path.open('wb') as handle:
            handle.write(persisted_tor)
        tor_key_path.chmod(0o600)

        with tor_pub_path.open('wb') as handle:
            handle.write(tor_public)
        tor_pub_path.chmod(0o600)

        self.clear_sensitive_state()
        if new_password is not None:
            self._password = bytearray(new_password.encode('utf-8'))

        if new_password is None:
            self._salt_file.unlink(missing_ok=True)

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

        with key_path.open('rb') as f:
            data: bytes = f.read()

        box: Optional[nacl.secret.SecretBox] = self._get_encryption_box()
        if box:
            return box.decrypt(data)
        return data
