"""
Module managing Tor network connections, socket lifecycles, and message routing.
Handles the transition between live TCP streams and fallback Drop & Go messages.
Ensures strict TCP stream framing and fragmentation resilience.
"""

import socket
import threading
import time
import base64
import secrets
from typing import Dict, List, Optional, Callable

from metor.core.tor import TorManager
from metor.core.api import IpcEvent, EventType
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

# Local Package Imports
from metor.core.daemon.models import TorCommand
from metor.core.daemon.crypto import Crypto


class NetworkManager:
    """Handles raw sockets, Tor connections, and safe message buffering."""

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        crypto: Crypto,
        broadcast_callback: Callable[[IpcEvent], None],
        stop_flag: threading.Event,
    ) -> None:
        """
        Initializes the NetworkManager.

        Args:
            tm (TorManager): Tor process manager.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Offline messages manager.
            crypto (Crypto): Cryptographic challenge/response engine.
            broadcast_callback (Callable): Callback to broadcast IPC events.
            stop_flag (threading.Event): Global daemon termination flag.

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._crypto: Crypto = crypto
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._stop_flag: threading.Event = stop_flag

        self._lock: threading.Lock = threading.Lock()
        self._connections: Dict[str, socket.socket] = {}
        self._pending_connections: Dict[str, socket.socket] = {}
        self._initial_buffers: Dict[str, str] = {}
        self._unacked_messages: Dict[str, Dict[str, str]] = {}

    def start_listener(self) -> None:
        """
        Starts the local Tor listener in a background thread.

        Args:
            None

        Returns:
            None
        """
        threading.Thread(target=self._listener_target, daemon=True).start()

    def get_active_aliases(self) -> List[str]:
        """
        Returns a list of currently connected aliases safely under lock.

        Args:
            None

        Returns:
            List[str]: Active connection aliases.
        """
        with self._lock:
            return list(self._connections.keys())

    def get_pending_aliases(self) -> List[str]:
        """
        Returns a list of aliases waiting for acceptance safely under lock.

        Args:
            None

        Returns:
            List[str]: Pending connection aliases.
        """
        with self._lock:
            return list(self._pending_connections.keys())

    def _listener_target(self) -> None:
        """
        Background loop accepting raw incoming Tor sockets.

        Args:
            None

        Returns:
            None
        """
        listener: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind((Constants.LOCALHOST, self._tm.incoming_port or 0))
        listener.listen(5)
        while not self._stop_flag.is_set():
            try:
                listener.settimeout(1.0)
                conn, _ = listener.accept()
                threading.Thread(
                    target=self._handle_incoming, args=(conn,), daemon=True
                ).start()
            except Exception:
                continue

    def _handle_incoming(self, conn: socket.socket) -> None:
        """
        Authenticates inbound requests and routes them to Live-Chat or Drop-Box.
        Safely reconstructs fragmented TCP streams and enforces async network policies.

        Args:
            conn (socket.socket): The incoming socket connection.

        Returns:
            None
        """
        auth_successful: bool = False
        remote_identity: Optional[str] = None
        is_async: bool = False
        buffer: str = ''

        try:
            conn.settimeout(10.0)
            challenge: str = secrets.token_hex(32)
            conn.sendall(f'{TorCommand.CHALLENGE.value} {challenge}\n'.encode('utf-8'))

            while '\n' not in buffer:
                data: bytes = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode('utf-8')

            if '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()
                if line.startswith(f'{TorCommand.AUTH.value} '):
                    parts: List[str] = line.split(' ')
                    if len(parts) >= 3 and self._crypto.verify_signature(
                        parts[1], challenge, parts[2]
                    ):
                        remote_identity = parts[1]
                        auth_successful = True
                        if len(parts) >= 4 and parts[3] == 'ASYNC':
                            is_async = True
        except Exception:
            pass

        if not auth_successful or not remote_identity:
            conn.close()
            return

        if is_async:
            if not Settings.get(SettingKey.ALLOW_ASYNC):
                conn.close()
                return

            try:
                while True:
                    while '\n' in buffer:
                        msg, buffer = buffer.split('\n', 1)
                        msg = msg.strip()
                        if not msg:
                            continue
                        if msg.startswith(f'{TorCommand.DROP.value} '):
                            parts = msg.split(' ', 2)
                            if len(parts) == 3:
                                msg_id, content = (
                                    parts[1],
                                    base64.b64decode(parts[2]).decode('utf-8'),
                                )
                                self._mm.queue_message(
                                    remote_identity,
                                    MessageDirection.IN,
                                    MessageType.TEXT,
                                    content,
                                    MessageStatus.UNREAD,
                                )
                                self._hm.log_event(
                                    HistoryEvent.ASYNC_RECEIVED,
                                    remote_identity,
                                    'Received offline message',
                                )
                                conn.sendall(
                                    f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8')
                                )
                                alias: Optional[str] = self._cm.get_alias_by_onion(
                                    remote_identity
                                )
                                self._broadcast(
                                    IpcEvent(
                                        type=EventType.INBOX_NOTIFICATION,
                                        alias=alias,
                                        # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                                        text="📬 1 new offline message from '{alias}'.",
                                    )
                                )
                    data = conn.recv(4096)
                    if not data:
                        break
                    buffer += data.decode('utf-8')
            except Exception:
                pass
            finally:
                conn.close()
            return

        conn.settimeout(None)
        alias = self._cm.get_alias_by_onion(remote_identity)
        if not alias:
            conn.close()
            return

        with self._lock:
            if alias in self._connections or alias in self._pending_connections:
                try:
                    conn.sendall(
                        f'{TorCommand.REJECT.value} {self._tm.onion}\n'.encode('utf-8')
                    )
                except Exception:
                    pass
                conn.close()
                return

            if (alias in self._cm.get_all_contacts()) and Settings.get(
                SettingKey.AUTO_ACCEPT_CONTACTS
            ):
                self._connections[alias] = conn
                try:
                    conn.sendall(f'{TorCommand.ACCEPTED.value}\n'.encode('utf-8'))
                except Exception:
                    pass
                self._hm.log_event(HistoryEvent.CONNECTED, remote_identity)
                self._broadcast(
                    IpcEvent(
                        type=EventType.CONNECTED, alias=alias, onion=remote_identity
                    )
                )
                self._start_receiving(alias, conn, buffer)
                return

            self._pending_connections[alias] = conn
            self._initial_buffers[alias] = buffer

        self._hm.log_event(HistoryEvent.REQUESTED_BY_REMOTE, remote_identity)
        self._broadcast(
            IpcEvent(
                type=EventType.INFO,
                alias=alias,
                # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                text=f"Incoming connection from '{{alias}}'. Type '{Theme.GREEN}/accept {{alias}}{Theme.RESET}' or '{Theme.RED}/reject {{alias}}{Theme.RESET}'.",
            )
        )

    def connect_to(self, target: str) -> None:
        """
        Initiates an outbound Tor connection and parses the handshake response safely.

        Args:
            target (str): The alias or onion address to connect to.

        Returns:
            None
        """
        alias, onion, exists = self._cm.resolve_target(target)
        # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
        if not exists or onion == self._tm.onion:
            return

        with self._lock:
            if alias in self._connections:
                return

        try:
            conn: socket.socket = self._tm.connect(onion)
            conn.settimeout(10.0)

            buffer: str = ''
            while '\n' not in buffer:
                chunk: bytes = conn.recv(4096)
                if not chunk:
                    break
                buffer += chunk.decode('utf-8')

            if '\n' in buffer:
                challenge_line, buffer = buffer.split('\n', 1)
                challenge: str = challenge_line.strip().split(' ')[1]
                signature: Optional[str] = self._crypto.sign_challenge(challenge)
                conn.sendall(
                    f'{TorCommand.AUTH.value} {self._tm.onion} {signature}\n'.encode(
                        'utf-8'
                    )
                )
                conn.settimeout(None)

                self._hm.log_event(HistoryEvent.REQUESTED, onion)
                self._broadcast(
                    IpcEvent(
                        type=EventType.INFO,
                        alias=alias,
                        # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                        text="Request sent to '{alias}'. Waiting for acceptance...",
                    )
                )
                self._start_receiving(alias or onion, conn, buffer)
            else:
                raise ConnectionError('Handshake incomplete.')
        except Exception:
            self._broadcast(
                IpcEvent(
                    type=EventType.INFO,
                    alias=alias,
                    # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                    text="Failed to connect to '{alias}'.",
                )
            )

    def accept(self, alias: str) -> None:
        """
        Approves a pending incoming connection and processes any leftover stream buffer.

        Args:
            alias (str): The alias to accept.

        Returns:
            None
        """
        with self._lock:
            if alias not in self._pending_connections:
                return
            conn: socket.socket = self._pending_connections.pop(alias)
            initial_buffer: str = self._initial_buffers.pop(alias, '')
            self._connections[alias] = conn

        try:
            conn.sendall(f'{TorCommand.ACCEPTED.value}\n'.encode('utf-8'))
        except Exception:
            pass
        onion: Optional[str] = self._cm.get_onion_by_alias(alias)
        self._hm.log_event(HistoryEvent.CONNECTED, onion)
        self._broadcast(IpcEvent(type=EventType.CONNECTED, alias=alias, onion=onion))
        self._start_receiving(alias, conn, initial_buffer)

    def reject(self, alias: str, initiated_by_self: bool = True) -> None:
        """
        Rejects a pending connection request and cleans up isolated resources.

        Args:
            alias (str): The alias to reject.
            initiated_by_self (bool): Whether the local user initiated the rejection.

        Returns:
            None
        """
        with self._lock:
            conn = self._connections.pop(alias, None) or self._pending_connections.pop(
                alias, None
            )
            self._initial_buffers.pop(alias, None)

        if conn:
            if initiated_by_self:
                try:
                    conn.sendall(
                        f'{TorCommand.REJECT.value} {self._tm.onion}\n'.encode('utf-8')
                    )
                except Exception:
                    pass
            conn.close()

        status: HistoryEvent = (
            HistoryEvent.REJECTED
            if initiated_by_self
            else HistoryEvent.REJECTED_BY_REMOTE
        )
        self._hm.log_event(status, self._cm.get_onion_by_alias(alias))
        self._broadcast(
            IpcEvent(
                type=EventType.INFO,
                alias=alias,
                # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                text="Connection with '{alias}' rejected.",
            )
        )

    def disconnect(
        self, alias: str, initiated_by_self: bool = True, is_fallback: bool = False
    ) -> None:
        """
        Terminates a connection and converts un-ACKed messages to offline drops.

        Args:
            alias (str): The alias to disconnect.
            initiated_by_self (bool): Whether the local user initiated the disconnect.
            is_fallback (bool): Whether this is an unexpected network drop.

        Returns:
            None
        """
        with self._lock:
            conn = self._connections.pop(alias, None) or self._pending_connections.pop(
                alias, None
            )
            self._initial_buffers.pop(alias, None)
            unacked: Dict[str, str] = self._unacked_messages.pop(alias, {})

        if unacked:
            onion: Optional[str] = self._cm.get_onion_by_alias(alias)
            if onion:
                for content in unacked.values():
                    self._mm.queue_message(
                        onion,
                        MessageDirection.OUT,
                        MessageType.TEXT,
                        content,
                        MessageStatus.PENDING,
                    )
                self._hm.log_event(
                    HistoryEvent.ASYNC_QUEUED, onion, 'Unacked msgs converted to drop'
                )
            self._broadcast(
                IpcEvent(
                    type=EventType.MSG_FALLBACK_TO_DROP, msg_ids=list(unacked.keys())
                )
            )

        if conn:
            if initiated_by_self:
                try:
                    conn.sendall(
                        f'{TorCommand.DISCONNECT.value} {self._tm.onion}\n'.encode(
                            'utf-8'
                        )
                    )
                    time.sleep(0.2)
                    conn.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
            try:
                conn.close()
            except Exception:
                pass

        status: HistoryEvent = (
            HistoryEvent.CONNECTION_LOST
            if is_fallback
            else (
                HistoryEvent.DISCONNECTED
                if initiated_by_self
                else HistoryEvent.DISCONNECTED_BY_REMOTE
            )
        )
        self._hm.log_event(status, self._cm.get_onion_by_alias(alias))
        self._broadcast(
            IpcEvent(
                type=EventType.DISCONNECTED,
                alias=alias,
                text="Disconnected from '{alias}'.",
            )
        )

    def disconnect_all(self) -> None:
        """
        Forcefully disconnects all active and pending peers safely upon daemon shutdown.

        Args:
            None

        Returns:
            None
        """
        with self._lock:
            active_aliases: List[str] = list(self._connections.keys())
            pending_aliases: List[str] = list(self._pending_connections.keys())

        aliases_to_disconnect: List[str] = active_aliases + pending_aliases

        for alias in aliases_to_disconnect:
            self.disconnect(alias, initiated_by_self=True)

    def send_message(self, alias: str, msg: str, msg_id: str) -> None:
        """
        Sends a live chat message and buffers it for ACK verification.

        Args:
            alias (str): The target alias.
            msg (str): The message content.
            msg_id (str): The unique message identifier.

        Returns:
            None
        """
        with self._lock:
            if alias not in self._connections:
                return
            conn: socket.socket = self._connections[alias]
            self._unacked_messages.setdefault(alias, {})[msg_id] = msg

        try:
            b64_msg: str = base64.b64encode(msg.encode('utf-8')).decode('utf-8')
            conn.sendall(f'{TorCommand.MSG.value} {msg_id} {b64_msg}\n'.encode('utf-8'))
        except Exception:
            pass

    def _start_receiving(
        self, alias: str, conn: socket.socket, initial_buffer: str = ''
    ) -> None:
        """
        Starts a background thread to listen for data on a specific live socket.

        Args:
            alias (str): The connected alias.
            conn (socket.socket): The active socket connection.
            initial_buffer (str): Leftover TCP stream buffer from the handshake.

        Returns:
            None
        """
        threading.Thread(
            target=self._receiver_target,
            args=(alias, conn, initial_buffer),
            daemon=True,
        ).start()

    def _receiver_target(
        self, current_alias: str, conn: socket.socket, initial_buffer: str = ''
    ) -> None:
        """
        Target processing incoming live messages, ACKs, and disconnects.
        Uses rigorous TCP line buffering to eliminate data corruption.

        Args:
            current_alias (str): The alias associated with the connection.
            conn (socket.socket): The active socket connection.
            initial_buffer (str): Leftover TCP stream buffer from the handshake.

        Returns:
            None
        """
        remote_rejected: bool = False
        remote_disconnected: bool = False
        buffer: str = initial_buffer

        try:
            while True:
                while '\n' in buffer:
                    msg, buffer = buffer.split('\n', 1)
                    msg = msg.strip()
                    if not msg:
                        continue

                    if msg == TorCommand.ACCEPTED.value:
                        with self._lock:
                            if current_alias in self._pending_connections:
                                self._pending_connections.pop(current_alias)
                            self._connections[current_alias] = conn
                        onion: Optional[str] = self._cm.get_onion_by_alias(
                            current_alias
                        )
                        self._hm.log_event(HistoryEvent.CONNECTED, onion)
                        self._broadcast(
                            IpcEvent(
                                type=EventType.CONNECTED,
                                alias=current_alias,
                                onion=onion,
                            )
                        )

                    elif msg.startswith(f'{TorCommand.DISCONNECT.value} '):
                        remote_disconnected = True
                        break
                    elif msg.startswith(f'{TorCommand.REJECT.value} '):
                        remote_rejected = True
                        break

                    elif msg.startswith(f'{TorCommand.ACK.value} '):
                        msg_id: str = msg.split(' ')[1]
                        with self._lock:
                            if current_alias in self._unacked_messages:
                                self._unacked_messages[current_alias].pop(msg_id, None)
                        self._broadcast(IpcEvent(type=EventType.ACK, msg_id=msg_id))

                    elif msg.startswith(f'{TorCommand.MSG.value} '):
                        parts: List[str] = msg.split(' ', 2)
                        if len(parts) == 3:
                            try:
                                conn.sendall(
                                    f'{TorCommand.ACK.value} {parts[1]}\n'.encode(
                                        'utf-8'
                                    )
                                )
                                content: str = base64.b64decode(parts[2]).decode(
                                    'utf-8'
                                )
                                self._broadcast(
                                    IpcEvent(
                                        type=EventType.REMOTE_MSG,
                                        alias=current_alias,
                                        text=content,
                                    )
                                )
                            except Exception:
                                pass

                if remote_disconnected or remote_rejected:
                    break

                data: bytes = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode('utf-8')

        except Exception:
            pass
        finally:
            if remote_rejected:
                self.reject(current_alias, initiated_by_self=False)
            elif remote_disconnected:
                self.disconnect(current_alias, initiated_by_self=False)
            else:
                self.disconnect(
                    current_alias, initiated_by_self=False, is_fallback=True
                )
