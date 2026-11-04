"""Managed-runtime bootstrap helpers for authenticated daemon construction."""

from dataclasses import dataclass
from typing import Callable, Optional

from metor.core.daemon import InvalidMasterPasswordError, verify_master_password
from metor.core.key import KeyManager
from metor.core.tor import TorManager
from metor.shared import secure_clear_buffer
from metor.data import (
    ContactManager,
    DatabaseCorruptedError,
    HistoryManager,
    MessageManager,
    SqlManager,
)
from metor.data.blob import BlobStore, EncryptedBlobStore, PlaintextBlobStore
from metor.data.profile import ProfileManager

# Local Package Imports
from metor.core.daemon.managed.local_auth import (
    SessionAuthContext,
    create_session_auth_context,
)
from metor.core.daemon.managed.runtime_release import release_resources


class CorruptedStorageError(Exception):
    """Raised when the profile database cannot be opened safely."""


class RuntimeBuildCleanupError(RuntimeError):
    """Reports that partial runtime resources could not all be released."""

    def __init__(
        self,
        failed: tuple[str, ...],
        retry_cleanup: Callable[[], bool],
    ) -> None:
        """Retains only known internal cleanup phases.

        Args:
            failed: Names of cleanup actions that did not complete.
            retry_cleanup: Retained cleanup owner for a later release attempt.
        Returns:
            None
        """
        super().__init__('Partial runtime cleanup remains incomplete.')
        self.failed = failed
        self.retry_cleanup = retry_cleanup


@dataclass(frozen=True)
class DaemonRuntime:
    """Authenticated runtime components required by the managed daemon."""

    km: KeyManager
    tm: TorManager
    cm: ContactManager
    hm: HistoryManager
    mm: MessageManager
    blob_store: Optional[BlobStore]
    session_auth: Optional[SessionAuthContext]


def release_uninstalled_runtime(pm: ProfileManager, runtime: DaemonRuntime) -> None:
    """Release a built runtime that was never adopted by a running daemon.

    Args:
        pm: Owner of the temporary profile database and runtime paths.
        runtime: Fully built runtime that cannot be installed or started.
    Returns:
        None
    Raises:
        RuntimeBuildCleanupError: At least one release action needs a retry.
    """
    cleanup_error = _cleanup_owned_components(
        pm,
        runtime.km,
        runtime.blob_store,
        runtime.session_auth,
        runtime.tm,
    )
    if cleanup_error is not None:
        raise cleanup_error


def _cleanup_owned_components(
    pm: ProfileManager,
    km: KeyManager,
    blob_store: BlobStore | None,
    session_auth: SessionAuthContext | None,
    tm: TorManager | None = None,
) -> RuntimeBuildCleanupError | None:
    """Attempt independent cleanup and retain a retry owner for failed phases.

    Args:
        pm: Temporary profile whose pooled database may have been opened.
        km: Key material acquired by the builder.
        blob_store: Optional constructed external blob store.
        session_auth: Optional local session proof context.
        tm: Optional Tor manager from a complete but uninstalled bundle.
    Returns:
        RuntimeBuildCleanupError | None: Retained owner only if cleanup failed.
    """
    steps: list[tuple[str, Callable[[], object]]] = []
    if tm is not None:
        steps.append(('tor_exports', tm.stop))
    if blob_store is not None:
        steps.append(('blob_keys', blob_store.close))
    if session_auth is not None:
        steps.append(
            ('session_proof', lambda: secure_clear_buffer(session_auth.proof_key))
        )
    steps.extend(
        (
            ('database', lambda: SqlManager.close_connection(pm.paths.get_db_file())),
            ('profile_keys', km.clear_sensitive_state),
        )
    )
    cleanup = release_resources(steps)
    if cleanup.succeeded:
        return None

    def retry_cleanup() -> bool:
        """Retry all retained cleanup phases without losing ownership.

        Args:
            None
        Returns:
            bool: True only when every release action returned successfully.
        """
        return release_resources(steps).succeeded

    return RuntimeBuildCleanupError(cleanup.failed, retry_cleanup)


def build_runtime(
    pm: ProfileManager,
    password: Optional[str],
    *,
    enable_session_auth: bool,
    session_auth_password: Optional[str] = None,
) -> DaemonRuntime:
    """
    Builds the authenticated runtime objects required for a full daemon startup.

    Args:
        pm (ProfileManager): The active profile manager.
        password (Optional[str]): The master password, if the profile uses encrypted storage.
        enable_session_auth (bool): Whether the current daemon runtime should require per-session auth.
        session_auth_password (Optional[str]): Optional plaintext-profile session-auth password.

    Returns:
        DaemonRuntime: The authenticated runtime bundle.

    Raises:
        InvalidMasterPasswordError: If the master password is wrong.
        CorruptedStorageError: If the encrypted database is corrupted.
    """
    km = KeyManager(pm, password)
    session_auth: Optional[SessionAuthContext] = None
    blob_store: BlobStore | None = None
    try:
        if pm.uses_encrypted_storage():
            if not password:
                raise InvalidMasterPasswordError()
            verify_master_password(km)

        if pm.uses_encrypted_storage() or enable_session_auth:
            auth_password: Optional[str] = (
                password if pm.uses_encrypted_storage() else session_auth_password
            )
            if not auth_password:
                raise InvalidMasterPasswordError()
            session_auth = create_session_auth_context(auth_password)

        database_key = km.get_database_key()
        cm = ContactManager(pm, database_key)
        hm = HistoryManager(pm, database_key)
        mm = MessageManager(pm, database_key)
        if pm.uses_encrypted_storage():
            blob_store = EncryptedBlobStore(
                pm.paths.get_persistent_blob_dir(),
                pm.paths.get_temporary_blob_dir(),
                km.get_blob_key(),
            )
        else:
            blob_store = PlaintextBlobStore(
                pm.paths.get_persistent_blob_dir(),
                pm.paths.get_temporary_blob_dir(),
            )
        return DaemonRuntime(
            km=km,
            tm=TorManager(pm, km),
            cm=cm,
            hm=hm,
            mm=mm,
            blob_store=blob_store,
            session_auth=session_auth,
        )
    except BaseException as error:
        cleanup_error = _cleanup_owned_components(pm, km, blob_store, session_auth)
        if cleanup_error is not None:
            raise cleanup_error from error
        if isinstance(error, DatabaseCorruptedError):
            raise CorruptedStorageError() from error
        raise
