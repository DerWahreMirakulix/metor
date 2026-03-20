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

        atexit.register(self.stop)
        
        if os.name != 'nt':
            signal.signal(signal.SIGTERM, self._sig_handler)
            signal.signal(signal.SIGHUP, self._sig_handler)

    def _sig_handler(self, signum, frame):
        self.stop()
        sys.exit(0)

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
        msg = json.dumps(data_dict) + "\n"
        dead_clients = []
        with self._lock:
            for client in self._ipc_clients:
                try: client.sendall(msg.encode())
                except Exception: dead_clients.append(client)
            for dc in dead_clients:
                self._ipc_clients.remove(dc)

    def _send_to_client(self, conn, data_dict):
        try:
            msg = json.dumps(data_dict) + "\n"
            conn.sendall(msg.encode())
        except Exception: pass

    def _ipc_handler(self, conn):
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

        elif action == "get_contacts_list":
            text = self.cm.show(chat_mode=cmd.get("chat_mode", False))
            self._send_to_client(conn, {"type": "contact_list", "text": text})

        elif action == "connect":
            alias, onion = self.cm.resolve_target(target)
            target_name = f'"{alias}"' if alias else onion
            self._broadcast_ipc({"type": "info", "alias": alias, "text": f"Connecting to {target_name} ..."})
            threading.Thread(target=self._establish_connection, args=(target,), daemon=True).start()

        elif action == "disconnect":
            self.disconnect(target, initiated_by_self=True)

        elif action == "accept":
            self.accept_connection(target)

        elif action == "reject":
            self.reject_connection(target, initiated_by_self=True)

        elif action == "msg":
            self.send_message(target, cmd.get("text"), cmd.get("msg_id"))
            
        elif action == "add_contact":
            alias = cmd.get("alias")
            onion = cmd.get("onion")
            
            with self._lock:
                if onion:
                    success, msg = self.cm.add_contact(alias, onion)
                else:
                    success, msg = self.cm.promote_session_alias(alias)
            self._send_to_client(conn, {"type": "system", "text": msg})

        elif action == "remove_contact":
            alias = cmd.get("alias")
            
            trigger_demotion = False
            new_alias = None
            history_updated = False
            
            with self._lock:
                onion = self.cm.get_onion_by_alias(alias)
                success, msg = self.cm.remove_contact(alias)
                
                if success:
                    if alias in self._connections or alias in self._pending_connections:
                        new_alias = self.cm.get_alias_by_onion(onion) 
                        
                        if alias in self._connections:
                            self._connections[new_alias] = self._connections.pop(alias)
                        if alias in self._pending_connections:
                            self._pending_connections[new_alias] = self._pending_connections.pop(alias)
                            
                        history_updated = self.hm.update_alias(alias, new_alias)
                        trigger_demotion = True
                        
            if trigger_demotion:
                self._broadcast_ipc({
                    "type": "rename_success", 
                    "old_alias": alias, 
                    "new_alias": new_alias,
                    "history_updated": history_updated,
                    "is_demotion": True
                })
            else:
                self._send_to_client(conn, {"type": "system", "text": msg})
            
        elif action == "rename_contact":
            old_alias, new_alias = cmd.get("old_alias"), cmd.get("new_alias")
            with self._lock:
                success, msg = self.cm.rename_contact(old_alias, new_alias)
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
                    "history_updated": history_updated,
                    "is_demotion": False
                })
            else:
                self._send_to_client(conn, {"type": "system", "text": msg})

        elif action == "switch":
            with self._lock:
                if target in self._connections or target in self._pending_connections:
                    self._send_to_client(conn, {"type": "switch_success", "alias": target})
                else:
                    self._send_to_client(conn, {"type": "system", "text": f"Cannot switch: No active or pending connection with '{target}'."})

    # --- CRYPTO & TOR UTILS ---
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
        alias, onion = self.cm.resolve_target(target)
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
        self._broadcast_ipc({"type": "info", "alias": alias, "text": "Request sent to '{alias}'. Waiting for them to accept..."})
        self._start_receiving_thread(alias, conn)

    def accept_connection(self, alias):
        with self._lock:
            if alias not in self._pending_connections: return
            conn = self._pending_connections.pop(alias)
            self._connections[alias] = conn

        try: conn.sendall(b"/accepted\n")
        except Exception: pass
        onion = self.cm.get_onion_by_alias(alias)
        self.hm.log_event("connected", alias, onion)
        self._broadcast_ipc({"type": "connected", "alias": alias, "onion": onion, "text": "Connection established with '{alias}'."})
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
        
        msg = "Connection with '{alias}' rejected." if initiated_by_self else "Connection with '{alias}' rejected by peer."
        self._broadcast_ipc({"type": "info", "alias": alias, "text": msg})

    def disconnect(self, alias, initiated_by_self=True, is_fallback=False):
        conn = None
        with self._lock:
            if alias in self._connections: conn = self._connections.pop(alias)
            elif alias in self._pending_connections: conn = self._pending_connections.pop(alias)
        
        if conn:
            if initiated_by_self:
                try: 
                    conn.sendall(f"/disconnect {self.tm.onion}\n".encode())
                    # timeout to let disconnect message be sent
                    time.sleep(0.2)
                    conn.shutdown(socket.SHUT_RDWR)
                except Exception: pass
                
            try: conn.close()
            except Exception: pass
            
            if is_fallback:
                status = "connection cancelled / lost"
            else:
                status = "disconnected" if initiated_by_self else "disconnected by remote peer"
            
            self.hm.log_event(status, alias, self.cm.get_onion_by_alias(alias))
            
            msg = "Peer '{alias}' disconnected." if not is_fallback else "Connection to '{alias}' cancelled / lost."
            self._broadcast_ipc({"type": "disconnected", "alias": alias, "text": msg})

    def send_message(self, alias, msg, msg_id):
        with self._lock:
            if alias not in self._connections: return
            conn = self._connections[alias]
        try:
            b64_msg = base64.b64encode(msg.encode('utf-8')).decode('utf-8')
            conn.sendall(f"/msg {msg_id} {b64_msg}\n".encode())
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
    
                        onion = self.cm.get_onion_by_alias(current_alias)
                        self.hm.log_event("connected", current_alias, onion)
                        self._broadcast_ipc({"type": "connected", "alias": current_alias, "onion": onion, "text": "Connection established with '{alias}'."})
                        
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
                        if len(parts) == 3:
                            msg_id, b64_content = parts[1], parts[2]
                            try: conn.sendall(f"/ack {msg_id}\n".encode())
                            except Exception: pass    
                            try: content = base64.b64decode(b64_content).decode('utf-8')
                            except Exception: content = b64_content
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
