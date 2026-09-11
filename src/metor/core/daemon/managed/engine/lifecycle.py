"""Profile runtime lock, ordinary exit, and destructive purge lifecycle."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
import threading
import socket
from typing import TYPE_CHECKING

from metor.core.api import EventType, JsonValue, create_event
from metor.core.daemon.managed.network import StateTracker
from metor.core.profile_destruction import destroy_profile_storage
from metor.data.sql import SqlManager
from metor.utils import Constants, secure_shred_file

if TYPE_CHECKING:
    from metor.core.daemon.managed.crypto import Crypto
    from metor.core.daemon.managed.engine.command_dispatch import (
        DaemonCommandDispatcher,
    )
    from metor.core.daemon.managed.engine.session_access import (
        SessionAccessController,
    )
    from metor.core.daemon.managed.engine.session_maintenance import (
        SessionMaintenance,
    )
    from metor.core.daemon.managed.ipc import IpcServer
    from metor.core.daemon.managed.outbox import OutboxWorker
    from metor.core.daemon.managed.network import NetworkManager
    from metor.core.key import KeyManager
    from metor.core.tor import TorManager
    from metor.data import (
        ContactManager,
        HistoryManager,
        MessageManager,
        ProfileManager,
    )
    from metor.data.blob import BlobStore


class DaemonLifecycle(str, Enum):
    """Security-relevant daemon lifecycle states."""

    LOCKED = 'locked'
    UNLOCKING = 'unlocking'
    UNLOCKED = 'unlocked'
    LOCKING = 'locking'


class DaemonLifecycleMixin:
    """Owns normal runtime release and key-first destructive teardown."""

    _blob_store: 'BlobStore | None'
    _cm: 'ContactManager | None'
    _command_dispatcher: 'DaemonCommandDispatcher'
    _crypto: 'Crypto | None'
    _hm: 'HistoryManager | None'
    _ipc: 'IpcServer'
    _km: 'KeyManager | None'
    _lifecycle: DaemonLifecycle
    _mm: 'MessageManager | None'
    _network: 'NetworkManager | None'
    _outbox: 'OutboxWorker | None'
    _pm: 'ProfileManager'
    _runtime_stop_flag: threading.Event
    _session_access: 'SessionAccessController'
    _session_maintenance: 'SessionMaintenance | None'
    _tm: 'TorManager | None'
    _transport_state: StateTracker
    _destruction_recipients: set[socket.socket]

    def _on_runtime_internal_error(self, message: str) -> None:
        """Reports one lifecycle failure through the concrete daemon."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stops the concrete daemon after destructive teardown."""
        raise NotImplementedError

    def _lock_runtime(self, preserve_reliability: bool = True) -> bool:
        """Tears down all profile-scoped state while keeping IPC available.

        Args:
            preserve_reliability (bool): Whether normal pending LIVE fallback policy runs.

        Returns:
            bool: True only when every security-sensitive cleanup step completed.
        """
        self._lifecycle = DaemonLifecycle.LOCKING
        self._runtime_stop_flag.set()
        cleanup_succeeded: bool = True

        # Revoke access first, then tear down decrypted resources.  The locked
        # event is emitted only after this method completes.
        self._session_access.clear_all()

        try:
            if self._outbox is not None:
                self._outbox.stop()
        except Exception:
            cleanup_succeeded = False
        try:
            self._command_dispatcher.clear_all_focus()
        except Exception:
            cleanup_succeeded = False
        try:
            if self._network is not None:
                if preserve_reliability:
                    self._network.disconnect_all()
                else:
                    self._network.abort_all()
        except Exception:
            cleanup_succeeded = False
        try:
            if self._tm is not None:
                self._tm.stop()
        except Exception:
            cleanup_succeeded = False
        SqlManager.close_connection(self._pm.paths.get_db_file())
        runtime_db_path: Path = (
            self._pm.paths.get_config_dir() / Constants.DB_RUNTIME_FILE
        )
        try:
            secure_shred_file(runtime_db_path)
        except OSError:
            cleanup_succeeded = False
            self._on_runtime_internal_error(
                'Failed to shred the runtime database mirror while locking.'
            )
        try:
            if getattr(self, '_blob_store', None) is not None:
                assert self._blob_store is not None
                self._blob_store.close()
        except Exception:
            cleanup_succeeded = False
        try:
            if self._km is not None:
                self._km.clear_sensitive_state()
        except Exception:
            cleanup_succeeded = False

        self._command_dispatcher.clear_runtime_handlers()
        self._network = None
        self._outbox = None
        self._session_maintenance = None
        self._crypto = None
        self._tm = None
        self._cm = None
        self._hm = None
        self._mm = None
        self._blob_store = None
        self._km = None
        self._transport_state = StateTracker()
        self._lifecycle = (
            DaemonLifecycle.LOCKED if cleanup_succeeded else DaemonLifecycle.LOCKING
        )
        return cleanup_succeeded

    def _nuke_data(self) -> None:
        """
        Destroys PMK access before best-effort profile filesystem cleanup.

        Args:
            None

        Returns:
            None
        """
        failure_phase = 'unknown'
        key_destroyed = False
        profile_name = getattr(self._pm, 'profile_name', 'unknown')

        def publish(
            event_type: EventType, payload: dict[str, JsonValue] | None = None
        ) -> None:
            """Publishes purge status only to the initiating control session."""
            ipc = getattr(self, '_ipc', None)
            if ipc is None:
                return
            recipients: set[socket.socket] = getattr(
                self, '_destruction_recipients', set()
            )
            try:
                ipc.broadcast_to(create_event(event_type, payload), recipients)
            except Exception:
                pass

        def report_key_destroyed() -> None:
            """Publishes the irreversible key-destruction milestone."""
            nonlocal key_destroyed
            key_destroyed = True
            publish(
                EventType.SELF_DESTRUCT_KEY_DESTROYED,
                {'profile': profile_name},
            )

        def record_failure(phase: str, destroyed: bool) -> None:
            """Captures the destruction phase before the original error propagates."""
            nonlocal failure_phase, key_destroyed
            failure_phase = phase
            key_destroyed = destroyed

        try:
            destroy_profile_storage(
                self._pm,
                prepare_runtime=lambda: self._lock_runtime(preserve_reliability=False),
                key_destroyed_callback=report_key_destroyed,
                failure_callback=record_failure,
            )
            publish(EventType.SELF_DESTRUCT_COMPLETED)
        except Exception:
            publish(
                EventType.SELF_DESTRUCT_CLEANUP_FAILED,
                {
                    'profile': profile_name,
                    'phase': failure_phase,
                    'key_destroyed': key_destroyed,
                },
            )
            self._on_runtime_internal_error(
                'Profile destruction failed during '
                f'{failure_phase}; key_destroyed={key_destroyed}.'
            )
        finally:
            ipc = getattr(self, '_ipc', None)
            if ipc is not None:
                try:
                    ipc.flush(
                        Constants.SOCKET_WRITER_FLUSH_TIMEOUT_SEC,
                        getattr(self, '_destruction_recipients', set()),
                    )
                except Exception:
                    pass
            self.stop()
