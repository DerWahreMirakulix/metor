"""Profile master-key protection and domain-separated runtime key derivation."""

import base64
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

import nacl.exceptions
import nacl.hash
import nacl.pwhash
import nacl.secret
import nacl.utils
from nacl.encoding import RawEncoder

from metor.core.api import JsonValue
from metor.utils import secure_clear_buffer, secure_shred_file

PROFILE_MASTER_KEY_BYTES = 32
DERIVED_KEY_BYTES = 32
KEYSLOT_FORMAT = 'metor-password-keyslot'
KEYSLOT_VERSION = 1
KEYSLOT_KDF = 'argon2id'
KEYSLOT_WRAP = 'xsalsa20-poly1305-secretbox'
DB_KEY_CONTEXT = b'metor/db/v1'
SECRET_KEY_CONTEXT = b'metor/secrets/v1'
BLOB_KEY_CONTEXT = b'metor/blobs/v1'
PASSWORD_KDF_OPSLIMIT = nacl.pwhash.argon2id.OPSLIMIT_INTERACTIVE
PASSWORD_KDF_MEMLIMIT = nacl.pwhash.argon2id.MEMLIMIT_INTERACTIVE
MIN_PASSWORD_KDF_OPSLIMIT = nacl.pwhash.argon2id.OPSLIMIT_MIN
MAX_PASSWORD_KDF_OPSLIMIT = nacl.pwhash.argon2id.OPSLIMIT_MODERATE
MIN_PASSWORD_KDF_MEMLIMIT = nacl.pwhash.argon2id.MEMLIMIT_MIN
MAX_PASSWORD_KDF_MEMLIMIT = nacl.pwhash.argon2id.MEMLIMIT_MODERATE
MAX_KEYSLOT_BYTES = 16_384


class KeyProtectorError(ValueError):
    """Base error for protected PMK operations."""


class InvalidCredentialError(KeyProtectorError):
    """Raised when a credential cannot authenticate a protected PMK."""


class InvalidKeyslotError(KeyProtectorError):
    """Raised when protected PMK metadata is invalid or unsupported."""


class ProtectedKeyMissingError(KeyProtectorError):
    """Raised when an encrypted profile has no protected PMK."""


class KeyProtector(Protocol):
    """Persistence boundary for software or future hardware PMK protection."""

    @property
    def exists(self) -> bool:
        """Reports whether protected PMK material exists.

        Args:
            None

        Returns:
            bool: True when a protected PMK can be addressed.
        """
        ...

    def protect(self, pmk: bytes | bytearray, credential: str) -> None:
        """Protects a new PMK under the supplied credential.

        Args:
            pmk (bytes | bytearray): Random profile master key.
            credential (str): Protector-specific unlock credential.

        Returns:
            None
        """
        ...

    def unprotect(self, credential: str) -> bytearray:
        """Recovers the PMK into mutable runtime memory.

        Args:
            credential (str): Protector-specific unlock credential.

        Returns:
            bytearray: Recovered PMK.
        """
        ...

    def rewrap(self, old_credential: str, new_credential: str) -> None:
        """Atomically rewraps the same PMK under a new credential.

        Args:
            old_credential (str): Current unlock credential.
            new_credential (str): Replacement unlock credential.

        Returns:
            None
        """
        ...

    def destroy(self) -> None:
        """Destroys the addressable protected PMK material.

        Args:
            None

        Returns:
            None
        """
        ...


def _derive_key(root_key: bytes | bytearray, context: bytes) -> bytearray:
    """Derives one domain-separated key with libsodium BLAKE2b.

    Args:
        root_key (bytes | bytearray): Root key material.
        context (bytes): Stable versioned domain label.

    Returns:
        bytearray: Mutable derived key.
    """
    derived = nacl.hash.blake2b(
        context,
        key=bytes(root_key),
        digest_size=DERIVED_KEY_BYTES,
        encoder=RawEncoder,
    )
    return bytearray(derived)


