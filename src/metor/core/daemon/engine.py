"""
Module defining the primary background daemon engine.
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
from typing import List, Set, Optional, Callable, Dict, Union
from pathlib import Path

from metor.core import KeyManager, TorManager
from metor.core.api import (
    AuthenticateSessionCommand,
    IpcEvent,
    IpcCommand,
    InitCommand,
    GetConnectionsCommand,
    GetContactsListCommand,
    ConnectCommand,
    DisconnectCommand,
    AcceptCommand,
    RejectCommand,
    MsgCommand,
    RegisterLiveConsumerCommand,
    AddContactCommand,
    RemoveContactCommand,
    RenameContactCommand,
    ClearContactsCommand,
    SwitchCommand,
    SendDropCommand,
    GetInboxCommand,
    MarkReadCommand,
    FallbackCommand,
    GetHistoryCommand,
    GetRawHistoryCommand,
    ClearHistoryCommand,
    GetMessagesCommand,
    ClearMessagesCommand,
    GetAddressCommand,
    GenerateAddressCommand,
    ClearProfileDbCommand,
    SetSettingCommand,
    GetSettingCommand,
    SetConfigCommand,
    GetConfigCommand,
    SyncConfigCommand,
    SelfDestructCommand,
    UnlockCommand,
    RetunnelCommand,
    EventType,
    JsonValue,
    create_event,
)
from metor.data.profile import ProfileManager
from metor.data import (
    HistoryManager,
    ContactManager,
    MessageManager,
    SettingKey,
)
from metor.utils import Constants, clean_onion, secure_shred_file

# Local Package Imports
from metor.core.daemon.crypto import Crypto
from metor.core.daemon.ipc import IpcServer
from metor.core.daemon.outbox import OutboxWorker
from metor.core.daemon.network import NetworkManager, StateTracker
from metor.core.daemon.models import DaemonStatus
from metor.core.daemon.bootstrap import (
    build_runtime,
    CorruptedStorageError,
    DaemonRuntime,
    InvalidMasterPasswordError,
)
from metor.core.daemon.handlers import (
    DatabaseCommandHandler,
    SystemCommandHandler,
    NetworkCommandHandler,
    ConfigCommandHandler,
)


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
        status_callback: Optional[
            Callable[[Union[EventType, DaemonStatus], Dict[str, JsonValue]], None]
        ] = None,
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
            status_callback (Optional[Callable]): Hook for UI-agnostic startup logging.
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
        self._status_cb: Optional[
            Callable[[Union[EventType, DaemonStatus], Dict[str, JsonValue]], None]
        ] = status_callback

        self._stop_flag: threading.Event = threading.Event()
        self._stop_lock: threading.Lock = threading.Lock()
        self._is_locked: bool = start_locked
        self._is_stopping: bool = False
        self._authenticated_clients: Set[socket.socket] = set()
        self._live_consumer_clients: Set[socket.socket] = set()
        self._transport_state: StateTracker = StateTracker()

        self._crypto: Optional[Crypto] = None
        self._ipc: IpcServer = IpcServer(
            pm, self._process_ui_command, self._on_ipc_disconnect
        )
        self._outbox: Optional[OutboxWorker] = None
        self._network: Optional[NetworkManager] = None

        self._config_handler: ConfigCommandHandler = ConfigCommandHandler(self._pm)
        self._db_handler: Optional[DatabaseCommandHandler] = None
        self._sys_handler: Optional[SystemCommandHandler] = None
        self._network_handler: Optional[NetworkCommandHandler] = None

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
                )
            )

        atexit.register(self.stop)
        if os.name != 'nt':
            signal.signal(signal.SIGINT, self._sig_handler)
            signal.signal(signal.SIGTERM, self._sig_handler)
            signal.signal(signal.SIGHUP, self._sig_handler)

    def _install_runtime(self, runtime: DaemonRuntime) -> None:
        """
        Installs the authenticated runtime components after direct startup or unlock.

        Args:
            runtime (DaemonRuntime): The authenticated runtime bundle.

        Returns:
            None
        """
        self._km = runtime.km
        self._tm = runtime.tm
        self._cm = runtime.cm
        self._hm = runtime.hm
        self._mm = runtime.mm
        self._transport_state = StateTracker()

        self._crypto = Crypto(runtime.km)
        self._network = NetworkManager(
            runtime.tm,
            runtime.cm,
            runtime.hm,
            runtime.mm,
            self._crypto,
            self._ipc.broadcast,
            self._ipc.has_active_clients,
            self._has_live_consumers,
            self._stop_flag,
            config=self._pm.config,
            state=self._transport_state,
        )
        self._outbox = OutboxWorker(
            runtime.tm,
            runtime.mm,
            runtime.hm,
            self._crypto,
            self._ipc.broadcast,
            self._stop_flag,
            config=self._pm.config,
            state=self._transport_state,
        )
        self._db_handler = DatabaseCommandHandler(
            self._pm,
            runtime.cm,
            runtime.hm,
            runtime.mm,
            self._network.get_active_onions,
            self._ipc.broadcast,
        )
        self._sys_handler = SystemCommandHandler(self._pm, runtime.tm)
        self._network_handler = NetworkCommandHandler(
            runtime.tm,
            runtime.cm,
            runtime.hm,
            runtime.mm,
            self._network,
            self._outbox,
            self._ipc.broadcast,
            self._send_to_client,
            self._register_live_consumer,
            config=self._pm.config,
        )

    def _has_live_consumers(self) -> bool:
        """
        Checks whether an interactive chat session is currently attached.

        Args:
            None

        Returns:
            bool: True if at least one live consumer is connected.
        """
        return bool(self._live_consumer_clients)

    def _register_live_consumer(self, conn: socket.socket) -> None:
        """
        Marks one IPC session as an interactive live-message consumer.

        Args:
            conn (socket.socket): The IPC session socket.

        Returns:
            None
        """
        had_consumers: bool = self._has_live_consumers()
        self._live_consumer_clients.add(conn)
        if not had_consumers and self._network is not None:
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
            if self._is_locked:
                self._ipc.start()
                if self._status_cb:
                    self._status_cb(DaemonStatus.LOCKED_MODE, {})
            else:
                self._start_subsystems()

            while not self._stop_flag.is_set():
                time.sleep(Constants.WORKER_SLEEP_SEC)
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

        self._network.start_listener()

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
            self._authenticated_clients.clear()
            self._live_consumer_clients.clear()

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
        secure_shred_file(runtime_db_path)

        try:
            self._pm.clear_daemon_port(
                expected_pid=os.getpid(),
                expected_port=self._ipc.port,
            )
        except Exception:
            pass

        try:
            if self._tm is not None:
                self._tm.stop()
        except Exception:
            pass

    def _nuke_data(self) -> None:
        """
        Securely erases local SQLite DB and Tor keys, and initiates shutdown.

        Args:
            None

        Returns:
            None
        """
        db_path: Path = self._pm.paths.get_db_file()
        runtime_db_path: Path = (
            self._pm.paths.get_config_dir() / Constants.DB_RUNTIME_FILE
        )
        secure_shred_file(db_path)
        secure_shred_file(runtime_db_path)

        hs_dir: Path = self._pm.paths.get_hidden_service_dir()
        key_files: List[str] = [
            Constants.METOR_SECRET_KEY,
            Constants.TOR_SECRET_KEY,
            f'{Constants.TOR_SECRET_KEY}.enc',
            Constants.TOR_PUBLIC_KEY,
        ]
        for key_file in key_files:
            secure_shred_file(hs_dir / key_file)

        self.stop()

    def _on_ipc_disconnect(self, conn: socket.socket) -> None:
        """
        Callback fired when an IPC client disconnects. Cleans up authentication states.

        Args:
            conn (socket.socket): The disconnected client socket.

        Returns:
            None
        """
        if conn in self._authenticated_clients:
            self._authenticated_clients.remove(conn)

        self._live_consumer_clients.discard(conn)

        if self._network_handler is not None:
            self._network_handler.clear_client_focus(conn)

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
        if (
            self._pm.config.get_bool(SettingKey.REQUIRE_LOCAL_AUTH)
            and not self._is_locked
        ):
            if not isinstance(
                cmd, (InitCommand, AuthenticateSessionCommand, UnlockCommand)
            ):
                if conn not in self._authenticated_clients:
                    self._ipc.send_to(
                        conn,
                        create_event(EventType.AUTH_REQUIRED),
                    )
                    return

        if isinstance(cmd, SelfDestructCommand):
            self._ipc.send_to(
                conn,
                create_event(EventType.SELF_DESTRUCT_INITIATED),
            )
            threading.Thread(target=self._nuke_data, daemon=True).start()
            return

        if isinstance(cmd, AuthenticateSessionCommand):
            if self._is_locked:
                self._ipc.send_to(conn, create_event(EventType.DAEMON_LOCKED))
                return

            if not self._pm.config.get_bool(SettingKey.REQUIRE_LOCAL_AUTH):
                self._authenticated_clients.add(conn)
                self._ipc.send_to(
                    conn,
                    create_event(EventType.SESSION_AUTHENTICATED),
                )
                return

            if conn in self._authenticated_clients:
                self._ipc.send_to(
                    conn,
                    create_event(EventType.SESSION_AUTHENTICATED),
                )
                return

            try:
                temp_km: KeyManager = KeyManager(self._pm, cmd.password)
                temp_km.get_metor_key()
                self._authenticated_clients.add(conn)
                self._ipc.send_to(
                    conn,
                    create_event(EventType.SESSION_AUTHENTICATED),
                )
            except Exception:
                self._ipc.send_to(
                    conn,
                    create_event(EventType.INVALID_PASSWORD),
                )
            return

        if isinstance(cmd, UnlockCommand):
            if not self._is_locked:
                self._ipc.send_to(
                    conn,
                    create_event(EventType.ALREADY_UNLOCKED),
                )
                return

            try:
                runtime = build_runtime(self._pm, cmd.password)
            except InvalidMasterPasswordError:
                self._ipc.send_to(
                    conn,
                    create_event(EventType.INVALID_PASSWORD),
                )
                return
            except CorruptedStorageError:
                self._ipc.send_to(conn, create_event(EventType.DB_CORRUPTED))
                return

            self._install_runtime(runtime)

            self._is_locked = False
            self._authenticated_clients.add(conn)
            if not self._start_subsystems():
                return
            self._ipc.send_to(conn, create_event(EventType.DAEMON_UNLOCKED))
            return

        if self._is_locked:
            self._ipc.send_to(conn, create_event(EventType.DAEMON_LOCKED))
            return

        # --- DELEGATION TO DEDICATED HANDLERS ---

        if isinstance(
            cmd,
            (
                SetSettingCommand,
                GetSettingCommand,
                SetConfigCommand,
                GetConfigCommand,
                SyncConfigCommand,
            ),
        ):
            self._ipc.send_to(conn, self._config_handler.handle(cmd))

        elif isinstance(
            cmd,
            (
                InitCommand,
                GetConnectionsCommand,
                ConnectCommand,
                DisconnectCommand,
                AcceptCommand,
                RejectCommand,
                MsgCommand,
                RegisterLiveConsumerCommand,
                FallbackCommand,
                SendDropCommand,
                SwitchCommand,
                RetunnelCommand,
            ),
        ):
            if self._network_handler is None:
                self._ipc.send_to(conn, create_event(EventType.DAEMON_OFFLINE))
                return
            self._network_handler.handle(cmd, conn)

        elif isinstance(
            cmd,
            (
                GetContactsListCommand,
                AddContactCommand,
                RemoveContactCommand,
                RenameContactCommand,
                ClearContactsCommand,
                ClearProfileDbCommand,
                GetHistoryCommand,
                GetRawHistoryCommand,
                ClearHistoryCommand,
                GetMessagesCommand,
                ClearMessagesCommand,
                GetInboxCommand,
                MarkReadCommand,
            ),
        ):
            if self._db_handler is None:
                self._ipc.send_to(conn, create_event(EventType.DAEMON_OFFLINE))
                return
            self._ipc.send_to(conn, self._db_handler.handle(cmd))

        elif isinstance(cmd, (GetAddressCommand, GenerateAddressCommand)):
            if self._sys_handler is None:
                self._ipc.send_to(conn, create_event(EventType.DAEMON_OFFLINE))
                return
            self._ipc.send_to(conn, self._sys_handler.handle(cmd))
