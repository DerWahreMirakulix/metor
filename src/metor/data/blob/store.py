"""Authenticated external blob storage using stable opaque identifiers."""

import os
import re
import secrets
from enum import Enum
from pathlib import Path

import nacl.bindings
import nacl.exceptions
import nacl.hash
import nacl.utils
from nacl.encoding import RawEncoder

from metor.utils import secure_clear_buffer

BLOB_FORMAT_MAGIC = b'METORB01'
BLOB_FORMAT_VERSION = 1
BLOB_ID_BYTES = 32
BLOB_ID_PATTERN = re.compile(r'^[0-9a-f]{64}$')
BLOB_KEY_BYTES = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_KEYBYTES
BLOB_NONCE_BYTES = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_NPUBBYTES
BLOB_AUTH_BYTES = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_ABYTES
MAX_BLOB_PLAINTEXT_BYTES = 64 * 1024 * 1024
PER_BLOB_CONTEXT = b'metor/blob-object/v1\x00'
BLOB_HEADER_BYTES = len(BLOB_FORMAT_MAGIC) + 1 + BLOB_NONCE_BYTES


class BlobLifecycle(str, Enum):
    """Physical lifecycle class for one encrypted blob object."""

    PERSISTENT = 'persistent'
    TEMPORARY = 'temporary'


class BlobStoreError(ValueError):
    """Base error for encrypted blob operations."""


class InvalidBlobIdError(BlobStoreError):
    """Raised when a blob identifier is not a canonical opaque ID."""


class BlobNotFoundError(BlobStoreError):
    """Raised when no encrypted object exists for a blob identifier."""


class BlobFormatError(BlobStoreError):
    """Raised when an encrypted blob has an invalid or unsupported format."""


class BlobAuthenticationError(BlobStoreError):
    """Raised when authenticated blob decryption fails."""


