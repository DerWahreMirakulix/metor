"""
Module defining the background daemon engine handling Tor, cryptography, and IPC API.
"""

import socket
import threading
import secrets
import base64
import json
import nacl.bindings
import time
import atexit
import sys
import os
import signal
from typing import Dict, List, Any, Optional

from metor.data.profile import ProfileManager
from metor.core.key import KeyManager
from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.core.tor import TorManager
from metor.data.history import HistoryManager
from metor.data.contact import ContactManager
from metor.utils.helper import clean_onion
from metor.core.api import IpcCommand, IpcEvent, Action, EventType


class Daemon:
    """The background engine. Handles Tor, crypto, and local IPC API."""

    def __init__(
        self,
        pm: ProfileManager,
        km: KeyManager,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
    ) -> None:
        self._pm: ProfileManager = pm
        self._km: KeyManager = km
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm

        self._connections: Dict[str, socket.socket] = {}
        self._pending_connections: Dict[str, socket.socket] = {}
        self._ipc_clients: List[socket.socket] = []

        self._lock: threading.Lock = threading.Lock()
        self._stop_flag: threading.Event = threading.Event()
        self.ipc_port: Optional[int] = None

        atexit.register(self.stop)

        if os.name != 'nt':
            signal.signal(signal.SIGTERM, self._sig_handler)
            signal.signal(signal.SIGHUP, self._sig_handler)

    def _sig_handler(self, signum: int, frame: Any) -> None:
        """Handles termination signals gracefully."""
        self.stop()
        sys.exit(0)

    def run(self) -> None:
        """Starts the background daemon, Tor, and the IPC server."""
        success: bool = self._tm.start()
        if not success:
            print('Daemon: Failed to start Tor.')
            return

        self._start_tor_listener()
        self._start_ipc_server()

        print(
            f'Daemon running... Onion: {Theme.YELLOW}{clean_onion(self._tm.onion or "")}{Theme.RESET}.onion | IPC Port: {Theme.YELLOW}{self.ipc_port}{Theme.RESET}'
        )

        try:
            while not self._stop_flag.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """Stops the daemon, disconnects all peers, and clears active locks."""
        self._stop_flag.set()

        aliases_to_disconnect: List[str] = list(self._connections.keys()) + list(
            self._pending_connections.keys()
        )
        for alias in aliases_to_disconnect:
            self.disconnect(alias, initiated_by_self=True)

        for c in self._ipc_clients:
            c.close()

        self._pm.clear_daemon_port()
        self._tm.stop()

    def _start_ipc_server(self) -> None:
        """Initializes the local IPC server to communicate with the Chat UI."""
        server: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((Constants.LOCALHOST, 0))
        server.listen(5)
        self.ipc_port = server.getsockname()[1]
        self._pm.set_daemon_port(self.ipc_port)
        threading.Thread(target=self._ipc_acceptor, args=(server,), daemon=True).start()

    def _ipc_acceptor(self, server: socket.socket) -> None:
        """Accepts incoming IPC client connections."""
        while not self._stop_flag.is_set():
            try:
                server.settimeout(1)
                conn, _ = server.accept()
                with self._lock:
                    self._ipc_clients.append(conn)
                threading.Thread(
                    target=self._ipc_handler, args=(conn,), daemon=True
                ).start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _broadcast_ipc(self, event: IpcEvent) -> None:
        """Sends an event payload to all connected IPC clients (UIs)."""
        msg: str = event.to_json() + '\n'
        dead_clients: List[socket.socket] = []
        with self._lock:
            for client in self._ipc_clients:
                try:
                    client.sendall(msg.encode())
                except Exception:
                    dead_clients.append(client)
            for dc in dead_clients:
                self._ipc_clients.remove(dc)

    def _send_to_client(self, conn: socket.socket, event: IpcEvent) -> None:
        """Sends an event payload to a specific IPC client."""
        try:
            msg: str = event.to_json() + '\n'
            conn.sendall(msg.encode())
        except Exception:
            pass

    def _ipc_handler(self, conn: socket.socket) -> None:
        """Listens for commands from a connected IPC client (UI)."""
        buffer: str = ''
        try:
            while True:
                data: bytes = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode()

                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        cmd_dict: Dict[str, Any] = json.loads(line)
                        cmd: IpcCommand = IpcCommand.from_dict(cmd_dict)
                        self._process_ui_command(cmd, conn)
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            with self._lock:
                if conn in self._ipc_clients:
                    self._ipc_clients.remove(conn)
            conn.close()

    def _process_ui_command(self, cmd: IpcCommand, conn: socket.socket) -> None:
        """Dispatches strongly-typed commands received from the chat UI."""
        if cmd.action == Action.INIT:
            self._send_to_client(
                conn, IpcEvent(type=EventType.INIT, onion=self._tm.onion)
            )

        elif cmd.action == Action.GET_CONNECTIONS:
            with self._lock:
                # Get all aliases currently stored in the address book
                contacts: List[str] = self._cm.get_all_contacts()

                self._send_to_client(
                    conn,
                    IpcEvent(
                        type=EventType.CONNECTIONS_STATE,
                        active=list(self._connections.keys()),
                        pending=list(self._pending_connections.keys()),
                        contacts=contacts,
                        is_header=cmd.is_header,
                    ),
                )

        elif cmd.action == Action.GET_CONTACTS_LIST:
            text: str = self._cm.show(chat_mode=cmd.chat_mode)
            self._send_to_client(conn, IpcEvent(type=EventType.CONTACT_LIST, text=text))

        elif cmd.action == Action.CONNECT:
            if not cmd.target:
                return
            alias, onion = self._cm.resolve_target(cmd.target)
            target_name: str = f"'{alias}'" if alias else (onion or '')
            self._broadcast_ipc(
                IpcEvent(
                    type=EventType.INFO,
                    alias=alias,
                    text=f'Connecting to {target_name} ...',
                )
            )
            threading.Thread(
                target=self._establish_connection, args=(cmd.target,), daemon=True
            ).start()

        elif cmd.action == Action.DISCONNECT:
            if cmd.target:
                self.disconnect(cmd.target, initiated_by_self=True)

        elif cmd.action == Action.ACCEPT:
            if cmd.target:
                self.accept_connection(cmd.target)

        elif cmd.action == Action.REJECT:
            if cmd.target:
                self.reject_connection(cmd.target, initiated_by_self=True)

        elif cmd.action == Action.MSG:
            if cmd.target and cmd.text and cmd.msg_id:
                self.send_message(cmd.target, cmd.text, cmd.msg_id)

        elif cmd.action == Action.ADD_CONTACT:
            if not cmd.alias:
                return
            with self._lock:
                if cmd.onion:
                    success, msg = self._cm.add_contact(cmd.alias, cmd.onion)
                else:
                    success, msg = self._cm.promote_session_alias(cmd.alias)
            self._send_to_client(conn, IpcEvent(type=EventType.SYSTEM, text=msg))

        elif cmd.action == Action.REMOVE_CONTACT:
            if not cmd.alias:
                return
            trigger_demotion: bool = False
            new_alias: Optional[str] = None
            history_updated: bool = False

            with self._lock:
                onion: Optional[str] = self._cm.get_onion_by_alias(cmd.alias)
                success, msg = self._cm.remove_contact(cmd.alias)

                if success:
                    if (
                        cmd.alias in self._connections
                        or cmd.alias in self._pending_connections
                    ):
                        new_alias = self._cm.get_alias_by_onion(onion)

                        if cmd.alias in self._connections:
                            self._connections[new_alias or ''] = self._connections.pop(
                                cmd.alias
                            )
                        if cmd.alias in self._pending_connections:
                            self._pending_connections[new_alias or ''] = (
                                self._pending_connections.pop(cmd.alias)
                            )

                        if new_alias:
                            history_updated = self._hm.update_alias(
                                cmd.alias, new_alias
                            )
                            trigger_demotion = True

            if trigger_demotion and new_alias:
                self._broadcast_ipc(
                    IpcEvent(
                        type=EventType.RENAME_SUCCESS,
                        old_alias=cmd.alias,
                        new_alias=new_alias,
                        history_updated=history_updated,
                        is_demotion=True,
                    )
                )
            else:
                self._send_to_client(conn, IpcEvent(type=EventType.SYSTEM, text=msg))

        elif cmd.action == Action.RENAME_CONTACT:
            if not cmd.old_alias or not cmd.new_alias:
                return
            with self._lock:
                success, msg = self._cm.rename_contact(cmd.old_alias, cmd.new_alias)
                if success:
                    if cmd.old_alias in self._connections:
                        self._connections[cmd.new_alias] = self._connections.pop(
                            cmd.old_alias
                        )
                    if cmd.old_alias in self._pending_connections:
                        self._pending_connections[cmd.new_alias] = (
                            self._pending_connections.pop(cmd.old_alias)
                        )

            if success:
                history_updated = self._hm.update_alias(cmd.old_alias, cmd.new_alias)
                self._broadcast_ipc(
                    IpcEvent(
                        type=EventType.RENAME_SUCCESS,
                        old_alias=cmd.old_alias,
                        new_alias=cmd.new_alias,
                        history_updated=history_updated,
                        is_demotion=False,
                    )
                )
            else:
                self._send_to_client(conn, IpcEvent(type=EventType.SYSTEM, text=msg))

        elif cmd.action == Action.SWITCH:
            with self._lock:
                if (
                    cmd.target in self._connections
                    or cmd.target in self._pending_connections
                ):
                    self._send_to_client(
                        conn, IpcEvent(type=EventType.SWITCH_SUCCESS, alias=cmd.target)
                    )
                else:
                    self._send_to_client(
                        conn,
                        IpcEvent(
                            type=EventType.SYSTEM,
                            text=f"Cannot switch: No active or pending connection with '{cmd.target}'.",
                        ),
                    )

    def _sign_challenge(self, challenge_hex: str) -> Optional[str]:
        """Signs a cryptographic challenge using the local Ed25519 secret key."""
        try:
            pynacl_secret_key: bytes = self._km.get_metor_key()
            signed_message: bytes = nacl.bindings.crypto_sign(
                challenge_hex.encode('utf-8'), pynacl_secret_key
            )
            return signed_message[:64].hex()
        except Exception:
            return None

    def _verify_signature(
        self, remote_onion: str, challenge_hex: str, signature_hex: str
    ) -> bool:
        """Verifies a signature payload received from a remote peer."""
        try:
            onion_str: str = clean_onion(remote_onion).upper()
            if len(onion_str) != 56:
                return False
            pad_len: int = 8 - (len(onion_str) % 8)
            if pad_len != 8:
                onion_str += '=' * pad_len
            public_key: bytes = base64.b32decode(onion_str)[:32]
            signature: bytes = bytes.fromhex(signature_hex)
            nacl.bindings.crypto_sign_open(
                signature + challenge_hex.encode('utf-8'), public_key
            )
            return True
        except Exception:
            return False

    def _start_tor_listener(self) -> None:
        """Starts the local listener thread for incoming Tor connections."""
        threading.Thread(target=self._start_listener_target, daemon=True).start()

    def _start_listener_target(self) -> None:
        """Target method for the Tor listener thread."""
        listener: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind((Constants.LOCALHOST, self._tm.incoming_port or 0))
        listener.listen(5)
        while not self._stop_flag.is_set():
            try:
                listener.settimeout(1)
                conn, _ = listener.accept()
                threading.Thread(
                    target=self._handle_incoming_target, args=(conn,), daemon=True
                ).start()
            except socket.timeout:
                continue
            except Exception:
                continue

    def _handle_incoming_target(self, conn: socket.socket) -> None:
        """Handles authentication and connection requests for a new inbound connection."""
        auth_successful: bool = False
        remote_identity: Optional[str] = None
        try:
            conn.settimeout(10)
            challenge: str = secrets.token_hex(32)
            conn.sendall(f'/challenge {challenge}\n'.encode())
            data: bytes = conn.recv(2048)
            if data and data.decode().strip().startswith('/auth '):
                parts: List[str] = data.decode().strip().split(' ')
                if len(parts) == 3 and self._verify_signature(
                    parts[1], challenge, parts[2]
                ):
                    remote_identity = parts[1]
                    auth_successful = True
        except Exception:
            pass

        if not auth_successful or not remote_identity:
            conn.close()
            return

        conn.settimeout(None)
        alias: Optional[str] = self._cm.get_alias_by_onion(remote_identity)
        if not alias:
            conn.close()
            return

        with self._lock:
            if alias in self._connections or alias in self._pending_connections:
                conn.sendall(f'/reject {self._tm.onion}\n'.encode())
                conn.close()
                return
            self._pending_connections[alias] = conn

        self._hm.log_event('requested by remote peer', alias, remote_identity)
        self._broadcast_ipc(
            IpcEvent(
                type=EventType.INFO,
                alias=alias,
                text=f"Incoming connection from '{alias}'. Type '{Theme.GREEN}/accept {alias}{Theme.RESET}' or '{Theme.RED}/reject {alias}{Theme.RESET}'.",
            )
        )

    def _establish_connection(self, target: str) -> None:
        """Initiates an outbound Tor connection to a remote peer."""
        alias, onion = self._cm.resolve_target(target)
        if onion == self._tm.onion:
            self._broadcast_ipc(
                IpcEvent(type=EventType.SYSTEM, text='Cannot connect to yourself.')
            )
            return

        if not alias or not onion:
            return

        with self._lock:
            if alias in self._connections:
                self._broadcast_ipc(
                    IpcEvent(type=EventType.SYSTEM, text='Already connected.')
                )
                return

        try:
            conn: socket.socket = self._tm.connect(onion)
        except Exception:
            self._broadcast_ipc(
                IpcEvent(type=EventType.INFO, text='Failed to connect via Tor.')
            )
            return

        try:
            conn.settimeout(10)
            data: bytes = conn.recv(1024)
            challenge: str = data.decode().strip().split(' ')[1]
            signature: Optional[str] = self._sign_challenge(challenge)
            conn.sendall(f'/auth {self._tm.onion} {signature}\n'.encode())
            conn.settimeout(None)
        except Exception:
            conn.close()
            return

        self._hm.log_event('requested', alias, onion)
        self._broadcast_ipc(
            IpcEvent(
                type=EventType.INFO,
                alias=alias,
                text="Request sent to '{alias}'. Waiting for them to accept...",
            )
        )
        self._start_receiving_thread(alias, conn)

    def accept_connection(self, alias: str) -> None:
        """Accepts a pending incoming connection request."""
        with self._lock:
            if alias not in self._pending_connections:
                return
            conn: socket.socket = self._pending_connections.pop(alias)
            self._connections[alias] = conn

        try:
            conn.sendall(b'/accepted\n')
        except Exception:
            pass
        onion: Optional[str] = self._cm.get_onion_by_alias(alias)
        self._hm.log_event('connected', alias, onion)
        self._broadcast_ipc(
            IpcEvent(
                type=EventType.CONNECTED,
                alias=alias,
                onion=onion,
                text="Connection established with '{alias}'.",
            )
        )
        self._start_receiving_thread(alias, conn)

    def reject_connection(self, alias: str, initiated_by_self: bool = True) -> None:
        """Rejects a pending connection request."""
        conn: Optional[socket.socket] = None
        with self._lock:
            if alias in self._connections:
                conn = self._connections.pop(alias)
            elif alias in self._pending_connections:
                conn = self._pending_connections.pop(alias)

        if conn:
            if initiated_by_self:
                try:
                    conn.sendall(f'/reject {self._tm.onion}\n'.encode())
                except Exception:
                    pass
            conn.close()

        status: str = 'rejected' if initiated_by_self else 'rejected by remote peer'
        self._hm.log_event(status, alias, self._cm.get_onion_by_alias(alias))

        msg: str = (
            "Connection with '{alias}' rejected."
            if initiated_by_self
            else "Connection with '{alias}' rejected by peer."
        )
        self._broadcast_ipc(IpcEvent(type=EventType.INFO, alias=alias, text=msg))

    def disconnect(
        self, alias: str, initiated_by_self: bool = True, is_fallback: bool = False
    ) -> None:
        """Terminates an active connection."""
        conn: Optional[socket.socket] = None
        with self._lock:
            if alias in self._connections:
                conn = self._connections.pop(alias)
            elif alias in self._pending_connections:
                conn = self._pending_connections.pop(alias)

        if conn:
            if initiated_by_self:
                try:
                    conn.sendall(f'/disconnect {self._tm.onion}\n'.encode())
                    time.sleep(0.2)
                    conn.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass

            try:
                conn.close()
            except Exception:
                pass

            if is_fallback:
                status: str = 'connection cancelled / lost'
            else:
                status = (
                    'disconnected'
                    if initiated_by_self
                    else 'disconnected by remote peer'
                )

            self._hm.log_event(status, alias, self._cm.get_onion_by_alias(alias))

            msg: str = (
                "Peer '{alias}' disconnected."
                if not is_fallback
                else "Connection to '{alias}' cancelled / lost."
            )
            self._broadcast_ipc(
                IpcEvent(type=EventType.DISCONNECTED, alias=alias, text=msg)
            )

    def send_message(self, alias: str, msg: str, msg_id: str) -> None:
        """Sends an encrypted chat message to a connected peer."""
        with self._lock:
            if alias not in self._connections:
                return
            conn: socket.socket = self._connections[alias]
        try:
            b64_msg: str = base64.b64encode(msg.encode('utf-8')).decode('utf-8')
            conn.sendall(f'/msg {msg_id} {b64_msg}\n'.encode())
        except Exception:
            pass

    def _start_receiving_thread(self, alias: str, conn: socket.socket) -> None:
        """Starts a thread to listen for incoming messages from a specific peer."""
        threading.Thread(
            target=self._receiver_target, args=(alias, conn), daemon=True
        ).start()

    def _receiver_target(self, initial_alias: str, conn: socket.socket) -> None:
        """Target method processing incoming data on an active peer connection."""
        current_alias: str = initial_alias
        remote_rejected: bool = False
        remote_disconnected: bool = False

        try:
            while True:
                data: bytes = conn.recv(1024)
                if not data:
                    break

                with self._lock:
                    for k, v in list(self._connections.items()) + list(
                        self._pending_connections.items()
                    ):
                        if v == conn:
                            current_alias = k

                for msg in data.decode().strip().split('\n'):
                    msg = msg.strip()
                    if not msg:
                        continue

                    if msg == '/accepted':
                        with self._lock:
                            if current_alias in self._pending_connections:
                                self._pending_connections.pop(current_alias)
                            self._connections[current_alias] = conn

                        onion: Optional[str] = self._cm.get_onion_by_alias(
                            current_alias
                        )
                        self._hm.log_event('connected', current_alias, onion)
                        self._broadcast_ipc(
                            IpcEvent(
                                type=EventType.CONNECTED,
                                alias=current_alias,
                                onion=onion,
                                text="Connection established with '{alias}'.",
                            )
                        )

                    elif msg.startswith('/disconnect '):
                        remote_disconnected = True
                        break

                    elif msg.startswith('/reject '):
                        remote_rejected = True
                        break

                    elif msg.startswith('/ack '):
                        msg_id: str = msg.split(' ')[1]
                        self._broadcast_ipc(IpcEvent(type=EventType.ACK, msg_id=msg_id))

                    elif msg.startswith('/msg '):
                        parts: List[str] = msg.split(' ', 2)
                        if len(parts) == 3:
                            msg_id, b64_content = parts[1], parts[2]
                            try:
                                conn.sendall(f'/ack {msg_id}\n'.encode())
                            except Exception:
                                pass
                            try:
                                content: str = base64.b64decode(b64_content).decode(
                                    'utf-8'
                                )
                            except Exception:
                                content = b64_content
                            self._broadcast_ipc(
                                IpcEvent(
                                    type=EventType.REMOTE_MSG,
                                    alias=current_alias,
                                    text=content,
                                )
                            )

        except Exception:
            pass
        finally:
            if remote_rejected:
                self.reject_connection(current_alias, initiated_by_self=False)
            elif remote_disconnected:
                self.disconnect(current_alias, initiated_by_self=False)
            else:
                self.disconnect(
                    current_alias, initiated_by_self=False, is_fallback=True
                )
