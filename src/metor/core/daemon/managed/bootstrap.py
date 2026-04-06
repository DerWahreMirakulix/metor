"""Managed-runtime bootstrap helpers for authenticated daemon construction."""

from dataclasses import dataclass
from typing import Optional

from metor.core import KeyManager, TorManager
from metor.core.daemon import InvalidMasterPasswordError, verify_master_password
from metor.data import (
    ContactManager,
    DatabaseCorruptedError,
    HistoryManager,
    MessageManager,
)
from metor.data.profile import ProfileManager

# Local Package Imports
from metor.core.daemon.managed.local_auth import (
    SessionAuthContext,
    create_session_auth_context,
)


class CorruptedStorageError(Exception):
    """Raised when the profile database cannot be opened safely."""


@dataclass(frozen=True)
class DaemonRuntime:
    """Authenticated runtime components required by the managed daemon."""

    km: KeyManager
    tm: TorManager
    cm: ContactManager
    hm: HistoryManager
    mm: MessageManager
    session_auth: Optional[SessionAuthContext]


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
    session_auth: Optional[SessionAuthContext] = None
    if pm.uses_encrypted_storage():
        if not password:
            raise InvalidMasterPasswordError()
        verify_master_password(km)
        session_auth = create_session_auth_context(
            password,
            km.get_or_create_password_salt(),
        )

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
        session_auth=session_auth,
    )