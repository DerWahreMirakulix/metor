"""
Module defining the primary background daemon engine lifecycle.
Orchestrates Network, IPC API, and Outbox routing seamlessly.
Handles Unlock operations, Nuke/Purge protocols, and Local Authentication constraints.
Enforces the Zero-Text Policy by emitting structured Domain-Driven payloads directly to the IPC interface.
Ensures strict SRP by routing incoming commands to dedicated Handlers.
Guards against UI Domain leakage by rejecting UI configurations.
"""

import socket
import threading
import time
import atexit
import os
import signal
import types
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Union

from metor.core.api import (
    AcceptCommand,
    RejectCommand,
    ChangePasswordCommand,
    ConfigureQuickUnlockCommand,
    Delivery,
    create_event,
    IpcEvent,
    IpcCommand,
    LockCommand,
    RestrictClientCommand,
    PrepareProfileExitCommand,
    SelfDestructCommand,
    UnlockCommand,
    EventType,
    JsonValue,
    request_context,
    stamp_request_id,
)
from metor.core.key import KeyManager
from metor.core.profile_keys import InvalidCredentialError
from metor.core.tor import TorManager
from metor.data.profile import ProfileManager
from metor.data import (
    HistoryManager,
    ContactManager,
    MessageManager,
    SettingKey,
    SqlManager,
)
from metor.data.sql import ProfileMetadataRepository
from metor.data.blob import BlobLifecycle, BlobStore
from metor.shared import clean_onion, secure_clear_buffer
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.managed.crypto import Crypto
from metor.core.daemon.managed.bootstrap import (
    build_runtime,
    CorruptedStorageError,
    DaemonRuntime,
    RuntimeBuildCleanupError,
    release_uninstalled_runtime,
)
from metor.core.daemon.managed.handlers import (
    NetworkCommandHandler,
    ProfileMetadataCommandHandler,
)
from metor.core.daemon.managed.ipc import IpcServer
from metor.core.daemon.managed.outbox import OutboxWorker
from metor.core.daemon.managed.network import NetworkManager, StateTracker
from metor.core.daemon.managed.notify import NotificationService
from metor.core.daemon.managed.producers import (
    ProducerCleanup,
    VoiceProducerService,
    ProducerBlobAllocator,
)
from metor.core.daemon import InvalidMasterPasswordError
from metor.core.daemon.managed.local_auth import (
    SessionAuthContext,
    create_session_auth_context,
)
from metor.core.daemon.managed.quick_unlock import QuickUnlockStore
from metor.core.daemon.managed.status import DaemonStatus
from metor.core.daemon.handlers import (
    ConfigCommandHandler,
    DatabaseCommandHandler,
    SystemCommandHandler,
)

from .command_dispatch import DaemonCommandDispatcher
from .lifecycle import DaemonLifecycle as DaemonLifecycle
from .lifecycle import DaemonLifecycleMixin
from metor.core.daemon.managed.runtime_release import release_resources
from .session_access import SessionAccessController
from .session_maintenance import SessionMaintenance


@dataclass(frozen=True)
class RuntimeStartFailure:
    """Safe local phase and category for an incomplete daemon start."""

    phase: str
    category: str


class RuntimeStartupError(ValueError):
    """Reports a failed foreground start without exposing exception values."""

    def __init__(self, failure: RuntimeStartFailure) -> None:
        """Retains the safe startup failure for the foreground CLI.

        Args:
            failure: Fixed startup phase and known-safe category.
        Returns:
            None
        """
        super().__init__(
            f'Daemon startup failed [{failure.phase}]: {failure.category}.'
        )
        self.failure = failure


def safe_start_category(error: BaseException) -> str:
    """Classify an internal start exception without formatting its value.

    Args:
        error: Internal exception that remains in the local call chain.
    Returns:
        str: Known-safe category or a conservative fallback.
    """
    if isinstance(error, FileNotFoundError):
        return 'FileNotFoundError'
    if isinstance(error, PermissionError):
        return 'PermissionError'
    if isinstance(error, OSError):
        return 'OSError'
    if isinstance(error, RuntimeError):
        return 'RuntimeError'
    if isinstance(error, ValueError):
        return 'ValueError'
    return 'Exception'