class EncryptedBlobStore:
    """Stores authenticated ciphertext outside SQLCipher by opaque blob ID."""

    def __init__(
        self,
        persistent_dir: Path,
        temporary_dir: Path,
        blob_key: bytes | bytearray,
        max_blob_bytes: int = MAX_BLOB_PLAINTEXT_BYTES,
    ) -> None:
        """Initializes encrypted persistent and temporary object roots.

        Args:
            persistent_dir (Path): Persistent encrypted-object directory.
            temporary_dir (Path): Ephemeral encrypted spool directory.
            blob_key (bytes | bytearray): Profile blob-domain key.
            max_blob_bytes (int): Maximum accepted plaintext object size.

        Returns:
            None
        """
        if len(blob_key) != BLOB_KEY_BYTES:
            raise ValueError('Blob key has an invalid length.')
        if max_blob_bytes <= 0:
            raise ValueError('Blob size limit must be positive.')
        self._persistent_dir = persistent_dir
        self._temporary_dir = temporary_dir
        self._blob_key = bytearray(blob_key)
        self._max_blob_bytes = max_blob_bytes
        self._closed = False
        for root in (persistent_dir, temporary_dir):
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            root.chmod(0o700)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        """Best-effort syncs a directory entry update on POSIX.

        Args:
            path (Path): Directory to synchronize.

        Returns:
            None
        """
        if os.name == 'nt':
            return
        try:
            directory_fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass

    @staticmethod
    def _validate_blob_id(blob_id: str) -> str:
        """Validates a canonical non-path blob identifier.

        Args:
            blob_id (str): Candidate blob identifier.

        Returns:
            str: Validated identifier.
        """
        if BLOB_ID_PATTERN.fullmatch(blob_id) is None:
            raise InvalidBlobIdError('Blob ID is invalid.')
        return blob_id

    def _require_open(self) -> None:
        """Rejects operations after runtime key release.

        Args:
            None

        Returns:
            None
        """
        if self._closed:
            raise RuntimeError('Blob store is closed.')

    def _root(self, lifecycle: BlobLifecycle) -> Path:
        """Resolves a lifecycle to its injected storage root.

        Args:
            lifecycle (BlobLifecycle): Object lifecycle.

        Returns:
            Path: Encrypted object root.
        """
        return (
            self._persistent_dir
            if lifecycle is BlobLifecycle.PERSISTENT
            else self._temporary_dir
        )

    def _path(self, blob_id: str, lifecycle: BlobLifecycle) -> Path:
        """Maps one validated ID to its internal ciphertext path.

        Args:
            blob_id (str): Canonical blob identifier.
            lifecycle (BlobLifecycle): Object lifecycle.

        Returns:
            Path: Internal encrypted-object path.
        """
        return self._root(lifecycle) / f'{self._validate_blob_id(blob_id)}.blob'

    def _derive_object_key(self, blob_id: str) -> bytearray:
        """Derives independent encryption material for one blob ID.

        Args:
            blob_id (str): Canonical blob identifier.

        Returns:
            bytearray: Per-object AEAD key.
        """
        self._require_open()
        self._validate_blob_id(blob_id)
        derived = nacl.hash.blake2b(
            PER_BLOB_CONTEXT + blob_id.encode('ascii'),
            key=bytes(self._blob_key),
            digest_size=BLOB_KEY_BYTES,
            encoder=RawEncoder,
        )
        return bytearray(derived)

    @staticmethod
    def _associated_data(blob_id: str) -> bytes:
        """Builds immutable authenticated blob context.

        Args:
            blob_id (str): Canonical blob identifier.

        Returns:
            bytes: Format and identity associated data.
        """
        return (
            BLOB_FORMAT_MAGIC + bytes((BLOB_FORMAT_VERSION,)) + blob_id.encode('ascii')
        )

    def put(
        self,
        plaintext: bytes,
        lifecycle: BlobLifecycle = BlobLifecycle.PERSISTENT,
    ) -> str:
        """Encrypts one object atomically without a plaintext temporary file.

        Args:
            plaintext (bytes): Binary content to encrypt.
            lifecycle (BlobLifecycle): Persistent or temporary storage class.

        Returns:
            str: New opaque blob identifier.
        """
        self._require_open()
        if len(plaintext) > self._max_blob_bytes:
            raise ValueError('Blob exceeds the configured size limit.')
        blob_id = secrets.token_hex(BLOB_ID_BYTES)
        destination = self._path(blob_id, lifecycle)
        nonce = nacl.utils.random(BLOB_NONCE_BYTES)
        object_key = self._derive_object_key(blob_id)
        try:
            ciphertext = nacl.bindings.crypto_aead_xchacha20poly1305_ietf_encrypt(
                plaintext,
                self._associated_data(blob_id),
                nonce,
                bytes(object_key),
            )
        finally:
            secure_clear_buffer(object_key)
        encoded = BLOB_FORMAT_MAGIC + bytes((BLOB_FORMAT_VERSION,)) + nonce + ciphertext
        temp_path = destination.parent / f'.blob-{secrets.token_hex(8)}.tmp'
        try:
            with temp_path.open('xb') as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.chmod(0o600)
            temp_path.replace(destination)
            destination.chmod(0o600)
            self._sync_directory(destination.parent)
        finally:
            temp_path.unlink(missing_ok=True)
        return blob_id

    def read(
        self,
        blob_id: str,
        lifecycle: BlobLifecycle = BlobLifecycle.PERSISTENT,
    ) -> bytes:
        """Authenticates and decrypts one complete blob object.

        Args:
            blob_id (str): Opaque blob identifier.
            lifecycle (BlobLifecycle): Expected storage class.

        Returns:
            bytes: Authenticated plaintext.
        """
        self._require_open()
        path = self._path(blob_id, lifecycle)
        try:
            if path.stat().st_size > (
                BLOB_HEADER_BYTES + self._max_blob_bytes + BLOB_AUTH_BYTES
            ):
                raise BlobFormatError('Encrypted blob exceeds its size limit.')
            encoded = path.read_bytes()
        except FileNotFoundError as exc:
            raise BlobNotFoundError('Blob does not exist.') from exc
        if len(encoded) <= BLOB_HEADER_BYTES:
            raise BlobFormatError('Encrypted blob is truncated.')
        if encoded[: len(BLOB_FORMAT_MAGIC)] != BLOB_FORMAT_MAGIC:
            raise BlobFormatError('Encrypted blob magic is invalid.')
        version_offset = len(BLOB_FORMAT_MAGIC)
        if encoded[version_offset] != BLOB_FORMAT_VERSION:
            raise BlobFormatError('Encrypted blob version is unsupported.')
        nonce_offset = version_offset + 1
        nonce = encoded[nonce_offset:BLOB_HEADER_BYTES]
        ciphertext = encoded[BLOB_HEADER_BYTES:]
        object_key = self._derive_object_key(blob_id)
        try:
            try:
                return nacl.bindings.crypto_aead_xchacha20poly1305_ietf_decrypt(
                    ciphertext,
                    self._associated_data(blob_id),
                    nonce,
                    bytes(object_key),
                )
            except nacl.exceptions.CryptoError as exc:
                raise BlobAuthenticationError(
                    'Encrypted blob authentication failed.'
                ) from exc
        finally:
            secure_clear_buffer(object_key)

    def delete(
        self,
        blob_id: str,
        lifecycle: BlobLifecycle = BlobLifecycle.PERSISTENT,
    ) -> None:
        """Deletes one encrypted logical object idempotently.

        Args:
            blob_id (str): Opaque blob identifier.
            lifecycle (BlobLifecycle): Expected storage class.

        Returns:
            None
        """
        self._require_open()
        path = self._path(blob_id, lifecycle)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        self._sync_directory(path.parent)

    def promote(self, blob_id: str) -> None:
        """Atomically moves a temporary ciphertext into persistent ownership.

        Args:
            blob_id (str): Opaque blob identifier.

        Returns:
            None
        """
        self._require_open()
        source = self._path(blob_id, BlobLifecycle.TEMPORARY)
        destination = self._path(blob_id, BlobLifecycle.PERSISTENT)
        try:
            source.replace(destination)
        except FileNotFoundError as exc:
            raise BlobNotFoundError('Temporary blob does not exist.') from exc
        destination.chmod(0o600)
        self._sync_directory(source.parent)
        self._sync_directory(destination.parent)

    def close(self) -> None:
        """Best-effort clears the runtime blob key and disables the store.

        Args:
            None

        Returns:
            None
        """
        if self._closed:
            return
        secure_clear_buffer(self._blob_key)
        self._closed = True
