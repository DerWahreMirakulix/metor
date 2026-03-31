"""
Module defining the primary background daemon engine.
Orchestrates Network, IPC API, and Outbox routing seamlessly.
Handles Unlock operations, Nuke/Purge protocols, and Local Authentication constraints.
Enforces the Zero-Text Policy by emitting structured Domain-Driven payloads directly to the IPC interface.
Ensures strict SRP by routing incoming commands to dedicated Handlers.
"""

import socket
import threading
import time
import atexit
import sys
import os
import signal
import types
from typing import List, Set, Optional, Callable, Dict
from pathlib import Path

from metor.core import KeyManager, TorManager
from metor.core.api import (
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
    ClearHistoryCommand,
    GetMessagesCommand,
    ClearMessagesCommand,
    GetAddressCommand,
    GenerateAddressCommand,
    ClearProfileDbCommand,
    SetSettingCommand,
    SelfDestructCommand,
    UnlockCommand,
    RetunnelCommand,
    SystemCode,
    UiCode,
    DomainCode,
    JsonValue,
    ActionErrorEvent,
    ActionSuccessEvent,
    SettingUpdatedEvent,
)
from metor.data.profile import ProfileManager
from metor.data import (
    HistoryManager,
    ContactManager,
    MessageManager,
    Settings,
    SettingKey,
)
from metor.utils import Constants, clean_onion, secure_shred_file

# Local Package Imports
from metor.core.daemon.crypto import Crypto
from metor.core.daemon.ipc import IpcServer
from metor.core.daemon.outbox import OutboxWorker
from metor.core.daemon.network import NetworkManager
from metor.core.daemon.handlers import (
    DatabaseCommandHandler,
    SystemCommandHandler,
    NetworkCommandHandler,
)


