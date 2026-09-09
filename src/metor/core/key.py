"""Profile runtime keys plus encrypted Ed25519 identity-key persistence."""

import hashlib
import secrets
from pathlib import Path
from typing import Optional

import nacl.bindings
import nacl.secret

from metor.core.profile_keys import (
    PROFILE_MASTER_KEY_BYTES,
    InvalidCredentialError,
    InvalidKeyslotError,
    KeyProtector,
    PasswordKeyProtector,
    ProfileKeySet,
    ProtectedKeyMissingError,
)
from metor.data.profile import ProfileManager
from metor.utils import Constants, secure_clear_buffer


class KeyManager:
    """Owns unlocked profile keys and encrypted long-lived identity material."""

    def __init__(
        self,
        pm: ProfileManager,
        password: Optional[str] = None,
        protector: Optional[KeyProtector] = None,
    ) -> None:
        """Initializes a lazy profile-key runtime.

        Args:
            pm (ProfileManager): Active profile manager.
            password (Optional[str]): Password used only to unwrap or create the PMK.
            protector (Optional[KeyProtector]): Injected PMK protection provider.

        Returns:
            None
        """
        self._pm = pm
        self._hs_dir: Path = pm.paths.get_hidden_service_dir()
        self._password: Optional[bytearray] = (
            bytearray(password.encode('utf-8')) if password is not None else None
        )
        self._protector: KeyProtector = protector or PasswordKeyProtector(
            pm.paths.get_keyslot_file()
        )
        self._profile_keys: Optional[ProfileKeySet] = None

    def _has_legacy_or_persistent_data(self) -> bool:
        """Detects data that must never receive a newly invented PMK.

        Args:
            None

        Returns:
            bool: True when profile data predates or outlives a missing keyslot.
        """
        paths = (
            self._pm.paths.get_db_file(),
            self._hs_dir / Constants.METOR_SECRET_KEY,
            self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc',
        )
        return any(path.exists() for path in paths)

    def unlock_profile_keys(self) -> None:
        """Recovers or initially creates the encrypted profile key hierarchy.

        Args:
            None

        Returns:
            None
        """
        if self._profile_keys is not None:
            return
        if self._pm.uses_plaintext_storage() and not self._protector.exists:
            return
        if self._password is None or not self._password:
            raise InvalidCredentialError('The profile password is required.')
        credential = self._password.decode('utf-8')
        if self._protector.exists:
            pmk = self._protector.unprotect(credential)
        else:
            if self._has_legacy_or_persistent_data():
                raise ProtectedKeyMissingError(
                    'Encrypted profile data exists without a supported keyslot.'
                )
            pmk = bytearray(secrets.token_bytes(PROFILE_MASTER_KEY_BYTES))
            try:
                self._protector.protect(pmk, credential)
            except Exception:
                secure_clear_buffer(pmk)
                raise
        try:
            self._profile_keys = ProfileKeySet.derive(pmk)
        finally:
            secure_clear_buffer(pmk)

    def _secret_box(self) -> Optional[nacl.secret.SecretBox]:
        """Returns the profile-secret encryption box for encrypted profiles.

        Args:
            None

        Returns:
            Optional[nacl.secret.SecretBox]: Secret-domain box or None for plaintext.
        """
        if (
            self._pm.uses_plaintext_storage()
            and self._profile_keys is None
            and not self._protector.exists
        ):
            return None
        self.unlock_profile_keys()
        if self._profile_keys is None:
            return None
        return nacl.secret.SecretBox(self._profile_keys.secret_key())

    def get_database_key(self) -> Optional[bytes]:
        """Returns the PMK-derived SQLCipher key when storage is encrypted.

        Args:
            None

        Returns:
            Optional[bytes]: Database-domain key or None for plaintext storage.
        """
        if self._pm.uses_plaintext_storage() and not self._protector.exists:
            return None
        self.unlock_profile_keys()
        if self._profile_keys is None:
            raise InvalidKeyslotError('Encrypted profile keys are unavailable.')
        return self._profile_keys.database_key()

    def get_blob_key(self) -> bytes:
        """Returns the PMK-derived external-blob encryption key.

        Args:
            None

        Returns:
            bytes: Blob-domain key.
        """
        self.unlock_profile_keys()
        if self._profile_keys is None:
            raise InvalidKeyslotError('Blob encryption requires an encrypted profile.')
        return self._profile_keys.blob_key()

    def get_secret_key(self) -> bytes:
        """Returns the PMK-derived sensitive-secret encryption key.

        Args:
            None

        Returns:
            bytes: Secret-domain key.
        """
        self.unlock_profile_keys()
        if self._profile_keys is None:
            raise InvalidKeyslotError(
                'Secret encryption requires an encrypted profile.'
            )
        return self._profile_keys.secret_key()

    def clear_sensitive_state(self) -> None:
        """Best-effort clears passwords, PMK, and all derived runtime keys.

        Args:
            None

        Returns:
            None
        """
        if self._profile_keys is not None:
            self._profile_keys.clear()
            self._profile_keys = None
        if self._password is not None:
            secure_clear_buffer(self._password)
            self._password = None

    def generate_keys(self) -> None:
        """Creates encrypted Metor and Tor identity keys when none exist.

        Args:
            None

        Returns:
            None
        """
        metor_key_path = self._hs_dir / Constants.METOR_SECRET_KEY
        tor_sec_enc_path = self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc'
        tor_pub_path = self._hs_dir / Constants.TOR_PUBLIC_KEY
        required = (metor_key_path, tor_sec_enc_path, tor_pub_path)
        if all(path.exists() for path in required):
            return
        if any(path.exists() for path in required):
            raise ValueError('Incomplete identity key material cannot be used safely.')

        seed = bytearray(secrets.token_bytes(32))
        try:
            public_key, signing_key = nacl.bindings.crypto_sign_seed_keypair(
                bytes(seed)
            )
            digest = hashlib.sha512(bytes(seed)).digest()
        finally:
            secure_clear_buffer(seed)
        scalar = bytearray(digest[:32])
        scalar[0] &= 248
        scalar[31] &= 127
        scalar[31] |= 64
        expanded_key = bytearray(bytes(scalar) + digest[32:])
        secure_clear_buffer(scalar)

        raw_tor_secret = bytearray(
            b'== ed25519v1-secret: type0 ==\x00\x00\x00' + bytes(expanded_key)
        )
        raw_tor_public = b'== ed25519v1-public: type0 ==\x00\x00\x00' + public_key
        secure_clear_buffer(expanded_key)
        box = self._secret_box()
        try:
            persisted_signing_key = (
                box.encrypt(signing_key) if box is not None else signing_key
            )
            persisted_tor_secret = (
                box.encrypt(bytes(raw_tor_secret))
                if box is not None
                else bytes(raw_tor_secret)
            )
        finally:
            secure_clear_buffer(raw_tor_secret)

        self._write_private_file(metor_key_path, persisted_signing_key)
        self._write_private_file(tor_sec_enc_path, persisted_tor_secret)
        self._write_private_file(tor_pub_path, raw_tor_public)

    @staticmethod
    def _write_private_file(path: Path, data: bytes) -> None:
        """Writes one owner-only key file.

        Args:
            path (Path): Destination key path.
            data (bytes): Persisted key bytes.

        Returns:
            None
        """
        with path.open('wb') as handle:
            handle.write(data)
        path.chmod(0o600)

    def get_metor_key(self) -> bytes:
        """Returns the decrypted Metor signing key.

        Args:
            None

        Returns:
            bytes: Ed25519 signing key.
        """
        data = (self._hs_dir / Constants.METOR_SECRET_KEY).read_bytes()
        box = self._secret_box()
        return box.decrypt(data) if box is not None else data

    def has_metor_key(self) -> bool:
        """Reports whether Metor identity key material exists.

        Args:
            None

        Returns:
            bool: True when the signing-key file exists.
        """
        return (self._hs_dir / Constants.METOR_SECRET_KEY).exists()

    def has_any_key_material(self) -> bool:
        """Reports whether any persistent identity or PMK material exists.

        Args:
            None

        Returns:
            bool: True when at least one key file exists.
        """
        paths = (
            self._hs_dir / Constants.METOR_SECRET_KEY,
            self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc',
            self._hs_dir / Constants.TOR_PUBLIC_KEY,
            self._pm.paths.get_keyslot_file(),
        )
        return any(path.exists() for path in paths)

    def has_complete_key_material(self) -> bool:
        """Reports whether all required persistent key files exist.

        Args:
            None

        Returns:
            bool: True when the profile key set is structurally complete.
        """
        required = [
            self._hs_dir / Constants.METOR_SECRET_KEY,
            self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc',
            self._hs_dir / Constants.TOR_PUBLIC_KEY,
        ]
        if (
            self._pm.uses_encrypted_storage()
            or self._protector.exists
            or self._profile_keys is not None
        ):
            required.append(self._pm.paths.get_keyslot_file())
        return all(path.exists() for path in required)

    def rewrap_password(self, new_password: str) -> None:
        """Rewraps the same PMK without changing database or content keys.

        Args:
            new_password (str): Replacement profile password.

        Returns:
            None
        """
        if self._password is None:
            raise InvalidCredentialError('The current profile password is unavailable.')
        old_password = self._password.decode('utf-8')
        self._protector.rewrap(old_password, new_password)
        secure_clear_buffer(self._password)
        self._password = bytearray(new_password.encode('utf-8'))

    def rewrite_password_protection(self, new_password: Optional[str]) -> None:
        """Converts identity files between encrypted and explicit plaintext mode.

        Args:
            new_password (Optional[str]): New password, or None for plaintext mode.

        Returns:
            None
        """
        if self._pm.uses_encrypted_storage():
            if new_password is not None:
                self.rewrap_password(new_password)
                return
            metor_secret = self.get_metor_key()
            tor_secret = self.get_decrypted_tor_key()
            self._write_private_file(
                self._hs_dir / Constants.METOR_SECRET_KEY, metor_secret
            )
            self._write_private_file(
                self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc', tor_secret
            )
            self.clear_sensitive_state()
            self._protector.destroy()
            return

        if new_password is None:
            return
        metor_path = self._hs_dir / Constants.METOR_SECRET_KEY
        tor_path = self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc'
        plaintext_metor_secret: Optional[bytes] = (
            metor_path.read_bytes() if metor_path.exists() else None
        )
        plaintext_tor_secret: Optional[bytes] = (
            tor_path.read_bytes() if tor_path.exists() else None
        )
        pmk = bytearray(secrets.token_bytes(PROFILE_MASTER_KEY_BYTES))
        try:
            self._protector.protect(pmk, new_password)
            self._profile_keys = ProfileKeySet.derive(pmk)
        finally:
            secure_clear_buffer(pmk)
        self._password = bytearray(new_password.encode('utf-8'))
        box = self._secret_box()
        if (
            box is not None
            and plaintext_metor_secret is not None
            and plaintext_tor_secret is not None
        ):
            self._write_private_file(metor_path, box.encrypt(plaintext_metor_secret))
            self._write_private_file(tor_path, box.encrypt(plaintext_tor_secret))

    def get_decrypted_tor_key(self) -> bytes:
        """Returns the decrypted Tor secret-key file for runtime provisioning.

        Args:
            None

        Returns:
            bytes: Raw Tor secret-key format.
        """
        data = (self._hs_dir / f'{Constants.TOR_SECRET_KEY}.enc').read_bytes()
        box = self._secret_box()
        return box.decrypt(data) if box is not None else data