@dataclass(repr=False)
class ProfileKeySet:
    """Unlocked PMK and independently derived profile encryption keys."""

    _pmk: bytearray = field(repr=False)
    _db_key: bytearray = field(repr=False)
    _secret_key: bytearray = field(repr=False)
    _blob_key: bytearray = field(repr=False)
    _cleared: bool = field(default=False, repr=False)

    @classmethod
    def derive(cls, pmk: bytes | bytearray) -> 'ProfileKeySet':
        """Derives all runtime keys from one PMK.

        Args:
            pmk (bytes | bytearray): Profile master key.

        Returns:
            ProfileKeySet: Mutable runtime key hierarchy.
        """
        if len(pmk) != PROFILE_MASTER_KEY_BYTES:
            raise ValueError('Profile master key has an invalid length.')
        return cls(
            _pmk=bytearray(pmk),
            _db_key=_derive_key(pmk, DB_KEY_CONTEXT),
            _secret_key=_derive_key(pmk, SECRET_KEY_CONTEXT),
            _blob_key=_derive_key(pmk, BLOB_KEY_CONTEXT),
        )

    def _copy(self, value: bytearray) -> bytes:
        """Returns one derived key only while the hierarchy is active.

        Args:
            value (bytearray): Mutable key buffer.

        Returns:
            bytes: A short-lived immutable key copy.
        """
        if self._cleared:
            raise RuntimeError('Profile keys have been cleared.')
        return bytes(value)

    def pmk(self) -> bytes:
        """Returns a short-lived PMK copy for protector operations.

        Args:
            None

        Returns:
            bytes: Profile master key copy.
        """
        return self._copy(self._pmk)

    def database_key(self) -> bytes:
        """Returns the SQLCipher domain key.

        Args:
            None

        Returns:
            bytes: Database encryption key.
        """
        return self._copy(self._db_key)

    def secret_key(self) -> bytes:
        """Returns the profile-secret domain key.

        Args:
            None

        Returns:
            bytes: Secret encryption key.
        """
        return self._copy(self._secret_key)

    def blob_key(self) -> bytes:
        """Returns the external-blob domain key.

        Args:
            None

        Returns:
            bytes: Blob encryption key.
        """
        return self._copy(self._blob_key)

    def clear(self) -> None:
        """Best-effort clears all mutable runtime key buffers.

        Args:
            None

        Returns:
            None
        """
        if self._cleared:
            return
        for value in (self._blob_key, self._secret_key, self._db_key, self._pmk):
            secure_clear_buffer(value)
        self._cleared = True


