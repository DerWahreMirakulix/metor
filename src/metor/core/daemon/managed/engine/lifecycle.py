"""Profile runtime lock, ordinary exit, and destructive purge lifecycle."""

from __future__ import annotations

from enum import Enum
import threading
import socket
from typing import TYPE_CHECKING, Callable
from metor.core.daemon.managed.runtime_release import (
    RuntimeReleaseResult,
    release_resources,
)

from metor.core.api import EventType, JsonValue, create_event
from metor.core.daemon.managed.network import StateTracker
from metor.core.profile_destruction import destroy_profile_storage
from metor.data.sql import SqlManager
from metor.utils import Constants, secure_shred_file

if TYPE_CHECKING:
    from metor.core.daemon.managed.bootstrap import RuntimeBuildCleanupError
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
    _partial_build_cleanup: 'RuntimeBuildCleanupError | None'
    _pm: 'ProfileManager'
    _runtime_stop_flag: threading.Event
    _session_access: 'SessionAccessController'
    _session_maintenance: 'SessionMaintenance | None'
    _tm: 'TorManager | None'
    _transport_state: StateTracker
    _destruction_recipients: set[socket.socket]
    _last_runtime_release: RuntimeReleaseResult
    _release_lock: threading.RLock
    _domain_operation_lock: threading.RLock

    def _on_runtime_internal_error(self, message: str) -> None:
        """Reports one lifecycle failure through the concrete daemon.

        Args:
            message (str): The message input.

        Returns:
            None
        """
        raise NotImplementedError

    def stop(self) -> None:
        """Stops the concrete daemon after destructive teardown.

        Args:
            None

        Returns:
            None
        """
        raise NotImplementedError

    def _lock_runtime(self, preserve_reliability: bool = True) -> bool:
        """Serializes runtime release against repeated lock, stop and purge attempts.

        Args:
            preserve_reliability (bool): The preserve reliability input.

        Returns:
            bool: Whether the documented condition holds.
        """
        # Dispatch already owns the domain barrier. External stop must use the
        # same order, otherwise network teardown can invert these two locks.
        with self._domain_operation_lock, self._release_lock:
            return self._release_runtime(preserve_reliability)

    def _release_runtime(self, preserve_reliability: bool) -> bool:
        """Tears down all profile-scoped state while keeping IPC available.

        Args:
            preserve_reliability (bool): Whether normal pending LIVE fallback policy runs.

        Returns:
            bool: True only when every security-sensitive cleanup step completed.
        """
        self._lifecycle = DaemonLifecycle.LOCKING
        self._runtime_stop_flag.set()
        steps: list[tuple[str, Callable[[], object]]] = [
            ('session_authority', self._session_access.clear_all),
            ('focus', self._command_dispatcher.clear_all_focus),
        ]
        if preserve_reliability:
            steps.insert(
                0, ('voice_producers', self._command_dispatcher.release_voice_producers)
            )
        if self._outbox is not None:
            steps.append(('outbox', self._outbox.stop))
        if self._network is not None:
            steps.append(
                (
                    'network',
                    self._network.disconnect_all
                    if preserve_reliability
                    else self._network.abort_all,
                )
            )
        if self._tm is not None:
            steps.append(('tor_exports', self._tm.stop))
        steps.append(
            (
                'database',
                lambda: SqlManager.close_connection(self._pm.paths.get_db_file()),
            )
        )
        steps.append(
            (
                'plaintext_mirror',
                lambda: secure_shred_file(
                    self._pm.paths.get_config_dir() / Constants.DB_RUNTIME_FILE
                ),
            )
        )
        if self._blob_store is not None:
            steps.append(('blob_keys', self._blob_store.close))
        if self._km is not None:
            steps.append(('profile_keys', self._km.clear_sensitive_state))
        partial = getattr(self, '_partial_build_cleanup', None)
        if partial is not None:
            steps.append(('partial_build', partial.retry_cleanup))
        steps.append(
            ('runtime_handlers', self._command_dispatcher.clear_runtime_handlers)
        )
        self._last_runtime_release = release_resources(steps)
        cleanup_succeeded = self._last_runtime_release.succeeded
        if cleanup_succeeded:
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
            self._partial_build_cleanup = None
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
        operation_id = getattr(self, '_purge_operation_id', None)
        try:
            encrypted = self._pm.uses_encrypted_storage() is True
        except Exception:
            encrypted = False

        def publish(
            event_type: EventType, payload: dict[str, JsonValue] | None = None
        ) -> None:
            """Publishes purge status only to the initiating control session.

            Args:
                event_type (EventType): The event type input.
                payload (dict[str, JsonValue] | None): The payload input.

            Returns:
                None
            """
            ipc = getattr(self, '_ipc', None)
            if ipc is None:
                return
            if operation_id is not None:
                payload = dict(payload or {})
                payload.update(profile=profile_name, operation_id=operation_id)
            recipients: set[socket.socket] = getattr(
                self, '_destruction_recipients', set()
            )
            try:
                ipc.broadcast_to(create_event(event_type, payload), recipients)
            except Exception:
                pass

        def report_key_destroyed() -> None:
            """Publishes the irreversible key-destruction milestone.

            Args:
                None

            Returns:
                None
            """
            nonlocal key_destroyed
            key_destroyed = True
            publish(
                EventType.SELF_DESTRUCT_KEY_DESTROYED,
                {'profile': profile_name},
            )

        def record_failure(phase: str, destroyed: bool) -> None:
            """Captures the destruction phase before the original error propagates.

            Args:
                phase (str): The phase input.
                destroyed (bool): The destroyed input.

            Returns:
                None
            """
            nonlocal failure_phase, key_destroyed
            failure_phase = phase
            key_destroyed = destroyed

        def report_runtime_released() -> None:
            """Reports completed runtime release only to a client opting into scoped milestones.

            Args:
                None
            Returns:
                None
            """
            if operation_id is not None:
                publish(EventType.SELF_DESTRUCT_RUNTIME_RELEASED)

        def report_safe() -> None:
            """Reports combined power-off safety only for encrypted profile storage.

            Args:
                None
            Returns:
                None
            """
            if operation_id is not None and encrypted:
                publish(EventType.SELF_DESTRUCT_SAFE)

        try:
            destroy_profile_storage(
                self._pm,
                prepare_runtime=lambda: self._lock_runtime(preserve_reliability=False),
                key_destroyed_callback=report_key_destroyed,
                runtime_released_callback=report_runtime_released,
                safe_callback=report_safe,
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
