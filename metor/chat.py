import socket
import threading
import secrets
import base64
import binascii
import nacl.bindings

from metor.config import HelpMenu, ProfileManager, KeyManager, Settings
from metor.tor import TorManager
from metor.history import HistoryManager
from metor.cli import CommandLineInput
from metor.contacts import ContactsManager
from metor.utils import clean_onion

class ChatManager:
    """Core controller for chat connections, user inputs, and IO orchestration."""
    
    def __init__(self, profile_manager: ProfileManager, key_manager: KeyManager, tor_manager: TorManager, contacts: ContactsManager, history_manager: HistoryManager, cli: CommandLineInput):
        self.pm = profile_manager
        self.km = key_manager
        self.tor = tor_manager
        self.contacts = contacts
        self.history = history_manager
        self.cli = cli
        
        self._connections = {}
        self._pending_connections = {}
        self._focused_alias = None 
        self._connection_lock = threading.Lock()
    
        self.stop_flag = threading.Event()

    def run(self):
        """Main Loop replacing run_chat_mode."""
        try:
            self.cli.start_loading("Starting Tor process (this may take a few seconds)...")
            success = self.tor.start()
            self.cli.end_loading()

            if not success:
                self.cli.print_message("Failed to start Tor.", msg_type="raw", skip_prompt=True)
                return

            self.start_listener()
            self.print_header()
            
            while True:
                user_input = self.cli.read_line()
                
                if user_input == "":
                    self.cli.print_prompt()
                elif user_input == "/connections":
                    self.print_connections()
                elif user_input == "/clear":
                    self.print_header(clear_screen=True)
                elif user_input == "/exit":
                    if self.is_connected():
                        self.disconnect_all()
                    self.stop_flag.set()
                    break
                elif user_input.startswith("/end"):
                    parts = user_input.split()
                    if len(parts) == 1:
                        if self.is_connected() and self._focused_alias:
                            self.disconnect_active()
                        else:
                            self.cli.print_message("No active connection to end.", msg_type="system")
                    else:
                        target_alias = parts[1].lower()
                        with self._connection_lock:
                            exists = target_alias in self._connections or target_alias in self._pending_connections
                        
                        if exists:
                            self.disconnect(target_alias, initiated_by_self=True)
                        else:
                            self.cli.print_message(f'No active or pending connection with "{target_alias}".', msg_type="system")
                elif user_input.startswith("/connect"):
                    parts = user_input.split()
                    if len(parts) < 2:
                        self.cli.print_message("Usage: \"/connect [onion/alias]\".", msg_type="system")
                    else:
                        self.connect(parts[1].lower())
                elif user_input.startswith("/accept"):
                    parts = user_input.split()
                    if len(parts) < 2:
                        self.cli.print_message("Usage: \"/accept [alias]\".", msg_type="system")
                    else:
                        self.accept_connection(parts[1].lower())
                elif user_input.startswith("/reject"):
                    parts = user_input.split()
                    if len(parts) < 2:
                        self.cli.print_message("Usage: \"/reject [alias]\".", msg_type="system")
                    else:
                        self.reject_connection(parts[1].lower())
                elif user_input.startswith("/switch"):
                    parts = user_input.split()
                    if len(parts) < 2:
                        self.cli.print_message("Usage: \"/switch [alias]\".", msg_type="system")
                    else:
                        self.switch_focus(parts[1].lower())
                elif user_input.startswith("/contacts"):
                    parts = user_input.split()
                    subcmd = parts[1] if len(parts) > 1 else "list"

                    if subcmd == "list":
                        self.print_contacts()
                        
                    elif subcmd == "add":
                        if len(parts) < 4:
                            self.cli.print_message("Usage: \"/contacts add [alias] [onion]\".", msg_type="system")
                        else:
                            alias = self.contacts.add_contact(parts[2], parts[3])
                            self.cli.print_message(f"Contact '{alias}' added successfully.", msg_type="system")
                            
                    elif subcmd in ("rm", "remove"):
                        if len(parts) < 3:
                            self.cli.print_message("Usage: \"/contacts rm [alias]\".", msg_type="system")
                        else:
                            alias = parts[2]
                            if self.contacts.remove_contact(alias):
                                self.cli.print_message(f"Contact '{alias}' removed.", msg_type="system")
                            else:
                                self.cli.print_message(f"Contact '{alias}' not found.", msg_type="system")
                                
                    elif subcmd == "rename":
                        if len(parts) < 4:
                            self.cli.print_message("Usage: \"/contacts rename [old_alias] [new_alias]\".", msg_type="system")
                        else:
                            self.rename_alias(parts[2].lower(), parts[3].lower())
                    else:
                        self.cli.print_message("Usage: \"/contacts [list|add|rm|rename]\".", msg_type="system")
                else:
                    if self.is_connected():
                        self.send_message(user_input)
                    else:
                        self.cli.print_message("No active connection. Use /connect to initiate a connection.", msg_type="system")
                        
        except KeyboardInterrupt:
            self.disconnect_all()
            self.stop_flag.set()
            self.cli.clear_line() 
        finally:
            self.tor.stop()

    def _resolve_target(self, target: str | None, default_value: str | None = None):
        onion = self.contacts.get_onion_by_alias(target)
        if not onion:
            onion = self.contacts.ensure_onion_format(target)
        alias = self.contacts.get_alias_by_onion(onion)
        return (alias or default_value, onion or default_value)

    def _log_reject(self, target: str | None = None, remote: bool = False):
        alias, onion = self._resolve_target(target, default_value="unknown")
        msg = f"Connection {'by' if remote else 'from'} \"{{alias}}\" rejected."
        self.cli.print_message(msg, msg_type="info", alias=alias)
        self.history.log_event("rejected by remote peer" if remote else "rejected", alias, onion)

    def _log_failed(self, target: str | None = None, reason=""):
        alias, onion = self._resolve_target(target, default_value="unknown")
        msg = f'Connection with "{{alias}}" failed{f": {reason}" if reason else ""}.'
        self.cli.print_message(msg, msg_type="info", alias=alias)
        self.history.log_event("failed", alias, onion, reason)

    def _log_request(self, target: str | None = None, remote: bool = False):
        alias, onion = self._resolve_target(target, default_value="unknown")
        if remote:
            self.cli.print_message('Incoming connection from "{alias}". Type "/accept {alias}" or "/reject {alias}".', msg_type="info", alias=alias)
        else:
            self.cli.print_message('Request sent to "{alias}". Waiting for them to accept...', msg_type="info", alias=alias)
        self.history.log_event("requested by remote peer" if remote else "requested", alias, onion)

    def _log_connect(self, target: str | None = None):
        alias, onion = self._resolve_target(target, default_value="unknown")
        self.cli.print_message('Connection with "{alias}" established.', msg_type="info", alias=alias)
        self.history.log_event("connected", alias, onion)

    def _log_disconnect(self, target: str | None = None, remote: bool = False):
        alias, onion = self._resolve_target(target, default_value="unknown")
        msg = f"Connection with \"{{alias}}\" disconnected{' by remote peer' if remote else ''}."
        self.cli.print_message(msg, msg_type="info", alias=alias)
        self.history.log_event("disconnected by remote peer" if remote else "disconnected", alias, onion)

    def print_header(self, clear_screen=False):
        if clear_screen:
            self.cli.clear_screen()
            
        self.cli.print_message(f"Your onion address: {Settings.RED}{clean_onion(self.tor.onion)}{Settings.RESET}.onion", skip_prompt=True)
        self.cli.print_empty_line()
        self.cli.print_message(HelpMenu.show_chat_help(), skip_prompt=True)
        self.cli.print_empty_line()
        
        if self.is_connected():
            self.print_connections(header_mode=True)
            self.cli.print_empty_line()
            self.cli.print_prompt()
        else:
            self.cli.print_prompt()

    def print_contacts(self):
        self.cli.print_message(self.contacts.show(chat_mode=True), msg_type="system")

    def print_connections(self, header_mode=False):
        msg_type = "system" if not header_mode else "raw"

        if not self.is_connected() and not self._pending_connections:
            if not header_mode:
                self.cli.print_message("No active or pending connections.", msg_type="system")
            return

        with self._connection_lock:
            active_aliases = list(self._connections.keys())
            pending_aliases = list(self._pending_connections.keys())
            current_focus = self._focused_alias

        if active_aliases:     
            self.cli.print_message("Active connections:", msg_type=msg_type, skip_prompt=header_mode)
            for alias in active_aliases:
                marker = "*" if alias == current_focus else " "
                onion = self.contacts.get_onion_by_alias(alias)
                self.cli.print_message(f" {marker} {Settings.CYAN}{alias}{Settings.RESET} -> {onion}", msg_type=msg_type, skip_prompt=header_mode) 
        
        if pending_aliases:
            if active_aliases:
                self.cli.print_empty_line()
            self.cli.print_message("Pending connections:", msg_type=msg_type, skip_prompt=header_mode)
            for alias in pending_aliases:
                onion = self.contacts.get_onion_by_alias(alias)
                self.cli.print_message(f"   {Settings.CYAN}{alias}{Settings.RESET} -> {onion}", msg_type=msg_type, skip_prompt=header_mode)

    def _set_focused_alias(self, alias):
        with self._connection_lock:
            self._focused_alias = alias
        self.cli.set_focus(alias)

    def _sign_challenge(self, challenge_hex):
        try:
            pynacl_secret_key = self.km.get_metor_key()
            message = challenge_hex.encode('utf-8')
            signed_message = nacl.bindings.crypto_sign(message, pynacl_secret_key)
            signature = signed_message[:64]
            return signature.hex()
        except Exception:
            return None

    def _verify_signature(self, remote_onion, challenge_hex, signature_hex):
        try:
            onion_str = clean_onion(remote_onion).upper()
            if len(onion_str) != 56: return False
            pad_len = 8 - (len(onion_str) % 8)
            if pad_len != 8: onion_str += "=" * pad_len
                
            try: decoded = base64.b32decode(onion_str)
            except binascii.Error: return False 
                
            public_key = decoded[:32] 
            try: signature = bytes.fromhex(signature_hex)
            except ValueError: return False 
                
            message = challenge_hex.encode('utf-8')
            nacl.bindings.crypto_sign_open(signature + message, public_key)
            return True
        except Exception:
            return False

    def _handle_incoming_target(self, requested_connection):
        auth_successful = False
        remote_identity = None
        message = None

        try:
            requested_connection.settimeout(10)
            challenge = secrets.token_hex(32)
            requested_connection.sendall(f"/challenge {challenge}\n".encode())
            
            data = requested_connection.recv(2048)
            if data:
                decoded_data = data.decode().strip()
                if decoded_data.startswith("/auth "):
                    parts = decoded_data.split(" ")
                    if len(parts) == 3:
                        remote_onion = parts[1]
                        signature = parts[2]
                        if self._verify_signature(remote_onion, challenge, signature):
                            remote_identity = remote_onion
                            auth_successful = True
                        else: message = f"Invalid signature from \"{remote_onion}\""
                    else: message = "Malformed /auth format"
                else: message = "Did not receive /auth command"
            else: message = "Remote peer closed connection during handshake"
                
        except Exception:
            message = "Handshake failed"

        if not auth_successful:
            self._log_failed(remote_identity, reason=message)
            requested_connection.close()
            return

        requested_connection.settimeout(None) 
        alias = self.contacts.get_alias_by_onion(remote_identity)

        with self._connection_lock:
            if alias in self._connections or alias in self._pending_connections:
                requested_connection.sendall(f"/reject {self.tor.onion}\n".encode())
                requested_connection.close()
                return
            self._pending_connections[alias] = requested_connection

        self._log_request(remote_identity, remote=True)

    def start_listener(self):
        threading.Thread(target=self._start_listener_target, daemon=True).start()

    def _start_listener_target(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', self.tor.incoming_port))
        listener.listen(5)
        while not self.stop_flag.is_set():
            try:
                listener.settimeout(1)
                requested_connection, _ = listener.accept()
            except socket.timeout: continue
            except Exception: continue
            threading.Thread(target=self._handle_incoming_target, args=(requested_connection,), daemon=True).start()
        listener.close()

    def _start_receiving_thread(self, alias, conn):
        threading.Thread(target=self._receiver_target, args=(alias, conn), daemon=True).start()

    def _receiver_target(self, initial_alias, conn):
        rejected = False
        try:
            while True:
                data = conn.recv(1024)
                if not data: break

                current_alias = initial_alias
                with self._connection_lock:
                    for k, v in self._connections.items():
                        if v == conn:
                            current_alias = k
                            break
                    if current_alias == initial_alias:
                        for k, v in self._pending_connections.items():
                            if v == conn:
                                current_alias = k
                                break

                raw_msgs = data.decode().strip().split("\n")
                for msg in raw_msgs:
                    msg = msg.strip()
                    if not msg: continue
        
                    if msg == "/accepted":
                        with self._connection_lock:
                            if current_alias in self._pending_connections:
                                self._pending_connections.pop(current_alias)
                            self._connections[current_alias] = conn
                        self._set_focused_alias(current_alias)
                        self._log_connect(current_alias)
                        
                    elif msg.startswith("/disconnect "): raise Exception() 
                    elif msg.startswith("/reject "):
                        rejected = True
                        raise Exception()
                        
                    elif msg.startswith("/ack "):
                        parts = msg.split(" ")
                        if len(parts) == 2:
                            msg_id = parts[1]
                            self.cli.mark_acked(msg_id)
                                
                    elif msg.startswith("/msg "):
                        parts = msg.split(" ", 2)
                        if len(parts) == 3:
                            msg_id = parts[1]
                            content = parts[2]
                            try: conn.sendall(f"/ack {msg_id}\n".encode())
                            except Exception: pass    
                            
                            self.cli.print_message(content, msg_type="remote", alias=current_alias)
        except Exception:
            pass

        final_alias = initial_alias
        with self._connection_lock:
            for k, v in list(self._connections.items()) + list(self._pending_connections.items()):
                if v == conn:
                    final_alias = k
                    break
                    
        self.disconnect(final_alias, initiated_by_self=False, rejected=rejected)

    def disconnect_active(self):
        if self._focused_alias:
            self.disconnect(self._focused_alias, initiated_by_self=True)

    def disconnect_all(self):
        with self._connection_lock:
            aliases = list(self._connections.keys()) + list(self._pending_connections.keys())
        for alias in aliases:
            self.disconnect(alias, initiated_by_self=True)

    def disconnect(self, alias, initiated_by_self=True, rejected=False):
        conn = None
        with self._connection_lock:
            if alias in self._connections: conn = self._connections.pop(alias)
            elif alias in self._pending_connections: conn = self._pending_connections.pop(alias)
            else: return

            if self._focused_alias == alias:
                self._focused_alias = next(iter(self._connections)) if self._connections else None
                
        self.cli.set_focus(self._focused_alias)

        if initiated_by_self and conn:
            try: conn.sendall(f"/disconnect {self.tor.onion}\n".encode())
            except Exception: pass

        if conn:
            try: conn.close()
            except Exception: pass

        if rejected: self._log_reject(alias, remote=True)
        else: self._log_disconnect(alias, remote=not initiated_by_self)
    
    def send_message(self, msg):
        with self._connection_lock:
            if not self._focused_alias or self._focused_alias not in self._connections:
                self.cli.print_message("No active connection to send to.", msg_type="system")
                return
            conn = self._connections[self._focused_alias]
            
        try:
            msg_id = secrets.token_hex(4)
            formatted_msg = f"/msg {msg_id} {msg}\n".encode()
            conn.sendall(formatted_msg)
            self.cli.print_message(msg, msg_type="self", alias=self._focused_alias, msg_id=msg_id)
        except Exception:
            self.cli.print_message("Error sending message.", msg_type="system")

    def connect(self, target):
        self.cli.start_loading("Connecting...", show_prompt=True)
        self._establish_connection(target)
        self.cli.end_loading()
        
    def _establish_connection(self, target):
        alias, onion = self._resolve_target(target)
            
        if onion == self.tor.onion:
            self.cli.print_message("Cannot connect to yourself.", msg_type="system")
            return

        with self._connection_lock:
            if alias in self._connections:
                self._set_focused_alias(alias)
                self.cli.print_message('Already connected. Switched focus to {alias}.', msg_type="info", alias=alias)
                return
                
        try: conn = self.tor.connect(onion)
        except Exception:
            self._log_failed(onion, reason="Failed to connect via Tor")
            return 
        
        message = None
        try:
            conn.settimeout(10)
            data = conn.recv(1024)
            if not data: raise Exception()
                
            decoded_data = data.decode().strip()
            if not decoded_data.startswith("/challenge "): raise Exception()
                
            challenge = decoded_data.split(" ")[1]
            signature = self._sign_challenge(challenge)
            if signature is None:
                message = "Metor secret key file not found or failed to sign challenge"
                raise Exception()
            conn.sendall(f"/auth {self.tor.onion} {signature}\n".encode())
            conn.settimeout(None)
        except Exception:
            self._log_failed(onion, reason=message or "Handshake failed")
            conn.close()
            return
            
        self._log_request(onion)
        self._start_receiving_thread(alias, conn)

    def is_connected(self):
        with self._connection_lock: return len(self._connections) > 0

    def accept_connection(self, alias):
        conn = None
        with self._connection_lock:
            if alias not in self._pending_connections:
                self.cli.print_message(f'No pending connection from "{alias}".', msg_type="system")
                return
            conn = self._pending_connections.pop(alias)
            self._connections[alias] = conn

        self._set_focused_alias(alias)
        try: conn.sendall(b"/accepted\n")
        except Exception: pass

        self._log_connect(alias)
        self._start_receiving_thread(alias, conn)

    def reject_connection(self, alias):
        conn = None
        with self._connection_lock:
            if alias not in self._pending_connections:
                self.cli.print_message(f'No pending connection from "{alias}".', msg_type="system")
                return
            conn = self._pending_connections.pop(alias)
            
        try: conn.sendall(f"/reject {self.tor.onion}\n".encode())
        except Exception: pass
        finally: conn.close()

        self._log_reject(alias)

    def switch_focus(self, alias):
        with self._connection_lock: exists = alias in self._connections
        if exists:
            self._set_focused_alias(alias)
            self.cli.print_message('Switched focus to {alias}.', msg_type="info", alias=alias)
        else:
            self.cli.print_message(f'No active connection with "{alias}".', msg_type="system")

    def rename_alias(self, old_alias, new_alias):
        success = False
        with self._connection_lock:
            success = self.contacts.rename_contact(old_alias, new_alias)
            if success:
                if old_alias in self._connections:
                    self._connections[new_alias] = self._connections.pop(old_alias)
                if old_alias in self._pending_connections:
                    self._pending_connections[new_alias] = self._pending_connections.pop(old_alias)
                    
                if self._focused_alias == old_alias:
                    self._focused_alias = new_alias
                    
        if success:
            self.cli.rename_alias_in_history(old_alias, new_alias)
            history_updated = self.history.update_alias(old_alias, new_alias)

            self.cli.print_message(f'Renamed "{old_alias}" to "{new_alias}".', msg_type="system")   
            if not history_updated:
                self.cli.print_message(f"{Settings.RED}Note:{Settings.RESET} The history log did not update.", msg_type="system")
    
            self.cli.set_focus(self._focused_alias)
        else:
            self.cli.print_message("Failed to rename. Check if old alias exists and new alias is free.", msg_type="system")
