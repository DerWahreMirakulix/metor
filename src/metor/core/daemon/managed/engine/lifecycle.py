"""Profile runtime lock, ordinary exit, and destructive purge lifecycle."""

from __future__ import annotations

import threading
from enum import Enum
from pathlib import Path
from typing import Any

from metor.core.api import EventType, create_event
from metor.core.daemon.managed.network import StateTracker
from metor.core.profile_destruction import destroy_profile_storage
from metor.data.sql import SqlManager
from metor.utils import Constants, secure_shred_file


class DaemonLifecycle(str, Enum):
    """Security-relevant daemon lifecycle states."""

    LOCKED = 'locked'
    UNLOCKING = 'unlocking'
    UNLOCKED = 'unlocked'
    LOCKING = 'locking'


class DaemonLifecycleMixin:
    """Owns normal runtime release and key-first destructive teardown."""

    _blob_store: Any
    _cm: Any
    _command_dispatcher: Any
    _crypto: Any
    _domain_operation_lock: Any
    _hm: Any
    _ipc: Any
    _km: Any
    _lifecycle: Any
    _mm: Any
    _network: Any
    _outbox: Any
    _pm: Any
    _runtime_stop_flag: Any
    _session_access: Any
    _session_maintenance: Any
    _tm: Any
    _transport_state: Any

    def __getattr__(self, name: str) -> Any:
        """Defers typed collaborators to the composed daemon."""
        raise AttributeError(name)

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
        operation_lock = getattr(self, '_domain_operation_lock', threading.RLock())
        with operation_lock:
            failure_phase = 'unknown'
            key_destroyed = False

            def report_key_destroyed() -> None:
                """Publishes the irreversible key-destruction milestone."""
                nonlocal key_destroyed
                key_destroyed = True
                ipc = getattr(self, '_ipc', None)
                if ipc is not None:
                    ipc.broadcast(
                        create_event(
                            EventType.SELF_DESTRUCT_KEY_DESTROYED,
                            {'profile': self._pm.profile_name},
                        )
                    )

            def record_failure(phase: str, destroyed: bool) -> None:
                """Captures the destruction phase before the original error propagates."""
                nonlocal failure_phase, key_destroyed
                failure_phase = phase
                key_destroyed = destroyed

            try:
                destroy_profile_storage(
                    self._pm,
                    prepare_runtime=lambda: self._lock_runtime(
                        preserve_reliability=False
                    ),
                    key_destroyed_callback=report_key_destroyed,
                    failure_callback=record_failure,
                )
                ipc = getattr(self, '_ipc', None)
                if ipc is not None:
                    ipc.broadcast(create_event(EventType.SELF_DESTRUCT_COMPLETED))
            except Exception:
                ipc = getattr(self, '_ipc', None)
                if ipc is not None:
                    ipc.broadcast(
                        create_event(
                            EventType.SELF_DESTRUCT_CLEANUP_FAILED,
                            {
                                'profile': self._pm.profile_name,
                                'phase': failure_phase,
                                'key_destroyed': key_destroyed,
                            },
                        )
                    )
                self._on_runtime_internal_error(
                    'Profile destruction failed during '
                    f'{failure_phase}; key_destroyed={key_destroyed}.'
                )
            finally:
                self.stop()