class Daemon(DaemonLifecycleMixin):
    """The main orchestrator binding network, cryptography, and logic together."""

    def __init__(
        self,
        pm: ProfileManager,
        km: Optional[KeyManager] = None,
        tm: Optional[TorManager] = None,
        cm: Optional[ContactManager] = None,
        hm: Optional[HistoryManager] = None,
        mm: Optional[MessageManager] = None,
        blob_store: Optional[BlobStore] = None,
        session_auth: Optional[SessionAuthContext] = None,
        status_callback: Optional[
            Callable[[Union[EventType, DaemonStatus], Dict[str, JsonValue]], None]
        ] = None,
        require_session_auth: bool = False,
        start_locked: bool = False,
    ) -> None:
        """
        Initializes the DaemonEngine.

        Args:
            pm (ProfileManager): Profile configurations.
            km (Optional[KeyManager]): Handles cryptographic keys once runtime is installed.
            tm (Optional[TorManager]): Manages the Tor process.
            cm (Optional[ContactManager]): Address book manager.
            hm (Optional[HistoryManager]): Event logging.
            mm (Optional[MessageManager]): Offline messages storage.
            blob_store (Optional[BlobStore]): Mode-appropriate external object store.
            session_auth (Optional[SessionAuthContext]): Optional verifier context for per-session local auth.
            status_callback (Optional[Callable]): Hook for UI-agnostic startup logging.
            require_session_auth (bool): Whether this daemon runtime should require per-session auth.
            start_locked (bool): Whether to delay runtime startup until an explicit unlock.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._tm: Optional[TorManager] = None
        self._cm: Optional[ContactManager] = None
        self._hm: Optional[HistoryManager] = None
        self._mm: Optional[MessageManager] = None
        self._km: Optional[KeyManager] = None
        self._blob_store: Optional[BlobStore] = None
        self._status_cb: Optional[
            Callable[[Union[EventType, DaemonStatus], Dict[str, JsonValue]], None]
        ] = status_callback

        self._stop_flag: threading.Event = threading.Event()
        self._stop_lock: threading.RLock = threading.RLock()
        self._release_lock = threading.RLock()
        self._lifecycle: DaemonLifecycle = (
            DaemonLifecycle.LOCKED if start_locked else DaemonLifecycle.UNLOCKED
        )
        self._is_stopping: bool = False
        self._runtime_stop_flag: threading.Event = threading.Event()
        self._domain_operation_lock = threading.RLock()
        self._purge_fence = threading.Event()
        self._purge_operation_id: str | None = None
        self._last_start_failure: RuntimeStartFailure | None = None
        self._partial_build_cleanup: RuntimeBuildCleanupError | None = None
        self._require_session_auth: bool = require_session_auth
        self._transport_state: StateTracker = StateTracker()

        self._crypto: Optional[Crypto] = None
        self._notification_service: NotificationService = NotificationService(
            config_getter=lambda: self._pm.config.get_str(SettingKey.NOTIFICATION_SINK),
            error_callback=self._on_runtime_internal_error,
        )
        self._ipc: IpcServer = IpcServer(
            pm,
            self._process_ui_command,
            self._on_ipc_disconnect,
            self._on_runtime_internal_error,
        )
        self._outbox: Optional[OutboxWorker] = None
        self._network: Optional[NetworkManager] = None
        self._session_maintenance: Optional[SessionMaintenance] = None

        self._command_dispatcher: DaemonCommandDispatcher = DaemonCommandDispatcher(
            ConfigCommandHandler(self._pm),
            self._send_to_client,
        )
        profile_paths = getattr(self._pm, 'paths', None)
        quick_unlock_store = (
            QuickUnlockStore(profile_paths.get_quick_unlock_file())
            if profile_paths is not None
            else None
        )
        self._session_access: SessionAccessController = SessionAccessController(
            require_auth=require_session_auth,
            send_callback=self._send_to_client,
            lockout_timeout_callback=self._get_local_auth_lockout_timeout,
            failure_limit_callback=self._get_local_auth_failure_limit,
            live_consumer_available_callback=self._on_live_consumer_available,
            quick_unlock_store=quick_unlock_store,
            is_saved_contact_callback=self._is_saved_contact_target,
            resolve_target_callback=self._resolve_contact_target,
            voice_target_callback=self._voice_target,
            pending_token_callback=lambda onion: self._transport_state.pending_token(
                onion
            ),
            active_connection_callback=lambda onion: (
                self._transport_state.get_connection(onion)
            ),
            pending_call_callback=lambda onion: self._transport_state.pending_identity(
                onion
            ),
            voice_context_callback=self._voice_context,
            voice_delivery_callback=self._voice_delivery,
            inbound_voice_delivery_callback=self._inbound_voice_delivery,
            live_context_callback=self._live_context_token,
            live_generation_callback=lambda onion: (
                self._network.known_live_context_generation(onion)
                if self._network is not None
                else None
            ),
            live_state_callback=lambda onion: (
                self._network.get_live_state(onion).value
                if self._network is not None
                else 'disconnected'
            ),
            pending_projection_callback=lambda: (
                self._command_dispatcher.pending_call_entries()
            ),
            self_destruct_requires_unlock_callback=lambda: self._pm.config.get_bool(
                SettingKey.SELF_DESTRUCT_REQUIRES_UNLOCK
            ),
        )

        atexit.register(self.stop)
        if (
            km is not None
            and tm is not None
            and cm is not None
            and hm is not None
            and mm is not None
        ):
            try:
                self._install_runtime(
                    DaemonRuntime(
                        km=km,
                        tm=tm,
                        cm=cm,
                        hm=hm,
                        mm=mm,
                        blob_store=blob_store,
                        session_auth=session_auth,
                    )
                )
            except Exception as error:
                self._record_start_failure('runtime_install', error)
                if self._lock_runtime(preserve_reliability=False):
                    atexit.unregister(self.stop)
                raise RuntimeStartupError(
                    self._last_start_failure
                    or RuntimeStartFailure('runtime_install', 'Exception')
                ) from error

        if os.name != 'nt':
            signal.signal(signal.SIGINT, self._sig_handler)
            signal.signal(signal.SIGTERM, self._sig_handler)
            sighup_signal = getattr(signal, 'SIGHUP', None)
            if sighup_signal is not None:
                signal.signal(sighup_signal, self._sig_handler)

    def _install_runtime(self, runtime: DaemonRuntime) -> None:
        """
        Installs the authenticated runtime components after direct startup or unlock.

        Args:
            runtime (DaemonRuntime): The authenticated runtime bundle.

        Returns:
            None
        """
        self._runtime_stop_flag = threading.Event()
        self._km = runtime.km
        self._tm = runtime.tm
        self._cm = runtime.cm
        self._hm = runtime.hm
        self._mm = runtime.mm
        self._blob_store = runtime.blob_store
        self._transport_state = StateTracker()
        self._session_access.install_context(runtime.session_auth)

        self._crypto = Crypto(runtime.km)
        self._network = NetworkManager(
            runtime.tm,
            runtime.cm,
            runtime.hm,
            runtime.mm,
            self._crypto,
            self._broadcast_ipc_event,
            self._ipc.has_active_clients,
            self._session_access.has_session_consumers,
            self._notification_service.dispatch,
            self._runtime_stop_flag,
            config=self._pm.config,
            state=self._transport_state,
            blob_store=runtime.blob_store,
            purge_fence=self._purge_fence,
            operation_lock=self._domain_operation_lock,
        )
        self._outbox = OutboxWorker(
            runtime.tm,
            runtime.mm,
            runtime.hm,
            self._crypto,
            self._broadcast_ipc_event,
            self._runtime_stop_flag,
            config=self._pm.config,
            state=self._transport_state,
            error_callback=self._on_runtime_internal_error,
            blob_store=runtime.blob_store,
            operation_lock=self._domain_operation_lock,
        )
        self._session_maintenance = SessionMaintenance(
            network=self._network,
            state=self._transport_state,
            mm=runtime.mm,
            config=self._pm.config,
        )
        active_blob_store = runtime.blob_store

        def delete_persistent_blob_object(blob_id: str) -> None:
            """Deletes one persistent blob through the active profile store.

            Args:
                blob_id (str): The blob id input.

            Returns:
                None
            """
            if active_blob_store is not None:
                active_blob_store.delete(blob_id, BlobLifecycle.PERSISTENT)

        delete_persistent_blob: Optional[Callable[[str], None]] = (
            delete_persistent_blob_object if active_blob_store is not None else None
        )
        database_handler = DatabaseCommandHandler(
            self._pm,
            runtime.cm,
            runtime.hm,
            runtime.mm,
            self._network.get_active_onions,
            self._broadcast_ipc_event,
            self._session_maintenance.send_read_receipts,
            self._network.release_consumed_voice,
            delete_persistent_blob,
        )

        def profile_metadata() -> ProfileMetadataRepository:
            """Resolves storage only for the installed unlocked runtime.

            Args:
                None
            Returns:
                ProfileMetadataRepository: Profile-owned protected namespace.
            """
            return SqlManager.opened_profile_metadata(self._pm.paths.get_db_file())

        metadata_handler = ProfileMetadataCommandHandler(
            profile_metadata,
            self._session_access.is_full_authenticated,
            self._broadcast_ipc_event,
            self._session_access.quick_unlock_available,
        )
        system_handler = SystemCommandHandler(self._pm, runtime.tm)
        producers: VoiceProducerService | None = None
        voice_owner_available = False
        if active_blob_store is not None:
            producer_repository = SqlManager.opened_voice_producers(
                self._pm.paths.get_db_file()
            )
            voice_owner_available = producer_repository.protected
            self._network.set_voice_capture_allocator(
                ProducerBlobAllocator(producer_repository, active_blob_store).put
            )
            producers = VoiceProducerService(
                ProducerCleanup(
                    producer_repository,
                    runtime.mm,
                    active_blob_store,
                    self._network.cancel_voice_draft,
                    self._network.finalize_interrupted_voice,
                ),
                self._resolve_contact_target,
                self._send_to_client,
                self._purge_fence.is_set,
                context=lambda onion, msg_id: self._voice_context(onion, msg_id, 'out'),
                current_context=self._live_context_token,
            )
            producers.retry()
        network_handler = NetworkCommandHandler(
            runtime.tm,
            runtime.cm,
            runtime.hm,
            runtime.mm,
            self._network,
            self._outbox,
            self._broadcast_ipc_event,
            self._send_to_client,
            self._session_access.register_session_consumer,
            config=self._pm.config,
            current_revision_cb=self._ipc.current_revision,
            profile_instance_cb=metadata_handler.instance_id,
            voice_owner_available=voice_owner_available,
            authenticated_client_count_cb=lambda: len(
                self._session_access.authenticated_recipients()
            ),
        )
        self._command_dispatcher.install_runtime_handlers(
            network=network_handler,
            database=database_handler,
            system=system_handler,
            metadata=metadata_handler,
            producers=producers,
        )

    def _on_runtime_internal_error(self, message: str) -> None:
        """
        Surfaces one unexpected daemon runtime error to the daemon console callback.

        Args:
            message (str): The console-safe runtime error message.

        Returns:
            None
        """
        with self._stop_lock:
            if self._is_stopping:
                return

        try:
            if self._status_cb is not None:
                self._status_cb(DaemonStatus.RUNTIME_ERROR, {'message': message})
        except Exception:
            pass

    def _broadcast_ipc_event(self, event: IpcEvent) -> None:
        """
        Broadcasts one IPC event while preserving local-auth session boundaries.

        Args:
            event (IpcEvent): The event payload to emit.

        Returns:
            None
        """
        with self._domain_operation_lock:
            if self._lifecycle is not DaemonLifecycle.UNLOCKED:
                return
            if event.event_type is not EventType.RUNTIME_STATE_CHANGED:
                stamp_request_id(event)
            self._session_access.observe_call_transition(event)
            recipients = (
                self._session_access.authenticated_recipients()
                if self._session_access.requires_auth()
                else self._ipc.active_clients()
            )
            for recipient in recipients:
                filtered = self._session_access.filter_restricted_event(
                    recipient, event
                )
                if filtered is not None:
                    self._ipc.broadcast_to(filtered, {recipient})

    def _on_live_consumer_available(self) -> None:
        """Notifies the active network runtime about its first live consumer.

        Args:
            None

        Returns:
            None
        """
        if self._network is not None:
            self._network.on_live_consumer_available()

    def _send_to_client(self, conn: socket.socket, event: IpcEvent) -> None:
        """
        Helper to inject the IPC send function natively into Handlers.

        Args:
            conn (socket.socket): Connection.
            event (IpcEvent): The event to push.

        Returns:
            None
        """
        stamp_request_id(event)
        event = self._session_access.project_pending_snapshot(conn, event)
        self._ipc.send_to(conn, event)

    def _sig_handler(self, signum: int, frame: Optional[types.FrameType]) -> None:
        """
        Requests shutdown; run() owns cleanup after any in-flight startup returns.

        Args:
            signum (int): The signal number.
            frame (Optional[types.FrameType]): The current stack frame.

        Returns:
            None
        """
        with self._stop_lock:
            self._stop_flag.set()
            self._runtime_stop_flag.set()

    def run(self) -> None:
        """
        Starts the Engine infrastructure.

        Args:
            None

        Returns:
            None
        """
        try:
            with self._domain_operation_lock:
                if self._stop_flag.is_set() or self._purge_fence.is_set():
                    raise RuntimeStartupError(
                        RuntimeStartFailure('cancelled', 'Cancelled')
                    )
                if self._lifecycle is DaemonLifecycle.LOCKED:
                    try:
                        self._ipc.start()
                    except Exception as error:
                        self._record_start_failure('ipc_listener', error)
                        raise RuntimeStartupError(
                            self._last_start_failure
                            or RuntimeStartFailure('ipc_listener', 'Exception')
                        ) from error
                    if self._stop_flag.is_set() or self._purge_fence.is_set():
                        raise RuntimeStartupError(
                            RuntimeStartFailure('cancelled', 'Cancelled')
                        )
                    if self._status_cb:
                        try:
                            self._status_cb(DaemonStatus.LOCKED_MODE, {})
                        except Exception:
                            pass
                else:
                    self._lifecycle = DaemonLifecycle.UNLOCKING
                    if not self._start_subsystems():
                        failure = self._last_start_failure or RuntimeStartFailure(
                            'runtime', 'Exception'
                        )
                        raise RuntimeStartupError(failure)
                    with self._stop_lock:
                        if self._stop_flag.is_set() or self._purge_fence.is_set():
                            raise RuntimeStartupError(
                                RuntimeStartFailure('cancelled', 'Cancelled')
                            )
                        self._lifecycle = DaemonLifecycle.UNLOCKED
                        self._publish_active_status()

            while not self._stop_flag.is_set():
                time.sleep(Constants.WORKER_SLEEP_SEC)
                if self._session_maintenance is not None:
                    self._session_maintenance.check_idle_timeouts()
                with self._domain_operation_lock:
                    self._command_dispatcher.retry_voice_cleanup()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _start_subsystems(self) -> bool:
        """
        Initializes the actual Tor and Network components once unlocked.

        Args:
            None

        Returns:
            bool: True if startup completed successfully.
        """
        self._last_start_failure = None
        if self._tm is None or self._network is None or self._outbox is None:
            self._record_start_failure('runtime_install')
            return False

        if self._stop_flag.is_set() or self._purge_fence.is_set():
            self._record_start_failure('cancelled')
            return False

        try:
            self._pm.initialize()
        except Exception as error:
            self._record_start_failure('profile_initialize', error)
            return False

        if self._stop_flag.is_set() or self._purge_fence.is_set():
            self._record_start_failure('cancelled')
            return False

        try:
            success, event_type, _params = self._tm.start()
        except Exception as error:
            self._record_start_failure('tor_start', error)
            return False
        if not success:
            if self._status_cb and event_type is not None:
                try:
                    self._status_cb(event_type, {})
                except Exception:
                    pass
            self._record_start_failure('tor_start')
            return False

        if self._stop_flag.is_set() or self._purge_fence.is_set():
            self._record_start_failure('cancelled')
            return False
        try:
            self._network.start_listener()
        except Exception as error:
            self._record_start_failure('network_listener', error)
            return False

        if self._stop_flag.is_set() or self._purge_fence.is_set():
            self._record_start_failure('cancelled')
            return False
        try:
            if not self._ipc.port:
                self._ipc.start()
        except Exception as error:
            self._record_start_failure('ipc_listener', error)
            return False

        if self._stop_flag.is_set() or self._purge_fence.is_set():
            self._record_start_failure('cancelled')
            return False
        try:
            self._outbox.start()
        except Exception as error:
            self._record_start_failure('outbox', error)
            return False

        return True

    def _publish_active_status(self) -> None:
        """Publishes readiness only after the runtime commit point.

        Args:
            None
        Returns:
            None
        """
        if self._status_cb is None or self._tm is None:
            return
        try:
            self._status_cb(
                DaemonStatus.ACTIVE,
                {'onion': clean_onion(self._tm.onion or ''), 'port': self._ipc.port},
            )
        except Exception:
            pass

    def _record_start_failure(self, phase: str, error: Exception | None = None) -> None:
        """Records only a fixed start phase and known-safe exception category.

        Args:
            phase: Internal startup step that did not complete.
            error: Optional underlying exception, never formatted or retained.
        Returns:
            None
        """
        category = (
            ('Cancelled' if phase == 'cancelled' else 'Rejected')
            if error is None
            else safe_start_category(error)
        )
        self._last_start_failure = RuntimeStartFailure(phase, category)
        self._on_runtime_internal_error(f'Daemon startup failed [{phase}]: {category}.')

    def stop(self) -> None:
        """Serializes independently attempted release; failed phases remain retryable.

        Args:
            None

        Returns:
            None
        """
        with self._stop_lock:
            self._stop_flag.set()
        with self._domain_operation_lock, self._release_lock:
            self._stop_resources()

    def _stop_resources(self) -> None:
        """
        Stops the engine and gracefully tears down all sub-services.

        Args:
            None

        Returns:
            None
        """
        with self._stop_lock:
            if getattr(self, '_stop_completed', False):
                return
            self._is_stopping = True
            self._stop_flag.set()
            self._runtime_stop_flag.set()

        self._last_stop_release = release_resources(
            (
                ('notifications', self._notification_service.close),
                (
                    'runtime',
                    lambda: self._lock_runtime(
                        preserve_reliability=not self._purge_fence.is_set()
                    ),
                ),
                ('ipc', self._ipc.stop),
                (
                    'endpoint',
                    lambda: self._pm.clear_daemon_port(
                        expected_pid=os.getpid(), expected_port=self._ipc.port
                    ),
                ),
            )
        )
        self._stop_completed = self._last_stop_release.succeeded

    def _on_ipc_disconnect(self, conn: socket.socket) -> None:
        """
        Callback fired when an IPC client disconnects. Cleans up authentication states.

        Args:
            conn (socket.socket): The disconnected client socket.

        Returns:
            None
        """
        self._session_access.disconnect(conn)
        self._command_dispatcher.clear_client_focus(conn)
        with self._domain_operation_lock:
            self._command_dispatcher.disconnect_voice_producer(conn)

    def _get_local_auth_lockout_timeout(self) -> float:
        """
        Resolves the configured cross-connection local-auth cooldown window.

        Args:
            None

        Returns:
            float: The lockout duration in seconds.
        """
        return self._pm.config.get_float(SettingKey.LOCAL_AUTH_LOCKOUT_TIMEOUT)

    def _get_local_auth_failure_limit(self) -> int:
        """
        Resolves the configured local-auth failure limit for one auth window.

        Args:
            None

        Returns:
            int: The maximum invalid attempts before disconnect.
        """
        return max(1, self._pm.config.get_int(SettingKey.LOCAL_AUTH_FAILURE_LIMIT))

    def _is_saved_contact_target(self, target: str) -> bool:
        """Checks whether a target resolves to a saved contact in the active runtime.

        Args:
            target (str): Alias or onion identity.

        Returns:
            bool: True only for an active-runtime saved contact.
        """
        if self._cm is None:
            return False
        resolved = self._cm.resolve_target(target)
        if resolved is None:
            return False
        return resolved[0] in self._cm.get_all_contacts()

    def _resolve_contact_target(self, target: str) -> Optional[str]:
        """Resolves aliases to the stable onion identity used by lock policy.

        Args:
            target (str): The target input.

        Returns:
            Optional[str]: The resulting value.
        """
        if self._cm is None:
            return None
        resolved = self._cm.resolve_target(target)
        return resolved[1] if resolved is not None else None

    def _voice_target(self, msg_id: str) -> Optional[str]:
        """Returns the stable target bound to an active outbound Voice turn.

        Args:
            msg_id (str): The msg id input.

        Returns:
            Optional[str]: The resulting value.
        """
        return self._network.voice_target(msg_id) if self._network is not None else None

    def _voice_context(self, onion: str, msg_id: str, direction: str) -> int | None:
        """Returns immutable recording ownership from the active runtime.

        Args:
            onion (str): The onion input.
            msg_id (str): The msg id input.
            direction (str): The direction input.

        Returns:
            int | None: The resulting value.
        """
        return (
            self._network.voice_context(onion, msg_id, direction)
            if self._network is not None
            else None
        )

    def _voice_delivery(self, msg_id: str) -> Optional[Delivery]:
        """Returns delivery semantics bound to an active outbound Voice turn.

        Args:
            msg_id (str): The msg id input.

        Returns:
            Optional[Delivery]: The resulting value.
        """
        return (
            self._network.voice_delivery(msg_id) if self._network is not None else None
        )

    def _inbound_voice_delivery(self, onion: str, msg_id: str) -> Optional[Delivery]:
        """Returns exact retained inbound Voice delivery semantics.

        Args:
            onion (str): Stable peer identity.
            msg_id (str): Stable Voice identity.

        Returns:
            Optional[Delivery]: Retained delivery semantics, if available.
        """
        return (
            self._network.inbound_voice_delivery(onion, msg_id)
            if self._network is not None
            else None
        )

    def _live_context_token(self, onion: str) -> object | None:
        """Returns logical ownership for a restricted LIVE context.

        Args:
            onion (str): Stable peer identity.

        Returns:
            object | None: Active logical conversation generation.
        """
        return (
            self._network.live_context_token(onion)
            if self._network is not None
            else None
        )

    def _process_ui_command(self, cmd: IpcCommand, conn: socket.socket) -> None:
        """
        Routes typed IPC commands from the Chat UI or CLI Proxy to dedicated Handlers.
        Enforces local authentication and controls daemon state operations (Unlock, Purge, Config).

        Args:
            cmd (IpcCommand): The parsed command object.
            conn (socket.socket): The connection to respond to.

        Returns:
            None
        """
        with request_context(cmd.request_id):
            if self._purge_fence.is_set():
                if isinstance(cmd, SelfDestructCommand):
                    self._send_self_destruct_initiated(conn)
                else:
                    self._ipc.send_to(conn, create_event(EventType.DAEMON_OFFLINE))
                return
            with self._domain_operation_lock:
                if self._purge_fence.is_set():
                    if isinstance(cmd, SelfDestructCommand):
                        self._send_self_destruct_initiated(conn)
                    else:
                        self._ipc.send_to(conn, create_event(EventType.DAEMON_OFFLINE))
                    return
                self._process_ui_command_in_context(cmd, conn)

    def _send_self_destruct_initiated(self, conn: socket.socket) -> None:
        """Best-effort notification that never gates destructive work.

        Args:
            conn (socket.socket): The conn input.

        Returns:
            None
        """
        payload: dict[str, JsonValue] | None = None
        operation_id = getattr(self, '_purge_operation_id', None)
        if operation_id is not None and conn in getattr(
            self, '_destruction_recipients', set()
        ):
            payload = {'profile': self._pm.profile_name, 'operation_id': operation_id}
        try:
            self._ipc.send_to(
                conn,
                create_event(EventType.SELF_DESTRUCT_INITIATED, payload),
            )
        except Exception:
            pass

    def _process_ui_command_in_context(
        self,
        cmd: IpcCommand,
        conn: socket.socket,
    ) -> None:
        """
        Routes one request-scoped IPC command after correlation context setup.

        Args:
            cmd (IpcCommand): The parsed command object.
            conn (socket.socket): The connection to respond to.

        Returns:
            None
        """
        if not self._session_access.authorize(
            cmd,
            conn,
            runtime_unlocked=self._lifecycle is DaemonLifecycle.UNLOCKED,
        ):
            return

        pending_action = self._session_access.take_pending_action(conn)
        if pending_action is not None and self._network is not None:
            if isinstance(cmd, AcceptCommand):
                self._network.accept(cmd.target, expected_pending=pending_action)
                if (
                    cmd.action_handle is not None
                    and self._transport_state.get_connection(cmd.target)
                    is pending_action
                ):
                    generation = self._network.known_live_context_generation(cmd.target)
                    if generation is not None:
                        self._session_access.record_accepted_call(
                            conn, cmd.action_handle, cmd.target, generation
                        )
                return
            if isinstance(cmd, RejectCommand):
                self._network.reject(cmd.target, expected_pending=pending_action)
                return

        if isinstance(cmd, UnlockCommand):
            if self._lifecycle is DaemonLifecycle.UNLOCKED:
                self._ipc.send_to(
                    conn,
                    create_event(EventType.ALREADY_UNLOCKED),
                )
                return
            if self._lifecycle is not DaemonLifecycle.LOCKED:
                self._ipc.send_to(conn, create_event(EventType.INTERNAL_ERROR))
                return

            self._lifecycle = DaemonLifecycle.UNLOCKING
            start_phase = 'runtime_build'
            try:
                runtime = build_runtime(
                    self._pm,
                    cmd.password,
                    enable_session_auth=self._require_session_auth,
                )
            except InvalidMasterPasswordError:
                self._lifecycle = DaemonLifecycle.LOCKED
                should_disconnect: bool = self._session_access.register_invalid_unlock(
                    conn
                )
                local_auth_retry_after = self._session_access.retry_after_seconds()
                if local_auth_retry_after is not None:
                    self._ipc.send_to(
                        conn,
                        create_event(
                            EventType.LOCAL_AUTH_RATE_LIMITED,
                            {'retry_after': local_auth_retry_after},
                        ),
                    )
                    return
                self._ipc.send_to(
                    conn,
                    create_event(EventType.INVALID_PASSWORD),
                )
                if should_disconnect:
                    try:
                        conn.close()
                    except OSError:
                        pass
                return
            except CorruptedStorageError:
                self._lifecycle = DaemonLifecycle.LOCKED
                self._ipc.send_to(conn, create_event(EventType.DB_CORRUPTED))
                return
            except RuntimeBuildCleanupError as error:
                self._partial_build_cleanup = error
                self._record_start_failure(start_phase, error)
                self._lock_runtime(preserve_reliability=False)
                self._ipc.send_to(conn, create_event(EventType.INTERNAL_ERROR))
                return
            except Exception as error:
                self._record_start_failure(start_phase, error)
                self._lock_runtime(preserve_reliability=False)
                self._ipc.send_to(conn, create_event(EventType.INTERNAL_ERROR))
                return

            try:
                start_phase = 'runtime_install'
                if (
                    self._stop_flag.is_set()
                    or self._purge_fence.is_set()
                    or conn not in self._ipc.active_clients()
                ):
                    self._record_start_failure('cancelled')
                    try:
                        release_uninstalled_runtime(self._pm, runtime)
                    except RuntimeBuildCleanupError as cleanup_error:
                        self._partial_build_cleanup = cleanup_error
                    self._lock_runtime(preserve_reliability=False)
                    self._ipc.send_to(conn, create_event(EventType.INTERNAL_ERROR))
                    return
                self._install_runtime(runtime)
                if (
                    self._stop_flag.is_set()
                    or self._purge_fence.is_set()
                    or conn not in self._ipc.active_clients()
                ):
                    self._record_start_failure('cancelled')
                    raise RuntimeStartupError(
                        self._last_start_failure
                        or RuntimeStartFailure('cancelled', 'Cancelled')
                    )
                start_phase = 'service_start'
                if not self._start_subsystems():
                    raise RuntimeStartupError(
                        self._last_start_failure
                        or RuntimeStartFailure(start_phase, 'Exception')
                    )
                if (
                    self._stop_flag.is_set()
                    or self._purge_fence.is_set()
                    or conn not in self._ipc.active_clients()
                ):
                    self._record_start_failure('cancelled')
                    raise RuntimeStartupError(
                        self._last_start_failure
                        or RuntimeStartFailure('cancelled', 'Cancelled')
                    )
                start_phase = 'session_commit'
                with self._stop_lock:
                    if (
                        self._stop_flag.is_set()
                        or self._purge_fence.is_set()
                        or conn not in self._ipc.active_clients()
                    ):
                        self._record_start_failure('cancelled')
                        raise RuntimeStartupError(
                            self._last_start_failure
                            or RuntimeStartFailure('cancelled', 'Cancelled')
                        )
                    self._session_access.clear_connection_auth(conn)
                    self._session_access.mark_authenticated(conn)
                    self._lifecycle = DaemonLifecycle.UNLOCKED
                    self._ipc.send_to(conn, create_event(EventType.DAEMON_UNLOCKED))
                    self._publish_active_status()
            except Exception as error:
                if not isinstance(error, RuntimeStartupError):
                    self._record_start_failure(start_phase, error)
                if not self._lock_runtime(preserve_reliability=False):
                    self._on_runtime_internal_error(
                        'Daemon startup cleanup remains incomplete.'
                    )
                self._ipc.send_to(conn, create_event(EventType.INTERNAL_ERROR))
                return

            return

        if isinstance(cmd, LockCommand):
            if self._lifecycle is not DaemonLifecycle.LOCKED:
                if not self._lock_runtime():
                    self._ipc.send_to(conn, create_event(EventType.INTERNAL_ERROR))
                    return
            self._ipc.broadcast(create_event(EventType.DAEMON_LOCKED))
            return

        if self._lifecycle is not DaemonLifecycle.UNLOCKED:
            self._ipc.send_to(conn, create_event(EventType.DAEMON_LOCKED))
            return

        if isinstance(cmd, ChangePasswordCommand):
            if self._km is None or not self._pm.uses_encrypted_storage():
                self._ipc.send_to(
                    conn,
                    create_event(EventType.PASSWORD_CHANGE_UNSUPPORTED),
                )
                return
            if not cmd.new_password:
                self._ipc.send_to(conn, create_event(EventType.INVALID_NEW_PASSWORD))
                return
            replacement_auth = None
            try:
                if self._require_session_auth:
                    replacement_auth = create_session_auth_context(cmd.new_password)
                self._km.change_password(cmd.current_password, cmd.new_password)
                if replacement_auth is not None:
                    self._session_access.install_context(replacement_auth)
                    replacement_auth = None
            except (InvalidMasterPasswordError, InvalidCredentialError):
                self._ipc.send_to(conn, create_event(EventType.INVALID_PASSWORD))
                return
            except Exception:
                self._ipc.send_to(conn, create_event(EventType.PASSWORD_CHANGE_FAILED))
                return
            finally:
                if replacement_auth is not None:
                    secure_clear_buffer(replacement_auth.proof_key)
            self._ipc.send_to(conn, create_event(EventType.PASSWORD_CHANGED))
            return

        if isinstance(cmd, RestrictClientCommand):
            self._ipc.send_to(conn, self._session_access.restrict(conn, cmd))
            return

        if isinstance(cmd, ConfigureQuickUnlockCommand):
            self._ipc.send_to(
                conn, self._session_access.configure_quick_unlock(conn, cmd)
            )
            return

        if isinstance(cmd, PrepareProfileExitCommand):
            profile = self._pm.profile_name
            if not self._lock_runtime(preserve_reliability=True):
                self._ipc.send_to(conn, create_event(EventType.INTERNAL_ERROR))
                return
            self._ipc.send_to(
                conn,
                create_event(
                    EventType.PROFILE_EXIT_PREPARED,
                    {'profile': profile},
                ),
            )
            return

        if isinstance(cmd, SelfDestructCommand):
            self._purge_operation_id = cmd.operation_id
            self._purge_fence.set()
            self._transport_state.invalidate_all_live_generations()
            self._lifecycle = DaemonLifecycle.LOCKING
            self._runtime_stop_flag.set()
            self._destruction_recipients = {conn}
            self._send_self_destruct_initiated(conn)
            try:
                threading.Thread(target=self._nuke_data, daemon=True).start()
            except Exception:
                self._nuke_data()
            return

        self._command_dispatcher.dispatch(cmd, conn)
