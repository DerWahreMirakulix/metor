"""
Module defining the primary background daemon engine.
Orchestrates Network, IPC API, and Outbox routing seamlessly.
"""

import socket
import threading
import time
import atexit
import sys
import os
import signal
from typing import Any, Optional

from metor.data.profile import ProfileManager
from metor.core.key import KeyManager
from metor.core.tor import TorManager
from metor.data.history import HistoryManager, HistoryEvent
from metor.data.contact import ContactManager
from metor.data.messages import (
    MessageManager,
    MessageDirection,
    MessageType,
    MessageStatus,
)

from metor.core.api import IpcCommand, IpcEvent, Action, EventType
from metor.ui.theme import Theme
from metor.utils.helper import clean_onion

from metor.core.daemon.crypto import Crypto
from metor.core.daemon.ipc import IpcServer
from metor.core.daemon.outbox import OutboxWorker
from metor.core.daemon.network import NetworkManager


class DaemonEngine:
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
        """
        self._pm: ProfileManager = pm
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm

        self._stop_flag: threading.Event = threading.Event()

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
        """
        self.stop()
        sys.exit(0)

    def run(self) -> None:
        """Starts the Engine infrastructure."""
        if not self._tm.start():
            print('Daemon: Failed to start Tor.')
            return

        self._network.start_listener()
        self._ipc.start()
        self._outbox.start()

        print(
            f'Daemon running... Onion: {Theme.YELLOW}{clean_onion(self._tm.onion or "")}{Theme.RESET}.onion '
            f'| IPC Port: {Theme.YELLOW}{self._ipc.port}{Theme.RESET}'
        )

        try:
            while not self._stop_flag.is_set():
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """Stops the engine and gracefully tears down all sub-services."""
        self._stop_flag.set()
        self._network.disconnect_all()
        self._ipc.stop()
        self._pm.clear_daemon_port()
        self._tm.stop()

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
        """
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

                if exists:
                    self._mm.queue_message(
                        onion,
                        MessageDirection.OUT,
                        MessageType.TEXT,
                        cmd.text,
                        MessageStatus.PENDING,
                    )
                    self._hm.log_event(
                        HistoryEvent.ASYNC_QUEUED, onion, 'Queued offline message'
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
                if exists:
                    success, msg = self._hm.clear_history(onion)
                else:
                    success, msg = False, 'Contact not found.'
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
                if exists:
                    success, msg = self._mm.clear_messages(onion)
                else:
                    success, msg = False, 'Contact not found.'
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