class PasswordKeyProtector:
    """Argon2id and SecretBox software protector for one profile PMK."""

    def __init__(self, keyslot_path: Path) -> None:
        """Binds the protector to one versioned keyslot file.

        Args:
            keyslot_path (Path): Protected keyslot path.

        Returns:
            None
        """
        self._keyslot_path = keyslot_path

    @property
    def exists(self) -> bool:
        """Reports whether the keyslot exists.

        Args:
            None

        Returns:
            bool: True when the keyslot is a regular file.
        """
        return self._keyslot_path.is_file()

    @staticmethod
    def _derive_kek(
        credential: str,
        salt: bytes,
        opslimit: int,
        memlimit: int,
    ) -> bytearray:
        """Derives a Key Encryption Key with validated Argon2id limits.

        Args:
            credential (str): User unlock password.
            salt (bytes): Per-keyslot random salt.
            opslimit (int): Persisted Argon2id operation limit.
            memlimit (int): Persisted Argon2id memory limit in bytes.

        Returns:
            bytearray: Mutable KEK buffer.
        """
        if not credential:
            raise InvalidCredentialError('The profile password cannot be empty.')
        password = bytearray(credential.encode('utf-8'))
        try:
            return bytearray(
                nacl.pwhash.argon2id.kdf(
                    nacl.secret.SecretBox.KEY_SIZE,
                    bytes(password),
                    salt,
                    opslimit=opslimit,
                    memlimit=memlimit,
                )
            )
        finally:
            secure_clear_buffer(password)

    @staticmethod
    def _decode_field(value: object, expected_length: int | None = None) -> bytes:
        """Decodes one strict Base64 keyslot field.

        Args:
            value (object): Candidate JSON value.
            expected_length (int | None): Required decoded length.

        Returns:
            bytes: Decoded field.
        """
        if not isinstance(value, str):
            raise InvalidKeyslotError('Keyslot binary field is invalid.')
        try:
            decoded = base64.b64decode(value, validate=True)
        except ValueError as exc:
            raise InvalidKeyslotError('Keyslot Base64 field is invalid.') from exc
        if expected_length is not None and len(decoded) != expected_length:
            raise InvalidKeyslotError('Keyslot binary field has an invalid length.')
        return decoded

    def _build_document(self, pmk: bytes | bytearray, credential: str) -> bytes:
        """Builds one authenticated versioned keyslot document.

        Args:
            pmk (bytes | bytearray): Profile master key.
            credential (str): User unlock password.

        Returns:
            bytes: Serialized protected keyslot.
        """
        if len(pmk) != PROFILE_MASTER_KEY_BYTES:
            raise ValueError('Profile master key has an invalid length.')
        salt = nacl.utils.random(nacl.pwhash.argon2id.SALTBYTES)
        nonce = nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE)
        kek = self._derive_kek(
            credential,
            salt,
            PASSWORD_KDF_OPSLIMIT,
            PASSWORD_KDF_MEMLIMIT,
        )
        try:
            ciphertext = (
                nacl.secret.SecretBox(bytes(kek)).encrypt(bytes(pmk), nonce).ciphertext
            )
        finally:
            secure_clear_buffer(kek)
        document: dict[str, JsonValue] = {
            'format': KEYSLOT_FORMAT,
            'version': KEYSLOT_VERSION,
            'kdf': {
                'algorithm': KEYSLOT_KDF,
                'opslimit': PASSWORD_KDF_OPSLIMIT,
                'memlimit': PASSWORD_KDF_MEMLIMIT,
                'salt': base64.b64encode(salt).decode('ascii'),
            },
            'wrap': {
                'algorithm': KEYSLOT_WRAP,
                'nonce': base64.b64encode(nonce).decode('ascii'),
                'ciphertext': base64.b64encode(ciphertext).decode('ascii'),
            },
        }
        return json.dumps(document, sort_keys=True, separators=(',', ':')).encode(
            'utf-8'
        )

    def _atomic_write(
        self,
        document: bytes,
        validation_credential: str | None = None,
        expected_pmk: bytes | bytearray | None = None,
    ) -> None:
        """Persists a complete replacement keyslot atomically.

        Args:
            document (bytes): Serialized keyslot document.
            validation_credential (str | None): Credential used to read back a
                staged replacement before activation.
            expected_pmk (bytes | bytearray | None): PMK the staged replacement
                must recover before activation.

        Returns:
            None
        """
        parent = self._keyslot_path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent.chmod(0o700)
        temp_path = parent / f'.keyslot-{secrets.token_hex(8)}.tmp'
        try:
            with temp_path.open('xb') as handle:
                handle.write(document)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.chmod(0o600)
            if validation_credential is not None and expected_pmk is not None:
                recovered_pmk = PasswordKeyProtector(temp_path).unprotect(
                    validation_credential
                )
                try:
                    if not hmac.compare_digest(recovered_pmk, expected_pmk):
                        raise InvalidKeyslotError(
                            'Replacement keyslot recovered an unexpected PMK.'
                        )
                finally:
                    secure_clear_buffer(recovered_pmk)
            temp_path.replace(self._keyslot_path)
            self._keyslot_path.chmod(0o600)
            if os.name != 'nt':
                try:
                    directory_fd = os.open(parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except OSError:
                    pass
        finally:
            temp_path.unlink(missing_ok=True)

    def protect(self, pmk: bytes | bytearray, credential: str) -> None:
        """Protects a new PMK and refuses to overwrite an existing keyslot.

        Args:
            pmk (bytes | bytearray): Random profile master key.
            credential (str): User unlock password.

        Returns:
            None
        """
        if self.exists:
            raise KeyProtectorError('Protected profile key material already exists.')
        self._atomic_write(self._build_document(pmk, credential))

    def _read_document(self) -> tuple[bytes, bytes, bytes, int, int]:
        """Loads and strictly validates supported keyslot metadata.

        Args:
            None

        Returns:
            tuple[bytes, bytes, bytes, int, int]: Salt, nonce, ciphertext, and
                validated Argon2id limits.
        """
        if not self.exists:
            raise ProtectedKeyMissingError('Protected profile key material is missing.')
        try:
            if self._keyslot_path.stat().st_size > MAX_KEYSLOT_BYTES:
                raise InvalidKeyslotError('Keyslot document exceeds its size limit.')
            decoded: object = json.loads(self._keyslot_path.read_text('utf-8'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidKeyslotError('Keyslot document is malformed.') from exc
        if not isinstance(decoded, dict):
            raise InvalidKeyslotError('Keyslot document is malformed.')
        document = cast(dict[str, object], decoded)
        if set(document) != {'format', 'version', 'kdf', 'wrap'}:
            raise InvalidKeyslotError('Keyslot fields are invalid.')
        if (
            document['format'] != KEYSLOT_FORMAT
            or document['version'] != KEYSLOT_VERSION
        ):
            raise InvalidKeyslotError('Keyslot format or version is unsupported.')
        kdf = document['kdf']
        wrap = document['wrap']
        if not isinstance(kdf, dict) or not isinstance(wrap, dict):
            raise InvalidKeyslotError('Keyslot algorithm metadata is invalid.')
        if set(kdf) != {'algorithm', 'opslimit', 'memlimit', 'salt'} or set(wrap) != {
            'algorithm',
            'nonce',
            'ciphertext',
        }:
            raise InvalidKeyslotError('Keyslot algorithm fields are invalid.')
        if kdf['algorithm'] != KEYSLOT_KDF or wrap['algorithm'] != KEYSLOT_WRAP:
            raise InvalidKeyslotError('Keyslot algorithms are unsupported.')
        opslimit = kdf['opslimit']
        memlimit = kdf['memlimit']
        if (
            type(opslimit) is not int
            or type(memlimit) is not int
            or not MIN_PASSWORD_KDF_OPSLIMIT <= opslimit <= MAX_PASSWORD_KDF_OPSLIMIT
            or not MIN_PASSWORD_KDF_MEMLIMIT <= memlimit <= MAX_PASSWORD_KDF_MEMLIMIT
        ):
            raise InvalidKeyslotError('Keyslot KDF parameters are unsafe.')
        salt = self._decode_field(kdf['salt'], nacl.pwhash.argon2id.SALTBYTES)
        nonce = self._decode_field(wrap['nonce'], nacl.secret.SecretBox.NONCE_SIZE)
        ciphertext = self._decode_field(wrap['ciphertext'])
        if len(ciphertext) != PROFILE_MASTER_KEY_BYTES + nacl.secret.SecretBox.MACBYTES:
            raise InvalidKeyslotError('Protected PMK has an invalid length.')
        return salt, nonce, ciphertext, opslimit, memlimit

    def unprotect(self, credential: str) -> bytearray:
        """Authenticates the password and recovers the PMK.

        Args:
            credential (str): User unlock password.

        Returns:
            bytearray: Recovered PMK.
        """
        salt, nonce, ciphertext, opslimit, memlimit = self._read_document()
        kek = self._derive_kek(credential, salt, opslimit, memlimit)
        try:
            try:
                pmk = nacl.secret.SecretBox(bytes(kek)).decrypt(ciphertext, nonce)
            except nacl.exceptions.CryptoError as exc:
                raise InvalidCredentialError('Invalid profile password.') from exc
        finally:
            secure_clear_buffer(kek)
        if len(pmk) != PROFILE_MASTER_KEY_BYTES:
            raise InvalidKeyslotError('Recovered PMK has an invalid length.')
        return bytearray(pmk)

    def rewrap(self, old_credential: str, new_credential: str) -> None:
        """Atomically rewraps the unchanged PMK with a fresh salt and nonce.

        Args:
            old_credential (str): Current profile password.
            new_credential (str): Replacement profile password.

        Returns:
            None
        """
        pmk = self.unprotect(old_credential)
        try:
            self._atomic_write(
                self._build_document(pmk, new_credential),
                validation_credential=new_credential,
                expected_pmk=pmk,
            )
        finally:
            secure_clear_buffer(pmk)

    def destroy(self) -> None:
        """Best-effort shreds, unlinks, and directory-syncs the software keyslot.

        This is software-only destruction and cannot guarantee physical erasure on
        flash, copy-on-write filesystems, snapshots, or backups.

        Args:
            None

        Returns:
            None
        """
        if not self._keyslot_path.is_file():
            return
        secure_shred_file(self._keyslot_path)
        if os.name != 'nt':
            try:
                directory_fd = os.open(self._keyslot_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
