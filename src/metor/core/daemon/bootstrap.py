"""Shared password-verification helpers for daemon runtimes."""

from metor.core import KeyManager


class InvalidMasterPasswordError(Exception):
    """Raised when the supplied master password cannot decrypt local secrets."""


def verify_master_password(km: KeyManager) -> None:
    """
    Verifies that the master password can decrypt the Metor key material.

    Args:
        km (KeyManager): The key manager bound to the candidate password.

    Returns:
        None

    Raises:
        InvalidMasterPasswordError: If the stored key material cannot be decrypted.
    """
    try:
        if km.has_metor_key():
            km.get_metor_key()
    except Exception as exc:
        raise InvalidMasterPasswordError() from exc
