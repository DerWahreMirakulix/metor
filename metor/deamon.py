import socket
import threading
import secrets
import base64
import json
import nacl.bindings
import time

from metor.profile import ProfileManager
from metor.key import KeyManager
from metor.settings import Settings
from metor.tor import TorManager
from metor.history import HistoryManager
from metor.contact import ContactManager
from metor.utils import clean_onion, ensure_onion_format

class Daemon:
    """The background engine. Handles Tor, crypto, and local IPC API."""
    
    def __init__(self, pm: ProfileManager, km: KeyManager, tm: TorManager, cm: ContactManager, hm: HistoryManager):
        self.pm = pm
        self.km = km
        self.tm = tm
        self.cm = cm
        self.hm = hm
        
        self._connections = {}
        self._pending_connections = {}
        self._ipc_clients = []
        
        self._lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.ipc_port = None

    def run(self):
        success = self.tm.start()
        if not success:
            print("Daemon: Failed to start Tor.")
            return

        self.start_tor_listener()
        self.start_ipc_server()
        
        print(f"Daemon running... Onion: {Settings.YELLOW}{clean_onion(self.tm.onion)}{Settings.RESET}.onion | IPC Port: {Settings.YELLOW}{self.ipc_port}{Settings.RESET}")
        
        try:
            while not self.stop_flag.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        """Cleanly shuts down the daemon, informing all peers."""
        self.stop_flag.set()
        
        aliases_to_disconnect = list(self._connections.keys()) + list(self._pending_connections.keys())
        for alias in aliases_to_disconnect:
            self.disconnect(alias, initiated_by_self=True)
            
        for c in self._ipc_clients: 
            c.close()
            
        self.pm.clear_daemon_port()
        self.tm.stop()

    def start_ipc_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(('127.0.0.1', 0))
        server.listen(5)
        self.ipc_port = server.getsockname()[1]
        self.pm.set_daemon_port(self.ipc_port)
        threading.Thread(target=self._ipc_acceptor, args=(server,), daemon=True).start()

    def _ipc_acceptor(self, server):
        while not self.stop_flag.is_set():
            try:
                server.settimeout(1)
                conn, _ = server.accept()
                with self._lock: self._ipc_clients.append(conn)
                threading.Thread(target=self._ipc_handler, args=(conn,), daemon=True).start()
            except socket.timeout: continue
            except Exception: break

    def _broadcast_ipc(self, data_dict):
        """Send JSON events to all connected UI clients."""
        msg = json.dumps(data_dict) + "\n"
        dead_clients = []
        with self._lock:
            for client in self._ipc_clients:
                try: client.sendall(msg.encode())
                except Exception: dead_clients.append(client)
            for dc in dead_clients:
                self._ipc_clients.remove(dc)

    def _send_to_client(self, conn, data_dict):
        """Sends a response specifically to the client that made the request."""
        try:
            msg = json.dumps(data_dict) + "\n"
            conn.sendall(msg.encode())
        except Exception: pass

    def _ipc_handler(self, conn):
        """Reads commands from the local chat UI with a safe TCP buffer."""
        buffer = ""
        try:
            while True:
                data = conn.recv(4096)
                if not data: break
                buffer += data.decode()
                
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line: continue
                    
                    try:
                        cmd = json.loads(line)
                        self._process_ui_command(cmd, conn)
                    except Exception: pass
        except Exception: pass
        finally:
            with self._lock:
                if conn in self._ipc_clients: self._ipc_clients.remove(conn)
            conn.close()

    def _process_ui_command(self, cmd, conn):
        action = cmd.get("action")
        target = cmd.get("target")
        
        if action == "init":
            self._send_to_client(conn, {"type": "init", "onion": self.tm.onion})
            
        elif action == "get_connections":
            with self._lock:
                self._send_to_client(conn, {
                    "type": "connections_state",
                    "active": list(self._connections.keys()),
                    "pending": list(self._pending_connections.keys()),
                    "is_header": cmd.get("is_header", False)
                })
                
        elif action == "connect":
            alias, onion = self._resolve_target(target) or target
            self._broadcast_ipc({"type": "system", "alias": alias, "text": f"Connecting to {alias if alias else onion} ..."})
            threading.Thread(target=self._establish_connection, args=(target,), daemon=True).start()
            
        elif action == "disconnect":
            self.disconnect(target, initiated_by_self=True)
        elif action == "accept":
            self.accept_connection(target)
        elif action == "reject":
            self.reject_connection(target, initiated_by_self=True)
        elif action == "msg":
            self.send_message(target, cmd.get("text"), cmd.get("msg_id"))
            
        elif action == "rename_contact":
            old_alias, new_alias = cmd.get("old_alias"), cmd.get("new_alias")
            with self._lock:
                success, _ = self.cm.rename_contact(old_alias, new_alias)
                if success:
                    if old_alias in self._connections:
                        self._connections[new_alias] = self._connections.pop(old_alias)
                    if old_alias in self._pending_connections:
                        self._pending_connections[new_alias] = self._pending_connections.pop(old_alias)
                        
            if success:
                history_updated = self.hm.update_alias(old_alias, new_alias)
                self._broadcast_ipc({
                    "type": "rename_success", 
                    "old_alias": old_alias, 
                    "new_alias": new_alias,
                    "history_updated": history_updated
                })
            else:
                self._send_to_client(conn, {"type": "system", "text": "Failed to rename. Check if old alias exists and new alias is free."})

    # --- CRYPTO & TOR UTILS ---
    def _resolve_target(self, target: str | None, default_value: str | None = None):
        onion = self.cm.get_onion_by_alias(target)
        if not onion: onion = ensure_onion_format(target)
        alias = self.cm.get_alias_by_onion(onion)
        return (alias or default_value, onion or default_value)

    def _sign_challenge(self, challenge_hex):
        try:
            pynacl_secret_key = self.km.get_metor_key()
            signed_message = nacl.bindings.crypto_sign(challenge_hex.encode('utf-8'), pynacl_secret_key)
            return signed_message[:64].hex()
        except Exception: return None

    def _verify_signature(self, remote_onion, challenge_hex, signature_hex):
        try:
            onion_str = clean_onion(remote_onion).upper()
            if len(onion_str) != 56: return False
            pad_len = 8 - (len(onion_str) % 8)
            if pad_len != 8: onion_str += "=" * pad_len
            public_key = base64.b32decode(onion_str)[:32] 
            signature = bytes.fromhex(signature_hex)
            nacl.bindings.crypto_sign_open(signature + challenge_hex.encode('utf-8'), public_key)
            return True
        except Exception: return False

    # --- NETWORK LOGIC ---
    def start_tor_listener(self):
        threading.Thread(target=self._start_listener_target, daemon=True).start()

    def _start_listener_target(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', self.tm.incoming_port))
        listener.listen(5)
        while not self.stop_flag.is_set():
            try:
                listener.settimeout(1)
                conn, _ = listener.accept()
                threading.Thread(target=self._handle_incoming_target, args=(conn,), daemon=True).start()
            except socket.timeout: continue
            except Exception: continue

    def _handle_incoming_target(self, conn):
        auth_successful, remote_identity = False, None
        try:
            conn.settimeout(10)
            challenge = secrets.token_hex(32)
            conn.sendall(f"/challenge {challenge}\n".encode())
            data = conn.recv(2048)
            if data and data.decode().strip().startswith("/auth "):
                parts = data.decode().strip().split(" ")
                if len(parts) == 3 and self._verify_signature(parts[1], challenge, parts[2]):
                    remote_identity = parts[1]
                    auth_successful = True
        except Exception: pass

        if not auth_successful:
            conn.close()
            return

        conn.settimeout(None) 
        alias = self.cm.get_alias_by_onion(remote_identity)

        with self._lock:
            if alias in self._connections or alias in self._pending_connections:
                conn.sendall(f"/reject {self.tm.onion}\n".encode())
                conn.close()
                return
            self._pending_connections[alias] = conn

        self.hm.log_event("requested by remote peer", alias, remote_identity)
        self._broadcast_ipc({
            "type": "info", 
            "alias": alias, 
            "text": f'Incoming connection from "{{alias}}". Type "{Settings.GREEN}/accept {{alias}}{Settings.RESET}" or "{Settings.RED}/reject {{alias}}{Settings.RESET}".'
        })

    def _establish_connection(self, target):
        alias, onion = self._resolve_target(target)
        if onion == self.tm.onion:
            self._broadcast_ipc({"type": "system", "text": "Cannot connect to yourself."})
            return

        with self._lock:
            if alias in self._connections:
                self._broadcast_ipc({"type": "system", "text": "Already connected."})
                return
                
        try: conn = self.tm.connect(onion)
        except Exception:
            self._broadcast_ipc({"type": "info", "text": "Failed to connect via Tor."})
            return 
        
        try:
            conn.settimeout(10)
            data = conn.recv(1024)
            challenge = data.decode().strip().split(" ")[1]
            signature = self._sign_challenge(challenge)
            conn.sendall(f"/auth {self.tm.onion} {signature}\n".encode())
            conn.settimeout(None)
        except Exception:
            conn.close()
            return
            
        self.hm.log_event("requested", alias, onion)
        self._broadcast_ipc({"type": "info", "alias": alias, "text": 'Request sent to "{alias}". Waiting for them to accept...'})
        self._start_receiving_thread(alias, conn)

    def accept_connection(self, alias):
        with self._lock:
            if alias not in self._pending_connections: return
            conn = self._pending_connections.pop(alias)
            self._connections[alias] = conn

        try: conn.sendall(b"/accepted\n")
        except Exception: pass
        self.hm.log_event("connected", alias, self.cm.get_onion_by_alias(alias))
        self._broadcast_ipc({"type": "connected", "alias": alias, "text": "Connection established with {alias}."})
        self._start_receiving_thread(alias, conn)

    def reject_connection(self, alias, initiated_by_self=True):
        conn = None
        with self._lock:
            if alias in self._connections: conn = self._connections.pop(alias)
            elif alias in self._pending_connections: conn = self._pending_connections.pop(alias)
            
        if conn:
            if initiated_by_self:
                try: conn.sendall(f"/reject {self.tm.onion}\n".encode())
                except Exception: pass
            conn.close()
        
        status = "rejected" if initiated_by_self else "rejected by remote peer"
        self.hm.log_event(status, alias, self.cm.get_onion_by_alias(alias))
        
        msg = "Connection with {alias} rejected." if initiated_by_self else "Connection with {alias} rejected by peer."
        self._broadcast_ipc({"type": "info", "alias": alias, "text": msg})

    def disconnect(self, alias, initiated_by_self=True, is_fallback=False):
        conn = None
        with self._lock:
            if alias in self._connections: conn = self._connections.pop(alias)
            elif alias in self._pending_connections: conn = self._pending_connections.pop(alias)
        
        if conn:
            if initiated_by_self:
                try: conn.sendall(f"/disconnect {self.tm.onion}\n".encode())
                except Exception: pass
            conn.close()
            
            if is_fallback:
                status = "connection cancelled / lost"
            else:
                status = "disconnected" if initiated_by_self else "disconnected by remote peer"
            
            self.hm.log_event(status, alias, self.cm.get_onion_by_alias(alias))
            
            msg = "Peer {alias} disconnected." if not is_fallback else "Connection to {alias} cancelled / lost."
            self._broadcast_ipc({"type": "disconnected", "alias": alias, "text": msg})

    def send_message(self, alias, msg, msg_id):
        with self._lock:
            if alias not in self._connections: return
            conn = self._connections[alias]
        try:
            conn.sendall(f"/msg {msg_id} {msg}\n".encode())
        except Exception: pass

    def _start_receiving_thread(self, alias, conn):
        threading.Thread(target=self._receiver_target, args=(alias, conn), daemon=True).start()

    def _receiver_target(self, initial_alias, conn):
        current_alias = initial_alias
        remote_rejected = False
        remote_disconnected = False
        
        try:
            while True:
                data = conn.recv(1024)
                if not data: break
                
                with self._lock:
                    for k, v in list(self._connections.items()) + list(self._pending_connections.items()):
                        if v == conn: current_alias = k

                for msg in data.decode().strip().split("\n"):
                    msg = msg.strip()
                    if not msg: continue
        
                    if msg == "/accepted":
                        with self._lock:
                            if current_alias in self._pending_connections:
                                self._pending_connections.pop(current_alias)
                            self._connections[current_alias] = conn
                        self._broadcast_ipc({"type": "connected", "alias": current_alias, "text": "Connection established with {alias}."})
                        
                    elif msg.startswith("/disconnect "):
                        remote_disconnected = True
                        break 
                        
                    elif msg.startswith("/reject "):
                        remote_rejected = True
                        break 
                        
                    elif msg.startswith("/ack "):
                        msg_id = msg.split(" ")[1]
                        self._broadcast_ipc({"type": "ack", "msg_id": msg_id})
                                
                    elif msg.startswith("/msg "):
                        parts = msg.split(" ", 2)
                        msg_id, content = parts[1], parts[2]
                        try: conn.sendall(f"/ack {msg_id}\n".encode())
                        except Exception: pass    
                        self._broadcast_ipc({"type": "remote_msg", "alias": current_alias, "text": content})
                        
        except Exception:
            pass
        finally:
            if remote_rejected:
                self.reject_connection(current_alias, initiated_by_self=False)
            elif remote_disconnected:
                self.disconnect(current_alias, initiated_by_self=False)
            else:
                self.disconnect(current_alias, initiated_by_self=False, is_fallback=True)
