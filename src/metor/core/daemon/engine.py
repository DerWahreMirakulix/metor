"""
Module defining the primary background daemon engine.
Orchestrates Network, IPC API, and Outbox routing seamlessly.
Handles Unlock operations, Nuke/Purge protocols, and Local Authentication constraints.
"""

import socket
import threading
import time
import atexit
import sys
import os
import signal
from typing import Any, List, Optional, Set
from pathlib import Path

from metor.core.key import KeyManager
from metor.core.tor import TorManager
from metor.core.api import (
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
    SystemEvent,
    CliResponseEvent,
    InitEvent,
    ConnectionsStateEvent,
    ContactListEvent,
    InfoEvent,
    InboxDataEvent,
    SwitchSuccessEvent,
    RenameSuccessEvent,
    ContactRemovedEvent,
)
from metor.data.profile import ProfileManager
from metor.data.history import HistoryManager, HistoryEvent
from metor.data.contact import ContactManager
from metor.data.message import (
    MessageManager,
    MessageDirection,
    MessageType,
    MessageStatus,
)
from metor.data.settings import Settings, SettingKey
from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.utils.helper import clean_onion, secure_shred_file

# Local Package Imports
from metor.core.daemon.crypto import Crypto
from metor.core.daemon.ipc import IpcServer
from metor.core.daemon.outbox import OutboxWorker
from metor.core.daemon.network import NetworkManager


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
    ) -> None:
        """
        Initializes the DaemonEngine.

        Args:
            pm (ProfileManager): Profile configurations.
            km (KeyManager): Handles cryptographic keys.
            tm (TorManager): Manages the Tor process.
            cm (ContactManager): Address book and alias resolver.
            hm (HistoryManager): Event logging.
            mm (MessageManager): Offline messages storage.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._km: KeyManager = km

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

        atexit.register(self.stop)
        if os.name != 'nt':
            signal.signal(signal.SIGTERM, self._sig_handler)
            signal.signal(signal.SIGHUP, self._sig_handler)

    def _sig_handler(self, signum: int, frame: Any) -> None:
        """
        Handles termination signals gracefully.

        Args:
            signum (int): The signal number.
            frame (Any): The current stack frame.

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
                print('Daemon running in LOCKED mode... Waiting for IPC unlock.')
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

        success, msg = self._tm.start()
        if not success:
            print(f'{Theme.RED}{msg}{Theme.RESET}')
            self._stop_flag.set()
            return

        self._network.start_listener()

        if not self._ipc.port:
            self._ipc.start()

        self._outbox.start()

        print(
            f'Daemon active. Onion: {Theme.YELLOW}{clean_onion(self._tm.onion or "")}{Theme.RESET}.onion '
            f'| IPC Port: {Theme.YELLOW}{self._ipc.port}{Theme.RESET}'
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

        self._ipc.broadcast(
            SystemEvent(
                text='Daemon self-destruction initiated. Shutting down immediately...'
            )
        )

        self.stop()

    def _is_self_target(self, target: str) -> bool:
        """
        Safely checks if a target (alias or onion) points to our own identity.

        Args:
            target (str): The alias or onion to check.

        Returns:
            bool: True if it matches our own onion, False otherwise.
        """
        if not target or not self._tm.onion:
            return False

        if clean_onion(target) == clean_onion(self._tm.onion):
            return True

        onion_by_alias: Optional[str] = self._cm.get_onion_by_alias(target)
        if onion_by_alias and onion_by_alias == self._tm.onion:
            return True

        return False

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
        Routes typed IPC commands from the Chat UI or CLI Proxy to the internal managers.
        Enforces local authentication requirements prior to parsing state commands.

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
                        SystemEvent(
                            text='Authentication required. Please unlock the session first.'
                        ),
                    )
                    return

        if isinstance(cmd, SelfDestructCommand):
            self._ipc.send_to(
                conn,
                CliResponseEvent(
                    text='Self-destruct command accepted. Nuking daemon...'
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
                            CliResponseEvent(
                                text='Session authenticated successfully.'
                            ),
                        )
                    except Exception:
                        self._ipc.send_to(
                            conn, CliResponseEvent(text='Invalid master password.')
                        )
                    return

                self._ipc.send_to(
                    conn, CliResponseEvent(text='Daemon is already unlocked.')
                )
                return

            try:
                self._km = KeyManager(self._pm, cmd.password)
                self._km.get_metor_key()
            except Exception:
                self._ipc.send_to(
                    conn, CliResponseEvent(text='Invalid master password.')
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

            self._is_locked = False
            self._authenticated_clients.add(conn)
            self._start_subsystems()
            self._ipc.send_to(
                conn, CliResponseEvent(text='Daemon unlocked successfully.')
            )
            return

        if isinstance(cmd, SetSettingCommand):
            try:
                Settings.set(SettingKey(cmd.setting_key), cmd.setting_value)
                self._ipc.send_to(
                    conn,
                    CliResponseEvent(
                        text=f"Daemon setting '{cmd.setting_key}' updated."
                    ),
                )
            except TypeError as e:
                self._ipc.send_to(conn, CliResponseEvent(text=str(e), success=False))
            except Exception:
                self._ipc.send_to(
                    conn,
                    CliResponseEvent(text='Failed to update setting.', success=False),
                )
            return

        if self._is_locked:
            self._ipc.send_to(
                conn, CliResponseEvent(text='Daemon is locked. Please unlock first.')
            )
            return

        if isinstance(cmd, InitCommand):
            self._ipc.send_to(conn, InitEvent(onion=self._tm.onion))
            for active_onion in self._network.get_active_onions():
                self._network.flush_ram_buffer(active_onion)

        elif isinstance(cmd, GetConnectionsCommand):
            self._ipc.send_to(
                conn,
                ConnectionsStateEvent(
                    active=self._network.get_active_aliases(),
                    pending=self._network.get_pending_aliases(),
                    contacts=self._cm.get_all_contacts(),
                    is_header=cmd.is_header,
                ),
            )
            for active_onion in self._network.get_active_onions():
                self._network.flush_ram_buffer(active_onion)

        elif isinstance(cmd, GetContactsListCommand):
            self._ipc.send_to(conn, ContactListEvent(text=self._cm.show(cmd.chat_mode)))

        elif isinstance(cmd, ConnectCommand):
            if self._is_self_target(cmd.target):
                self._ipc.send_to(
                    conn, SystemEvent(text='You cannot connect to yourself.')
                )
                return

            alias, _, exists = self._cm.resolve_target(cmd.target, auto_create=True)

            if not exists:
                self._ipc.send_to(
                    conn,
                    SystemEvent(
                        text=f"Invalid target: '{cmd.target}' is neither a known contact nor a valid onion address."
                    ),
                )
                return

            self._ipc.broadcast(
                InfoEvent(
                    alias=alias,
                    # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                    text="Connecting to '{alias}'...",
                )
            )
            threading.Thread(
                target=self._network.connect_to, args=(cmd.target,), daemon=True
            ).start()

        elif isinstance(cmd, DisconnectCommand):
            self._network.disconnect(cmd.target, initiated_by_self=True)

        elif isinstance(cmd, AcceptCommand):
            self._network.accept(cmd.target)

        elif isinstance(cmd, RejectCommand):
            self._network.reject(cmd.target, initiated_by_self=True)

        elif isinstance(cmd, MsgCommand):
            self._network.send_message(cmd.target, cmd.text, cmd.msg_id)

        elif isinstance(cmd, FallbackCommand):
            success, msg = self._network.force_fallback(cmd.target)
            alias, _, _ = self._cm.resolve_target(cmd.target, default_value=cmd.target)
            self._ipc.send_to(
                conn, CliResponseEvent(text=msg, success=success, alias=alias)
            )

        elif isinstance(cmd, SendDropCommand):
            if not Settings.get(SettingKey.ALLOW_DROPS):
                self._ipc.send_to(
                    conn,
                    SystemEvent(
                        text='Async offline messages are disabled by security policy.'
                    ),
                )
                return

            if self._is_self_target(cmd.target):
                self._ipc.send_to(
                    conn, SystemEvent(text='You cannot send offline drops to yourself.')
                )
                return

            alias, onion, exists = self._cm.resolve_target(cmd.target, auto_create=True)

            if exists:
                self._mm.queue_message(
                    onion,
                    MessageDirection.OUT,
                    MessageType.TEXT,
                    cmd.text,
                    MessageStatus.PENDING,
                )
                if Settings.get(SettingKey.RECORD_DROP_EVENTS):
                    self._hm.log_event(
                        HistoryEvent.ASYNC_QUEUED,
                        onion,
                    )

                if cmd.cli_mode:
                    self._ipc.send_to(
                        conn,
                        CliResponseEvent(
                            text=f"Message successfully queued for '{alias}'.",
                            alias=alias,
                        ),
                    )
            else:
                if cmd.cli_mode:
                    self._ipc.send_to(
                        conn,
                        CliResponseEvent(
                            text=f"Invalid target: '{cmd.target}'.",
                            success=False,
                        ),
                    )

        elif isinstance(cmd, GetInboxCommand):
            if cmd.cli_mode:
                text: str = self._mm.show_inbox(self._cm)
                self._ipc.send_to(conn, CliResponseEvent(text=text))
            else:
                self._ipc.send_to(
                    conn, InboxDataEvent(inbox_counts=self._mm.get_unread_counts())
                )

        elif isinstance(cmd, MarkReadCommand):
            if cmd.cli_mode:
                text: str = self._mm.show_read(cmd.target, self._cm)
                alias, _, _ = self._cm.resolve_target(
                    cmd.target, default_value=cmd.target
                )
                self._ipc.send_to(conn, CliResponseEvent(text=text, alias=alias))
            else:
                alias, onion, exists = self._cm.resolve_target(cmd.target)
                if exists:
                    raw_messages = self._mm.get_and_read_inbox(onion)
                    messages = [
                        {'id': r[0], 'type': r[1], 'payload': r[2], 'timestamp': r[3]}
                        for r in raw_messages
                    ]
                    self._ipc.send_to(
                        conn, InboxDataEvent(alias=alias, messages=messages)
                    )

        elif isinstance(cmd, SwitchCommand):
            if cmd.target is None or cmd.target == '..':
                self._ipc.send_to(conn, SwitchSuccessEvent(alias=None))
            else:
                if self._is_self_target(cmd.target):
                    self._ipc.send_to(
                        conn, SystemEvent(text='You cannot switch focus to yourself.')
                    )
                    return

                alias, _, exists = self._cm.resolve_target(cmd.target)

                if not exists:
                    self._ipc.send_to(
                        conn,
                        SystemEvent(text=f"Invalid target: '{cmd.target}' not found."),
                    )
                    return

                self._ipc.send_to(conn, SwitchSuccessEvent(alias=alias))

        elif isinstance(cmd, GetHistoryCommand):
            alias, _, _ = self._cm.resolve_target(cmd.target, default_value=cmd.target)
            text: str = self._hm.show(self._cm, cmd.target, cmd.limit)
            self._ipc.send_to(conn, CliResponseEvent(text=text, alias=alias))

        elif isinstance(cmd, ClearHistoryCommand):
            active_onions = self._network.get_active_onions()
            alias, onion, exists = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )

            if cmd.target and not exists:
                success, msg = False, 'Contact not found.'
            else:
                success, msg = self._hm.clear_history(onion)

            deleted_aliases: List[str] = self._cm.cleanup_orphans(active_onions)
            for a in deleted_aliases:
                self._ipc.broadcast(ContactRemovedEvent(alias=a))

            self._ipc.send_to(
                conn, CliResponseEvent(text=msg, success=success, alias=alias)
            )

        elif isinstance(cmd, GetMessagesCommand):
            alias, _, _ = self._cm.resolve_target(cmd.target, default_value=cmd.target)
            if cmd.target:
                text = self._mm.show_history(cmd.target, self._cm, cmd.limit)
            else:
                text = 'No target specified.'
            self._ipc.send_to(conn, CliResponseEvent(text=text, alias=alias))

        elif isinstance(cmd, ClearMessagesCommand):
            active_onions = self._network.get_active_onions()
            alias, onion, exists = self._cm.resolve_target(
                cmd.target, default_value=cmd.target
            )

            if cmd.target and not exists:
                success, msg = False, 'Contact not found.'
            else:
                success, msg = self._mm.clear_messages(onion, cmd.non_contacts_only)

            deleted_aliases = self._cm.cleanup_orphans(active_onions)
            for a in deleted_aliases:
                self._ipc.broadcast(ContactRemovedEvent(alias=a))

            self._ipc.send_to(
                conn, CliResponseEvent(text=msg, success=success, alias=alias)
            )

        elif isinstance(cmd, ClearContactsCommand):
            active_onions = self._network.get_active_onions()
            success_c, msg, renames, removed = self._cm.clear_contacts(active_onions)
            if success_c:
                for old, new, was_saved in renames:
                    self._ipc.broadcast(
                        RenameSuccessEvent(
                            old_alias=old,
                            new_alias=new,
                            is_demotion=True,
                            was_saved=was_saved,
                        )
                    )
                for a in removed:
                    self._ipc.broadcast(ContactRemovedEvent(alias=a))
            self._ipc.send_to(conn, CliResponseEvent(text=msg, success=success_c))

        elif isinstance(cmd, ClearProfileDbCommand):
            active_onions = self._network.get_active_onions()
            success_c, _, renames, removed = self._cm.clear_contacts(active_onions)
            success_h, _ = self._hm.clear_history()
            success_m, _ = self._mm.clear_messages()

            success: bool = success_c and success_h and success_m
            msg: str = (
                f"Database for profile '{self._pm.profile_name}' successfully cleared."
                if success
                else 'Error clearing database.'
            )
            if success_c:
                for old, new, was_saved in renames:
                    self._ipc.broadcast(
                        RenameSuccessEvent(
                            old_alias=old,
                            new_alias=new,
                            is_demotion=True,
                            was_saved=was_saved,
                        )
                    )
                for a in removed:
                    self._ipc.broadcast(ContactRemovedEvent(alias=a))
            self._ipc.send_to(conn, CliResponseEvent(text=msg, success=success))

        elif isinstance(cmd, GetAddressCommand):
            _, msg = self._tm.get_address()
            self._ipc.send_to(conn, CliResponseEvent(text=msg))

        elif isinstance(cmd, GenerateAddressCommand):
            _, msg = self._tm.generate_address()
            self._ipc.send_to(conn, CliResponseEvent(text=msg))

        elif isinstance(cmd, AddContactCommand):
            if cmd.onion:
                _, msg = self._cm.add_contact(cmd.alias, cmd.onion)
            else:
                _, msg = self._cm.promote_discovered_peer(cmd.alias)
            self._ipc.send_to(conn, CliResponseEvent(text=msg, alias=cmd.alias))

        elif isinstance(cmd, RemoveContactCommand):
            active_onions = self._network.get_active_onions()
            success, msg, renames, removed = self._cm.remove_contact(
                cmd.alias, active_onions
            )
            if success:
                for old, new, was_saved in renames:
                    self._ipc.broadcast(
                        RenameSuccessEvent(
                            old_alias=old,
                            new_alias=new,
                            is_demotion=True,
                            was_saved=was_saved,
                        )
                    )
                for a in removed:
                    self._ipc.broadcast(ContactRemovedEvent(alias=a))
            self._ipc.send_to(
                conn, CliResponseEvent(text=msg, success=success, alias=cmd.alias)
            )

        elif isinstance(cmd, RenameContactCommand):
            success, msg = self._cm.rename_contact(cmd.old_alias, cmd.new_alias)
            if success:
                self._ipc.broadcast(
                    RenameSuccessEvent(old_alias=cmd.old_alias, new_alias=cmd.new_alias)
                )
            self._ipc.send_to(
                conn, CliResponseEvent(text=msg, success=success, alias=cmd.new_alias)
            )
