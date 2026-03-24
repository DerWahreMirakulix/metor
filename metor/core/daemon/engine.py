"""
Module defining the primary background daemon engine.
Orchestrates Network, IPC API, and Outbox routing seamlessly.
Handles Unlock operations and Nuke/Purge protocols.
"""

import socket
import threading
import time
import atexit
import sys
import os
import signal
from typing import Any, Optional

from metor.core.key import KeyManager
from metor.core.tor import TorManager
from metor.core.api import IpcCommand, IpcEvent, Action, EventType
from metor.data.profile import ProfileManager
from metor.data.history import HistoryManager, HistoryEvent
from metor.data.contact import ContactManager
from metor.data.message import (
    MessageManager,
    MessageDirection,
    MessageType,
    MessageStatus,
)
from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.utils.helper import clean_onion

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

        self._crypto: Crypto = Crypto(km)
        self._ipc: IpcServer = IpcServer(pm, self._process_ui_command)
        self._outbox: OutboxWorker = OutboxWorker(
            tm, mm, hm, self._crypto, self._stop_flag
        )
        self._network: NetworkManager = NetworkManager(
            tm, cm, hm, mm, self._crypto, self._ipc.broadcast, self._stop_flag
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
        if getattr(self._km, '_password', None) is None and self._pm.is_remote():
            self._is_locked = True
            self._ipc.start()
            print('Daemon running in LOCKED mode... Waiting for IPC unlock.')
        else:
            self._start_subsystems()

        try:
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
        if not self._tm.start():
            print('Daemon: Failed to start Tor.')
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
        self._ipc.stop()
        self._pm.clear_daemon_port()
        self._tm.stop()

    def _nuke_data(self) -> None:
        """
        Securely erases local SQLite DB and Tor keys, and initiates shutdown.
        Warning: Data shredding may be ineffective on modern SSDs due to wear-leveling.

        Args:
            None

        Returns:
            None
        """
        import stat
        import secrets
        from pathlib import Path

        db_path: Path = Path(self._pm.get_config_dir()) / Constants.DB_FILE
        if db_path.exists():
            with db_path.open('ba+') as f:
                length: int = f.tell()
                f.seek(0)
                f.write(secrets.token_bytes(length))
            db_path.unlink()

        hs_dir: Path = Path(self._pm.get_hidden_service_dir())
        for key_file in [
            Constants.METOR_SECRET_KEY,
            Constants.TOR_SECRET_KEY,
            Constants.TOR_PUBLIC_KEY,
        ]:
            key_path: Path = hs_dir / key_file
            if key_path.exists():
                key_path.chmod(stat.S_IWRITE)
                with key_path.open('ba+') as f:
                    length = f.tell()
                    f.seek(0)
                    f.write(secrets.token_bytes(length))
                key_path.unlink()

        self._ipc.broadcast(
            IpcEvent(
                type=EventType.SYSTEM,
                text='Daemon self-destruction initiated. Shutting down immediately...',
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

    def _process_ui_command(self, cmd: IpcCommand, conn: socket.socket) -> None:
        """
        Routes IPC commands from the Chat UI or CLI Proxy to the internal managers.

        Args:
            cmd (IpcCommand): The parsed command object.
            conn (socket.socket): The connection to respond to.

        Returns:
            None
        """
        if cmd.action == Action.SELF_DESTRUCT:
            self._ipc.send_to(
                conn,
                IpcEvent(
                    type=EventType.CLI_RESPONSE,
                    text='Self-destruct command accepted. Nuking daemon...',
                ),
            )
            threading.Thread(target=self._nuke_data, daemon=True).start()
            return

        if cmd.action == Action.UNLOCK:
            if not self._is_locked:
                self._ipc.send_to(
                    conn,
                    IpcEvent(
                        type=EventType.CLI_RESPONSE, text='Daemon is already unlocked.'
                    ),
                )
                return

            self._km = KeyManager(self._pm, cmd.password)
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
                self._stop_flag,
            )
            self._outbox = OutboxWorker(
                self._tm, self._mm, self._hm, self._crypto, self._stop_flag
            )

            self._is_locked = False
            self._start_subsystems()
            self._ipc.send_to(
                conn,
                IpcEvent(
                    type=EventType.CLI_RESPONSE,
                    text='Daemon unlocked successfully.',
                ),
            )
            return

        if cmd.action == Action.SET_SETTING:
            if cmd.setting_key and cmd.setting_value:
                try:
                    from metor.data.settings import Settings, SettingKey

                    Settings.set(SettingKey(cmd.setting_key), cmd.setting_value)
                    self._ipc.send_to(
                        conn,
                        IpcEvent(
                            type=EventType.CLI_RESPONSE,
                            text='Daemon setting updated.',
                        ),
                    )
                except Exception:
                    self._ipc.send_to(
                        conn,
                        IpcEvent(
                            type=EventType.CLI_RESPONSE,
                            text='Failed to update setting.',
                        ),
                    )
            return

        if self._is_locked:
            self._ipc.send_to(
                conn,
                IpcEvent(
                    type=EventType.CLI_RESPONSE,
                    text='Daemon is locked. Please unlock first.',
                ),
            )
            return

        if cmd.action == Action.INIT:
            self._ipc.send_to(conn, IpcEvent(type=EventType.INIT, onion=self._tm.onion))

        elif cmd.action == Action.GET_CONNECTIONS:
            self._ipc.send_to(
                conn,
                IpcEvent(
                    type=EventType.CONNECTIONS_STATE,
                    active=self._network.get_active_aliases(),
                    pending=self._network.get_pending_aliases(),
                    contacts=self._cm.get_all_contacts(),
                    is_header=cmd.is_header,
                ),
            )

        elif cmd.action == Action.GET_CONTACTS_LIST:
            self._ipc.send_to(
                conn,
                IpcEvent(
                    type=EventType.CONTACT_LIST, text=self._cm.show(cmd.chat_mode)
                ),
            )

        elif cmd.action == Action.CONNECT:
            if cmd.target:
                if self._is_self_target(cmd.target):
                    self._ipc.send_to(
                        conn,
                        IpcEvent(
                            type=EventType.SYSTEM,
                            text='You cannot connect to yourself.',
                        ),
                    )
                    return

                alias, _, exists = self._cm.resolve_target(cmd.target)

                # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
                if not exists:
                    self._ipc.send_to(
                        conn,
                        IpcEvent(
                            type=EventType.SYSTEM,
                            text=f"Invalid target: '{cmd.target}' is neither a known contact nor a valid onion address.",
                        ),
                    )
                    return

                self._ipc.broadcast(
                    IpcEvent(
                        type=EventType.INFO,
                        alias=alias,
                        # We intentionally don't resolve alias since it is dynamically inserted in the UI to keep it dynamic
                        text="Connecting to '{alias}'...",
                    )
                )
                threading.Thread(
                    target=self._network.connect_to, args=(cmd.target,), daemon=True
                ).start()

        elif cmd.action == Action.DISCONNECT:
            if cmd.target:
                self._network.disconnect(cmd.target, initiated_by_self=True)

        elif cmd.action == Action.ACCEPT:
            if cmd.target:
                self._network.accept(cmd.target)

        elif cmd.action == Action.REJECT:
            if cmd.target:
                self._network.reject(cmd.target, initiated_by_self=True)

        elif cmd.action == Action.MSG:
            if cmd.target and cmd.text and cmd.msg_id:
                self._network.send_message(cmd.target, cmd.text, cmd.msg_id)

        elif cmd.action == Action.SEND_DROP:
            if cmd.target and cmd.text:
                if self._is_self_target(cmd.target):
                    self._ipc.send_to(
                        conn,
                        IpcEvent(
                            type=EventType.SYSTEM,
                            text='You cannot send offline drops to yourself.',
                        ),
                    )
                    return

                _, onion, exists = self._cm.resolve_target(cmd.target)

                # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
                if exists:
                    self._mm.queue_message(
                        onion,
                        MessageDirection.OUT,
                        MessageType.TEXT,
                        cmd.text,
                        MessageStatus.PENDING,
                    )
                    self._hm.log_event(
                        HistoryEvent.ASYNC_QUEUED,
                        onion,
                        'Queued offline message',
                    )

        elif cmd.action == Action.GET_INBOX:
            self._ipc.send_to(
                conn,
                IpcEvent(
                    type=EventType.INBOX_DATA, inbox_counts=self._mm.get_unread_counts()
                ),
            )

        elif cmd.action == Action.MARK_READ:
            if cmd.target:
                alias, onion, exists = self._cm.resolve_target(cmd.target)
                # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
                if exists:
                    raw_messages = self._mm.get_and_read_inbox(onion)
                    messages = [
                        {'id': r[0], 'type': r[1], 'payload': r[2], 'timestamp': r[3]}
                        for r in raw_messages
                    ]
                    self._ipc.send_to(
                        conn,
                        IpcEvent(
                            type=EventType.INBOX_DATA, alias=alias, messages=messages
                        ),
                    )

        elif cmd.action == Action.SWITCH:
            if cmd.target is None or cmd.target == '..':
                self._ipc.send_to(
                    conn, IpcEvent(type=EventType.SWITCH_SUCCESS, alias=None)
                )
            else:
                if self._is_self_target(cmd.target):
                    self._ipc.send_to(
                        conn,
                        IpcEvent(
                            type=EventType.SYSTEM,
                            text='You cannot switch focus to yourself.',
                        ),
                    )
                    return

                alias, _, exists = self._cm.resolve_target(cmd.target)

                # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
                if not exists:
                    self._ipc.send_to(
                        conn,
                        IpcEvent(
                            type=EventType.SYSTEM,
                            text=f"Invalid target: '{cmd.target}' not found.",
                        ),
                    )
                    return

                self._ipc.send_to(
                    conn, IpcEvent(type=EventType.SWITCH_SUCCESS, alias=alias)
                )

        elif cmd.action == Action.GET_HISTORY:
            text: str = self._hm.show(self._cm, cmd.target)
            self._ipc.send_to(conn, IpcEvent(type=EventType.CLI_RESPONSE, text=text))

        elif cmd.action == Action.CLEAR_HISTORY:
            if cmd.target:
                _, onion, exists = self._cm.resolve_target(cmd.target)
                # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
                if exists:
                    success, msg = self._hm.clear_history(onion)
                else:
                    success, msg = (
                        False,
                        'Contact not found.',
                    )
            else:
                success, msg = self._hm.clear_history()
            self._ipc.send_to(
                conn, IpcEvent(type=EventType.CLI_RESPONSE, text=msg, success=success)
            )

        elif cmd.action == Action.GET_MESSAGES:
            if cmd.target:
                text = self._mm.show_history(cmd.target, self._cm, cmd.limit)
            else:
                text = 'No target specified.'
            self._ipc.send_to(conn, IpcEvent(type=EventType.CLI_RESPONSE, text=text))

        elif cmd.action == Action.CLEAR_MESSAGES:
            if cmd.target:
                _, onion, exists = self._cm.resolve_target(cmd.target)
                # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
                if exists:
                    success, msg = self._mm.clear_messages(onion)
                else:
                    success, msg = (
                        False,
                        'Contact not found.',
                    )
            else:
                success, msg = self._mm.clear_messages()
            self._ipc.send_to(
                conn, IpcEvent(type=EventType.CLI_RESPONSE, text=msg, success=success)
            )

        elif cmd.action == Action.CLEAR_CONTACTS:
            success, msg = self._cm.clear_contacts()
            self._ipc.send_to(
                conn, IpcEvent(type=EventType.CLI_RESPONSE, text=msg, success=success)
            )

        elif cmd.action == Action.GET_ADDRESS:
            _, msg = self._tm.get_address()
            self._ipc.send_to(conn, IpcEvent(type=EventType.CLI_RESPONSE, text=msg))

        elif cmd.action == Action.GENERATE_ADDRESS:
            _, msg = self._tm.generate_address()
            self._ipc.send_to(conn, IpcEvent(type=EventType.CLI_RESPONSE, text=msg))