class Daemon:
    """The main orchestrator binding network, cryptography, and logic together."""

    def __init__(
        self,
        pm: ProfileManager,
        km: KeyManager,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        status_callback: Optional[
            Callable[[DomainCode, Dict[str, JsonValue]], None]
        ] = None,
    ) -> None:
        """
        Initializes the DaemonEngine.

        Args:
            pm (ProfileManager): Profile configurations.
            km (KeyManager): Handles cryptographic keys.
            tm (TorManager): Manages the Tor process.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event logging.
            mm (MessageManager): Offline messages storage.
            status_callback (Optional[Callable]): Hook for UI-agnostic startup logging.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._km: KeyManager = km
        self._status_cb: Optional[
            Callable[[DomainCode, Dict[str, JsonValue]], None]
        ] = status_callback

        self._stop_flag: threading.Event = threading.Event()
        self._is_locked: bool = False
        self._authenticated_clients: Set[socket.socket] = set()

        self._crypto: Crypto = Crypto(km)
        self._ipc: IpcServer = IpcServer(
            pm, self._process_ui_command, self._on_ipc_disconnect
        )
        self._outbox: OutboxWorker = OutboxWorker(
            tm, mm, hm, self._crypto, self._ipc.broadcast, self._stop_flag
        )
        self._network: NetworkManager = NetworkManager(
            tm,
            cm,
            hm,
            mm,
            self._crypto,
            self._ipc.broadcast,
            self._ipc.has_active_clients,
            self._stop_flag,
        )

        self._db_handler: DatabaseCommandHandler = DatabaseCommandHandler(
            self._pm,
            self._cm,
            self._hm,
            self._mm,
            self._network.get_active_onions,
            self._ipc.broadcast,
        )
        self._sys_handler: SystemCommandHandler = SystemCommandHandler(
            self._pm, self._tm
        )
        self._network_handler: NetworkCommandHandler = NetworkCommandHandler(
            self._tm,
            self._cm,
            self._hm,
            self._mm,
            self._network,
            self._ipc.broadcast,
            self._send_to_client,
        )

        atexit.register(self.stop)
        if os.name != 'nt':
            signal.signal(signal.SIGTERM, self._sig_handler)
            signal.signal(signal.SIGHUP, self._sig_handler)

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
        sys.exit(0)

    def run(self) -> None:
        """
        Starts the Engine infrastructure.

        Args:
            None

        Returns:
            None
        """
        try:
            if getattr(self._km, '_password', None) is None and self._pm.is_remote():
                self._is_locked = True
                self._ipc.start()
                if self._status_cb:
                    self._status_cb(UiCode.DAEMON_LOCKED_MODE, {})
            else:
                self._start_subsystems()

            while not self._stop_flag.is_set():
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _start_subsystems(self) -> None:
        """
        Initializes the actual Tor and Network components once unlocked.

        Args:
            None

        Returns:
            None
        """
        self._pm.initialize()

        success, code, params = self._tm.start()
        if not success:
            if self._status_cb:
                self._status_cb(code, params)
            self._stop_flag.set()
            return

        self._network.start_listener()

        if not self._ipc.port:
            self._ipc.start()

        self._outbox.start()

        if self._status_cb:
            self._status_cb(
                UiCode.DAEMON_ACTIVE,
                {'onion': clean_onion(self._tm.onion or ''), 'port': self._ipc.port},
            )

    def stop(self) -> None:
        """
        Stops the engine and gracefully tears down all sub-services.

        Args:
            None

        Returns:
            None
        """
        self._stop_flag.set()
        self._network.disconnect_all()
        # Zero-trace cleanup: Force wipe all isolated orphans at shutdown
        if self._cm:
            self._cm.cleanup_orphans([])
        self._ipc.stop()
        self._pm.clear_daemon_port()
        self._tm.stop()

    def _nuke_data(self) -> None:
        """
        Securely erases local SQLite DB and Tor keys, and initiates shutdown.

        Args:
            None

        Returns:
            None
        """
        db_path: Path = Path(self._pm.get_config_dir()) / Constants.DB_FILE
        secure_shred_file(db_path)

        hs_dir: Path = Path(self._pm.get_hidden_service_dir())
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
        if Settings.get(SettingKey.REQUIRE_LOCAL_AUTH):
            if not isinstance(cmd, (InitCommand, UnlockCommand)):
                if conn not in self._authenticated_clients:
                    self._ipc.send_to(
                        conn,
                        ActionErrorEvent(
                            action=cmd.action,
                            code=SystemCode.AUTH_REQUIRED,
                        ),
                    )
                    return

        if isinstance(cmd, SelfDestructCommand):
            self._ipc.send_to(
                conn,
                ActionSuccessEvent(
                    action=cmd.action, code=SystemCode.SELF_DESTRUCT_INITIATED
                ),
            )
            threading.Thread(target=self._nuke_data, daemon=True).start()
            return

        if isinstance(cmd, UnlockCommand):
            if not self._is_locked:
                if (
                    Settings.get(SettingKey.REQUIRE_LOCAL_AUTH)
                    and conn not in self._authenticated_clients
                ):
                    try:
                        temp_km: KeyManager = KeyManager(self._pm, cmd.password)
                        temp_km.get_metor_key()
                        self._authenticated_clients.add(conn)
                        self._ipc.send_to(
                            conn,
                            ActionSuccessEvent(
                                action=cmd.action, code=SystemCode.SESSION_AUTHENTICATED
                            ),
                        )
                    except Exception:
                        self._ipc.send_to(
                            conn,
                            ActionErrorEvent(
                                action=cmd.action,
                                code=SystemCode.INVALID_PASSWORD,
                            ),
                        )
                    return

                self._ipc.send_to(
                    conn,
                    ActionSuccessEvent(
                        action=cmd.action, code=SystemCode.ALREADY_UNLOCKED
                    ),
                )
                return

            try:
                self._km = KeyManager(self._pm, cmd.password)
                self._km.get_metor_key()
            except Exception:
                self._ipc.send_to(
                    conn,
                    ActionErrorEvent(
                        action=cmd.action,
                        code=SystemCode.INVALID_PASSWORD,
                    ),
                )
                return

            self._tm = TorManager(self._pm, self._km)
            self._cm = ContactManager(self._pm, cmd.password)
            self._hm = HistoryManager(self._pm, cmd.password)
            self._mm = MessageManager(self._pm, cmd.password)

            self._crypto = Crypto(self._km)
            self._network = NetworkManager(
                self._tm,
                self._cm,
                self._hm,
                self._mm,
                self._crypto,
                self._ipc.broadcast,
                self._ipc.has_active_clients,
                self._stop_flag,
            )
            self._outbox = OutboxWorker(
                self._tm,
                self._mm,
                self._hm,
                self._crypto,
                self._ipc.broadcast,
                self._stop_flag,
            )

            self._db_handler = DatabaseCommandHandler(
                self._pm,
                self._cm,
                self._hm,
                self._mm,
                self._network.get_active_onions,
                self._ipc.broadcast,
            )
            self._sys_handler = SystemCommandHandler(self._pm, self._tm)
            self._network_handler = NetworkCommandHandler(
                self._tm,
                self._cm,
                self._hm,
                self._mm,
                self._network,
                self._ipc.broadcast,
                self._send_to_client,
            )

            self._is_locked = False
            self._authenticated_clients.add(conn)
            self._start_subsystems()
            self._ipc.send_to(
                conn,
                ActionSuccessEvent(action=cmd.action, code=SystemCode.DAEMON_UNLOCKED),
            )
            return

        if isinstance(cmd, SetSettingCommand):
            try:
                Settings.set(SettingKey(cmd.setting_key), cmd.setting_value)
                self._ipc.send_to(
                    conn,
                    SettingUpdatedEvent(
                        action=cmd.action,
                        code=SystemCode.SETTING_UPDATED,
                        key=cmd.setting_key,
                    ),
                )
            except TypeError as e:
                self._ipc.send_to(
                    conn,
                    ActionErrorEvent(
                        action=cmd.action,
                        code=SystemCode.SETTING_TYPE_ERROR,
                        reason=str(e),
                    ),
                )
            except Exception as e:
                self._ipc.send_to(
                    conn,
                    ActionErrorEvent(
                        action=cmd.action,
                        code=SystemCode.SETTING_UPDATE_FAILED,
                        reason=str(e),
                    ),
                )
            return

        if self._is_locked:
            self._ipc.send_to(
                conn,
                ActionErrorEvent(action=cmd.action, code=SystemCode.DAEMON_LOCKED),
            )
            return

        # --- DELEGATION TO DEDICATED HANDLERS ---

        if isinstance(
            cmd,
            (
                InitCommand,
                GetConnectionsCommand,
                ConnectCommand,
                DisconnectCommand,
                AcceptCommand,
                RejectCommand,
                MsgCommand,
                FallbackCommand,
                SendDropCommand,
                SwitchCommand,
                RetunnelCommand,
            ),
        ):
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
                ClearHistoryCommand,
                GetMessagesCommand,
                ClearMessagesCommand,
                GetInboxCommand,
                MarkReadCommand,
            ),
        ):
            self._ipc.send_to(conn, self._db_handler.handle(cmd))

        elif isinstance(cmd, (GetAddressCommand, GenerateAddressCommand)):
            self._ipc.send_to(conn, self._sys_handler.handle(cmd))
