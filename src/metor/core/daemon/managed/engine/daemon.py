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
from enum import Enum
from typing import Optional, Callable, Dict, Union
from pathlib import Path

from metor.core.api import (
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
from metor.core.profile_destruction import destroy_profile_storage
from metor.core.tor import TorManager
from metor.data.profile import ProfileManager
from metor.data import (
    HistoryManager,
    ContactManager,
    MessageManager,
    SettingKey,
)
from metor.data.sql import SqlManager
from metor.data.blob import BlobLifecycle, BlobStore
from metor.utils import Constants, clean_onion, secure_shred_file

# Local Package Imports
from metor.core.daemon.managed.crypto import Crypto
from metor.core.daemon.managed.bootstrap import (
    build_runtime,
    CorruptedStorageError,
    DaemonRuntime,
)
from metor.core.daemon.managed.handlers import NetworkCommandHandler
from metor.core.daemon.managed.ipc import IpcServer
from metor.core.daemon.managed.outbox import OutboxWorker
from metor.core.daemon.managed.network import NetworkManager, StateTracker
from metor.core.daemon.managed.notify import NotificationService
from metor.core.daemon import InvalidMasterPasswordError
from metor.core.daemon.managed.local_auth import SessionAuthContext
from metor.core.daemon.managed.quick_unlock import QuickUnlockStore
from metor.core.daemon.managed.status import DaemonStatus
from metor.core.daemon.handlers import (
    ConfigCommandHandler,
    DatabaseCommandHandler,
    SystemCommandHandler,
)

from .command_dispatch import DaemonCommandDispatcher
from .session_access import SessionAccessController
from .session_maintenance import SessionMaintenance


class DaemonLifecycle(str, Enum):
    """Security-relevant daemon lifecycle states."""

    LOCKED = 'locked'
    UNLOCKING = 'unlocking'
    UNLOCKED = 'unlocked'
    LOCKING = 'locking'


class Daemon:
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
        self._stop_lock: threading.Lock = threading.Lock()
        self._lifecycle: DaemonLifecycle = (
            DaemonLifecycle.LOCKED if start_locked else DaemonLifecycle.UNLOCKED
        )
        self._is_stopping: bool = False
        self._runtime_stop_flag: threading.Event = threading.Event()
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
            voice_delivery_callback=self._voice_delivery,
        )

        if (
            km is not None
            and tm is not None
            and cm is not None
            and hm is not None
            and mm is not None
        ):
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

        atexit.register(self.stop)
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
        )
        self._session_maintenance = SessionMaintenance(
            network=self._network,
            state=self._transport_state,
            mm=runtime.mm,
            config=self._pm.config,
        )
        active_blob_store = runtime.blob_store

        def delete_persistent_blob_object(blob_id: str) -> None:
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
        system_handler = SystemCommandHandler(self._pm, runtime.tm)
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
        )
        self._command_dispatcher.install_runtime_handlers(
            network=network_handler,
            database=database_handler,
            system=system_handler,
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
        if self._lifecycle is DaemonLifecycle.LOCKING:
            return
        stamp_request_id(event)
        recipients = (
            self._session_access.authenticated_recipients()
            if self._session_access.requires_auth()
            else self._ipc.active_clients()
        )
        for recipient in recipients:
            filtered = self._session_access.filter_restricted_event(recipient, event)
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
        self._ipc.send_to(conn, event)

    def _sig_handler(self, signum: int, frame: Optional[types.FrameType]) -> None:
        """
        Handles termination signals gracefully.

        Args:
            signum (int): The signal number.
            frame (Optional[types.FrameType]): The current stack frame.

        Returns:
            None
        """
        self.stop()

    def run(self) -> None:
        """
        Starts the Engine infrastructure.

        Args:
            None

        Returns:
            None
        """
        try:
            if self._lifecycle is DaemonLifecycle.LOCKED:
                self._ipc.start()
                if self._status_cb:
                    self._status_cb(DaemonStatus.LOCKED_MODE, {})
            else:
                self._start_subsystems()

            while not self._stop_flag.is_set():
                time.sleep(Constants.WORKER_SLEEP_SEC)
                if self._session_maintenance is not None:
                    self._session_maintenance.check_idle_timeouts()
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
        if self._tm is None or self._network is None or self._outbox is None:
            self.stop()
            return False

        self._pm.initialize()

        success, event_type, params = self._tm.start()
        if not success:
            if self._status_cb and event_type is not None:
                self._status_cb(event_type, params)
            self.stop()
            return False

        try:
            self._network.start_listener()
        except RuntimeError as exc:
            self._on_runtime_internal_error(str(exc))
            self.stop()
            return False

        if not self._ipc.port:
            self._ipc.start()

        self._outbox.start()

        if self._status_cb:
            self._status_cb(
                DaemonStatus.ACTIVE,
                {'onion': clean_onion(self._tm.onion or ''), 'port': self._ipc.port},
            )

        return True

    def stop(self) -> None:
        """
        Stops the engine and gracefully tears down all sub-services.

        Args:
            None

        Returns:
            None
        """
        with self._stop_lock:
            if self._is_stopping:
                return
            self._is_stopping = True
            self._stop_flag.set()
            self._runtime_stop_flag.set()
            self._session_access.clear_all()

        try:
            if self._outbox is not None:
                self._outbox.stop()
        except Exception:
            pass

        try:
            if self._network is not None:
                self._network.disconnect_all()
        except Exception:
            pass

        try:
            if self._cm is not None:
                self._cm.cleanup_orphans([])
        except Exception:
            pass

        try:
            self._ipc.stop()
        except Exception:
            pass

        runtime_db_path: Path = (
            self._pm.paths.get_config_dir() / Constants.DB_RUNTIME_FILE
        )
        try:
            secure_shred_file(runtime_db_path)
        except OSError:
            self._on_runtime_internal_error(
                'Failed to shred the runtime database mirror during shutdown.'
            )

        try:
            self._pm.clear_daemon_port(
                expected_pid=os.getpid(),
                expected_port=self._ipc.port,
            )
        except Exception:
            pass

        SqlManager.close_connection(self._pm.paths.get_db_file())

        try:
            if self._tm is not None:
                self._tm.stop()
        except Exception:
            pass

        try:
            if getattr(self, '_blob_store', None) is not None:
                assert self._blob_store is not None
                self._blob_store.close()
        except Exception:
            pass

        try:
            if self._km is not None:
                self._km.clear_sensitive_state()
        except Exception:
            pass

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
        try:
            destroy_profile_storage(
                self._pm,
                prepare_runtime=lambda: self._lock_runtime(preserve_reliability=False),
            )
            ipc = getattr(self, '_ipc', None)
            if ipc is not None:
                ipc.broadcast(create_event(EventType.SELF_DESTRUCT_COMPLETED))
        except OSError:
            self._on_runtime_internal_error(
                'Encrypted profile cleanup was incomplete after PMK destruction.'
            )
        finally:
            self.stop()

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
        """Resolves aliases to the stable onion identity used by lock policy."""
        if self._cm is None:
            return None
        resolved = self._cm.resolve_target(target)
        return resolved[1] if resolved is not None else None

    def _voice_target(self, msg_id: str) -> Optional[str]:
        """Returns the stable target bound to an active outbound Voice turn."""
        return self._network.voice_target(msg_id) if self._network is not None else None

    def _voice_delivery(self, msg_id: str) -> Optional[Delivery]:
        """Returns delivery semantics bound to an active outbound Voice turn."""
        return (
            self._network.voice_delivery(msg_id) if self._network is not None else None
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
            self._process_ui_command_in_context(cmd, conn)

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

        if (
            isinstance(cmd, SelfDestructCommand)
            and self._lifecycle is DaemonLifecycle.LOCKED
            and not self._pm.config.get_bool(SettingKey.SELF_DESTRUCT_REQUIRES_UNLOCK)
        ):
            self._lifecycle = DaemonLifecycle.LOCKING
            self._ipc.send_to(
                conn,
                create_event(EventType.SELF_DESTRUCT_INITIATED),
            )
            threading.Thread(target=self._nuke_data, daemon=True).start()
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

            self._install_runtime(runtime)

            self._lifecycle = DaemonLifecycle.UNLOCKED
            self._session_access.clear_connection_auth(conn)
            self._session_access.mark_authenticated(conn)
            if not self._start_subsystems():
                return
            self._ipc.send_to(conn, create_event(EventType.DAEMON_UNLOCKED))
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
            try:
                self._km.change_password(cmd.current_password, cmd.new_password)
            except (InvalidMasterPasswordError, InvalidCredentialError):
                self._ipc.send_to(conn, create_event(EventType.INVALID_PASSWORD))
                return
            except Exception:
                self._ipc.send_to(conn, create_event(EventType.PASSWORD_CHANGE_FAILED))
                return
            self._ipc.send_to(conn, create_event(EventType.PASSWORD_CHANGED))
            return

        if isinstance(cmd, RestrictClientCommand):
            self._ipc.send_to(conn, self._session_access.restrict(conn, cmd))
            return

        if isinstance(cmd, ConfigureQuickUnlockCommand):
            self._ipc.send_to(conn, self._session_access.configure_quick_unlock(cmd))
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
            self._lifecycle = DaemonLifecycle.LOCKING
            self._runtime_stop_flag.set()
            if self._network is not None:
                self._network.abort_all()
            self._ipc.send_to(
                conn,
                create_event(EventType.SELF_DESTRUCT_INITIATED),
            )
            threading.Thread(target=self._nuke_data, daemon=True).start()
            return

        self._command_dispatcher.dispatch(cmd, conn)
