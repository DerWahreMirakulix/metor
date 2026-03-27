"""
Module managing Tor network connections, socket lifecycles, and message routing.
Handles the transition between live TCP streams and fallback Drop & Go messages.
Enforces strict TCP stream framing and fragmentation resilience.
"""

import socket
import threading
import time
import base64
import secrets
from typing import Dict, List, Optional, Callable, Tuple, Any, Set

from metor.core.tor import TorManager
from metor.core.api import (
    IpcEvent,
    SystemEvent,
    ConnectedEvent,
    InfoEvent,
    DisconnectedEvent,
    InboxNotificationEvent,
    InboxDataEvent,
    MsgFallbackToDropEvent,
    AckEvent,
    RemoteMsgEvent,
    ContactRemovedEvent,
)
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
        has_clients_callback: Callable[[], bool],
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
            has_clients_callback (Callable): Callback to check for active UI clients.
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
        self._has_clients_callback: Callable[[], bool] = has_clients_callback
        self._stop_flag: threading.Event = stop_flag

        self._lock: threading.Lock = threading.Lock()
        # All routing dictionaries strictly map ONION -> SOCKET / BUFFER
        # This prevents any desync bugs if the user renames an active alias in the UI.
        self._connections: Dict[str, socket.socket] = {}
        self._pending_connections: Dict[str, socket.socket] = {}
        self._outbound_attempts: Set[str] = set()
        self._initial_buffers: Dict[str, str] = {}
        self._unacked_messages: Dict[str, Dict[str, str]] = {}
        self._ram_buffers: Dict[str, List[Tuple[str, str]]] = {}

    def start_listener(self) -> None:
        """
        Starts the local Tor listener in a background thread.

        Args:
            None

        Returns:
            None
        """
        threading.Thread(target=self._listener_target, daemon=True).start()

    def get_active_onions(self) -> List[str]:
        """
        Returns a list of all currently connected and pending onions.

        Args:
            None

        Returns:
            List[str]: Active Tor connection onions to preserve.
        """
        with self._lock:
            return list(self._connections.keys()) + list(
                self._pending_connections.keys()
            )

    def get_active_aliases(self) -> List[str]:
        """
        Returns a list of currently connected aliases safely under lock.
        Dynamically resolves the current alias from the active onions.

        Args:
            None

        Returns:
            List[str]: Active connection aliases.
        """
        with self._lock:
            return [
                self._cm.get_alias_by_onion(onion) for onion in self._connections.keys()
            ]

    def get_pending_aliases(self) -> List[str]:
        """
        Returns a list of aliases waiting for acceptance safely under lock.
        Dynamically resolves the current alias from the pending onions.

        Args:
            None

        Returns:
            List[str]: Pending connection aliases.
        """
        with self._lock:
            return [
                self._cm.get_alias_by_onion(onion)
                for onion in self._pending_connections.keys()
            ]

    def flush_ram_buffer(self, onion: str) -> None:
        """
        Flushes the headless RAM buffer to the UI and fires pending Tor ACKs.

        Args:
            onion (str): The target onion to flush.

        Returns:
            None
        """
        with self._lock:
            if onion not in self._connections:
                return
            buffered_msgs: List[Tuple[str, str]] = self._ram_buffers.pop(onion, [])
            conn: socket.socket = self._connections[onion]

        if not buffered_msgs:
            return

        alias: Optional[str] = self._cm.get_alias_by_onion(onion)
        messages_data: List[Dict[str, Any]] = [
            {'id': msg_id, 'payload': content, 'type': 'text', 'timestamp': ''}
            for msg_id, content in buffered_msgs
        ]

        self._broadcast(
            InboxDataEvent(alias=alias, messages=messages_data, is_live_flush=True)
        )

        for msg_id, _ in buffered_msgs:
            try:
                conn.sendall(f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8'))
            except Exception:
                pass

    def force_fallback(self, target: str) -> Tuple[bool, str]:
        """
        Forces all unacknowledged outgoing live messages to the drop queue.

        Args:
            target (str): The target alias or onion address.

        Returns:
            Tuple[bool, str]: A success flag and context-specific status message.
        """
        alias, onion, exists = self._cm.resolve_target(target)
        if not exists:
            return False, f"Peer '{target}' not found."

        with self._lock:
            unacked: Dict[str, str] = self._unacked_messages.pop(onion, {})

        if not unacked:
            # We intentionally don't resolve the alias since it is dynamically inserted in the UI
            return False, "No pending live messages found for '{alias}'."

        for _, content in unacked.items():
            self._mm.queue_message(
                onion,
                MessageDirection.OUT,
                MessageType.TEXT,
                content,
                MessageStatus.PENDING,
            )
            self._hm.log_event(
                HistoryEvent.ASYNC_QUEUED, onion, 'Manual fallback to drop'
            )

        self._broadcast(MsgFallbackToDropEvent(msg_ids=list(unacked.keys())))

        # We intentionally don't resolve the alias since it is dynamically inserted in the UI
        return (
            True,
            f"Successfully converted {len(unacked)} unacked message(s) to '{{alias}}' into drops.",
        )

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
        onion: Optional[str] = None
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
                        onion = parts[1]
                        auth_successful = True
                        if len(parts) >= 4 and parts[3] == 'ASYNC':
                            is_async = True
        except Exception:
            pass

        if not auth_successful or not onion:
            conn.close()
            return

        if not is_async:
            with self._lock:
                if onion in self._outbound_attempts:
                    if self._tm.onion and self._tm.onion < onion:
                        try:
                            conn.sendall(
                                f'{TorCommand.REJECT.value} {self._tm.onion}\n'.encode(
                                    'utf-8'
                                )
                            )
                        except Exception:
                            pass
                        conn.close()
                        return

        if is_async:
            if not Settings.get(SettingKey.ALLOW_DROPS):
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

                                is_ephemeral: bool = Settings.get(
                                    SettingKey.EPHEMERAL_MESSAGES
                                )
                                status: MessageStatus = (
                                    MessageStatus.READ
                                    if is_ephemeral
                                    else MessageStatus.UNREAD
                                )

                                self._mm.queue_message(
                                    onion,
                                    MessageDirection.IN,
                                    MessageType.TEXT,
                                    content,
                                    status,
                                )

                                self._hm.log_event(
                                    HistoryEvent.ASYNC_RECEIVED,
                                    onion,
                                )

                                conn.sendall(
                                    f'{TorCommand.ACK.value} {msg_id}\n'.encode('utf-8')
                                )

                                alias: Optional[str] = self._cm.get_alias_by_onion(
                                    onion
                                )
                                self._broadcast(
                                    InboxNotificationEvent(
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
        alias = self._cm.get_alias_by_onion(onion)
        if not alias:
            conn.close()
            return

        with self._lock:
            if onion in self._connections or onion in self._pending_connections:
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
                self._connections[onion] = conn
                try:
                    conn.sendall(f'{TorCommand.ACCEPTED.value}\n'.encode('utf-8'))
                except Exception:
                    pass

                self._hm.log_event(HistoryEvent.CONNECTED, onion)
                self._broadcast(ConnectedEvent(alias=alias, onion=onion))
                self._start_receiving(onion, conn, buffer)
                return

            self._pending_connections[onion] = conn
            self._initial_buffers[onion] = buffer

        self._hm.log_event(HistoryEvent.REQUESTED_BY_REMOTE, onion)

        self._broadcast(
            InfoEvent(
                alias=alias,
                # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                text=f"Incoming connection from '{{alias}}'. Type '{Theme.GREEN}/accept {{alias}}{Theme.RESET}' or '{Theme.RED}/reject {{alias}}{Theme.RESET}'.",
            )
        )

    def connect_to(self, target: str) -> None:
        """
        Initiates an outbound Tor connection and parses the handshake response safely.
        Implements rigorous retry mechanisms to handle network instability.

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
            if onion in self._connections:
                return
            self._outbound_attempts.add(onion)

        try:
            max_retries: int = Settings.get(SettingKey.MAX_CONNECT_RETRIES)
            for attempt in range(1, max_retries + 1):
                if self._stop_flag.is_set():
                    break
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
                        signature: Optional[str] = self._crypto.sign_challenge(
                            challenge
                        )
                        conn.sendall(
                            f'{TorCommand.AUTH.value} {self._tm.onion} {signature}\n'.encode(
                                'utf-8'
                            )
                        )
                        conn.settimeout(None)

                        self._hm.log_event(HistoryEvent.REQUESTED, onion)

                        self._broadcast(
                            InfoEvent(
                                alias=alias,
                                # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                                text="Request sent to '{alias}'. Waiting for acceptance...",
                            )
                        )
                        self._start_receiving(onion, conn, buffer)
                        return
                    else:
                        raise ConnectionError('Handshake incomplete.')
                except Exception:
                    if attempt < max_retries:
                        self._broadcast(
                            InfoEvent(
                                alias=alias,
                                # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                                text=f"Connecting to '{{alias}}' failed. Retrying ({attempt}/{max_retries})...",
                            )
                        )
                        for _ in range(3):
                            if self._stop_flag.is_set():
                                break
                            time.sleep(1.0)
                    else:
                        self._hm.log_event(
                            HistoryEvent.ASYNC_FAILED,
                            onion,
                            'Connection timeout/exhausted',
                        )
                        self._broadcast(
                            InfoEvent(
                                alias=alias,
                                # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                                text="Failed to connect to '{alias}'.",
                            )
                        )
        finally:
            with self._lock:
                self._outbound_attempts.discard(onion)

    def accept(self, target: str) -> None:
        """
        Approves a pending incoming connection and processes any leftover stream buffer.

        Args:
            target (str): The target alias or onion.

        Returns:
            None
        """
        alias, onion, exists = self._cm.resolve_target(target)
        # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
        if not exists:
            self._broadcast(SystemEvent(text=f"Cannot accept: '{target}' not found."))
            return

        with self._lock:
            if onion not in self._pending_connections:
                self._broadcast(
                    SystemEvent(text=f"No pending connection from '{alias}' to accept.")
                )
                return
            conn: socket.socket = self._pending_connections.pop(onion)
            initial_buffer: str = self._initial_buffers.pop(onion, '')
            self._connections[onion] = conn

        try:
            conn.sendall(f'{TorCommand.ACCEPTED.value}\n'.encode('utf-8'))
        except Exception:
            pass

        self._hm.log_event(HistoryEvent.CONNECTED, onion)

        self._broadcast(ConnectedEvent(alias=alias, onion=onion))
        self._start_receiving(onion, conn, initial_buffer)

    def reject(self, target: str, initiated_by_self: bool = True) -> None:
        """
        Rejects a pending connection request and cleans up isolated resources.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the rejection.

        Returns:
            None
        """
        alias, onion, exists = self._cm.resolve_target(target)
        # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
        if not exists:
            if initiated_by_self:
                self._broadcast(
                    SystemEvent(text=f"Cannot reject: '{target}' not found.")
                )
            return

        with self._lock:
            conn = self._connections.pop(onion, None) or self._pending_connections.pop(
                onion, None
            )
            self._initial_buffers.pop(onion, None)

        if not conn:
            if initiated_by_self:
                self._broadcast(
                    SystemEvent(text=f"No connection with '{alias}' to reject.")
                )
            return

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
        self._hm.log_event(status, onion)

        self._broadcast(
            InfoEvent(
                alias=alias,
                # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                text="Connection with '{alias}' rejected.",
            )
        )

    def disconnect(
        self, target: str, initiated_by_self: bool = True, is_fallback: bool = False
    ) -> None:
        """
        Terminates a connection and converts un-ACKed messages to offline drops.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the disconnect.
            is_fallback (bool): Whether this is an unexpected network drop.

        Returns:
            None
        """
        alias, onion, exists = self._cm.resolve_target(target)
        # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
        if not exists:
            if initiated_by_self:
                self._broadcast(
                    SystemEvent(text=f"Cannot disconnect: '{target}' not found.")
                )
            return

        with self._lock:
            conn = self._connections.pop(onion, None) or self._pending_connections.pop(
                onion, None
            )
            self._initial_buffers.pop(onion, None)
            self._ram_buffers.pop(onion, None)

            unacked: Dict[str, str] = {}
            if Settings.get(SettingKey.FALLBACK_TO_DROP):
                unacked = self._unacked_messages.pop(onion, {})

        # GUARD: Prevent double-logging if the connection was already terminated
        if not conn and not unacked:
            if initiated_by_self:
                self._broadcast(
                    SystemEvent(
                        # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                        text="No active connection with '{alias}' to disconnect."
                    )
                )
            return

        if unacked:
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
            self._broadcast(MsgFallbackToDropEvent(msg_ids=list(unacked.keys())))

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
        self._hm.log_event(status, onion)

        self._broadcast(
            DisconnectedEvent(
                alias=alias,
                # We intentionally don't resolve the alias since it is dynamically inserted in the UI
                text="Disconnected from '{alias}'.",
            )
        )

        # Cleanup orphans, keeping current active connections alive
        deleted_aliases = self._cm.cleanup_orphans(self.get_active_onions())
        for a in deleted_aliases:
            self._broadcast(ContactRemovedEvent(alias=a))

    def disconnect_all(self) -> None:
        """
        Forcefully disconnects all active and pending peers safely upon daemon shutdown.

        Args:
            None

        Returns:
            None
        """
        with self._lock:
            onions_to_disconnect: List[str] = list(self._connections.keys()) + list(
                self._pending_connections.keys()
            )

        for onion in onions_to_disconnect:
            self.disconnect(onion, initiated_by_self=True)

    def send_message(self, target: str, msg: str, msg_id: str) -> None:
        """
        Sends a live chat message and buffers it for ACK verification.
        Implements auto-fallback to drops if the connection is lost.

        Args:
            target (str): The target alias or onion.
            msg (str): The message content.
            msg_id (str): The unique message identifier.

        Returns:
            None
        """
        alias, onion, exists = self._cm.resolve_target(target)
        # We only need to check exists here since get_onion_by_alias returns None if alias or onion doesn't exist
        if not exists:
            return

        with self._lock:
            if onion not in self._connections:
                if Settings.get(SettingKey.FALLBACK_TO_DROP):
                    self._mm.queue_message(
                        onion,
                        MessageDirection.OUT,
                        MessageType.TEXT,
                        msg,
                        MessageStatus.PENDING,
                    )
                    self._hm.log_event(
                        HistoryEvent.ASYNC_QUEUED, onion, 'Auto fallback to drop'
                    )
                    self._broadcast(MsgFallbackToDropEvent(msg_ids=[msg_id]))
                return
            conn: socket.socket = self._connections[onion]
            self._unacked_messages.setdefault(onion, {})[msg_id] = msg

        try:
            b64_msg: str = base64.b64encode(msg.encode('utf-8')).decode('utf-8')
            conn.sendall(f'{TorCommand.MSG.value} {msg_id} {b64_msg}\n'.encode('utf-8'))
        except Exception:
            pass

    def _start_receiving(
        self, onion: str, conn: socket.socket, initial_buffer: str = ''
    ) -> None:
        """
        Starts a background thread to listen for data on a specific live socket.

        Args:
            onion (str): The connected remote onion.
            conn (socket.socket): The active socket connection.
            initial_buffer (str): Leftover TCP stream buffer from the handshake.

        Returns:
            None
        """
        threading.Thread(
            target=self._receiver_target,
            args=(onion, conn, initial_buffer),
            daemon=True,
        ).start()

    def _receiver_target(
        self, onion: str, conn: socket.socket, initial_buffer: str = ''
    ) -> None:
        """
        Target processing incoming live messages, ACKs, and disconnects.
        Uses rigorous TCP line buffering and Headful/Headless routing logic.

        Args:
            onion (str): The remote onion associated with the connection.
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
                            if onion in self._pending_connections:
                                self._pending_connections.pop(onion)
                            self._connections[onion] = conn
                        # alias is defined since onion can't be None and has to be valid
                        alias: str = self._cm.get_alias_by_onion(onion)

                        self._hm.log_event(HistoryEvent.CONNECTED, onion)

                        self._broadcast(
                            ConnectedEvent(
                                alias=alias,
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
                            if onion in self._unacked_messages:
                                self._unacked_messages[onion].pop(msg_id, None)
                        self._broadcast(AckEvent(msg_id=msg_id))

                    elif msg.startswith(f'{TorCommand.MSG.value} '):
                        parts: List[str] = msg.split(' ', 2)
                        if len(parts) == 3:
                            msg_id = parts[1]
                            content: str = base64.b64decode(parts[2]).decode('utf-8')
                            alias = self._cm.get_alias_by_onion(onion)

                            if self._has_clients_callback():
                                # Headful Routing: Relay to UI and ACK
                                try:
                                    conn.sendall(
                                        f'{TorCommand.ACK.value} {msg_id}\n'.encode(
                                            'utf-8'
                                        )
                                    )
                                    self._broadcast(
                                        RemoteMsgEvent(
                                            alias=alias,
                                            text=content,
                                        )
                                    )
                                except Exception:
                                    pass
                            else:
                                # Headless Routing: RAM Buffering
                                buffer_size: int = 0
                                with self._lock:
                                    if onion not in self._ram_buffers:
                                        self._ram_buffers[onion] = []
                                    self._ram_buffers[onion].append((msg_id, content))
                                    buffer_size = len(self._ram_buffers[onion])

                                max_limit: int = Settings.get(
                                    SettingKey.MAX_UNSEEN_LIVE_MSGS
                                )
                                if buffer_size >= max_limit:
                                    # Overflow protection triggered
                                    self.disconnect(onion, initiated_by_self=True)
                                    break

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
                self.reject(onion, initiated_by_self=False)
            elif remote_disconnected:
                self.disconnect(onion, initiated_by_self=False)
            else:
                self.disconnect(onion, initiated_by_self=False, is_fallback=True)
