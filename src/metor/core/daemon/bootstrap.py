"""
Shared bootstrap helpers for authenticated daemon runtime construction.
"""

from dataclasses import dataclass
from typing import Optional

from metor.core import KeyManager, TorManager
from metor.data import (
    ContactManager,
    DatabaseCorruptedError,
    HistoryManager,
    MessageManager,
)
from metor.data.profile import ProfileManager


class InvalidMasterPasswordError(Exception):
    """Raised when the supplied master password cannot decrypt local secrets."""


class CorruptedStorageError(Exception):
    """Raised when the profile database cannot be opened safely."""


@dataclass(frozen=True)
class DaemonRuntime:
    """Authenticated runtime components required by the daemon."""

    km: KeyManager
    tm: TorManager
    cm: ContactManager
    hm: HistoryManager
    mm: MessageManager


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


def build_runtime(pm: ProfileManager, password: Optional[str]) -> DaemonRuntime:
    """
    Builds the authenticated runtime objects required for a full daemon startup.

    Args:
        pm (ProfileManager): The active profile manager.
        password (Optional[str]): The master password, if the profile uses encrypted storage.

    Returns:
        DaemonRuntime: The authenticated runtime bundle.

    Raises:
        InvalidMasterPasswordError: If the master password is wrong.
        CorruptedStorageError: If the encrypted database is corrupted.
    """
    km = KeyManager(pm, password)
    if pm.uses_encrypted_storage():
        if not password:
            raise InvalidMasterPasswordError()
        verify_master_password(km)

    try:
        cm = ContactManager(pm, password)
        hm = HistoryManager(pm, password)
        mm = MessageManager(pm, password)
    except DatabaseCorruptedError as exc:
        raise CorruptedStorageError() from exc

    return DaemonRuntime(
        km=km,
        tm=TorManager(pm, km),
        cm=cm,
        hm=hm,
        mm=mm,
    )
