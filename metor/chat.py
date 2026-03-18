import socket
import threading
import secrets
import base64
import binascii
import os
import nacl.bindings
import subprocess

from metor.config import chat_help, get_metor_key
from metor.history import log_event
from metor.tor import start_tor, stop_tor, connect_via_tor
from metor.cli import CommandLineInput

def run_chat_mode():
    """
    Main interactive chat loop.
    Commands:
      - /connect [onion]                 : Connect to a remote peer.
      - /end                             : Disconnect the current chat.
      - /clear                           : Clear the chat display.
      - /exit                            : Exit chat mode.
      - All other text is sent as a chat message.
    """
    cli = CommandLineInput(prompt="> ")
    chat_manager = None
    tor_proc = None

    try:
        cli.start_loading("Starting Tor process (this may take a few seconds)...")
        tor_proc, own_onion, socks_port, incoming_port = start_tor()
        cli.end_loading()

        if not tor_proc:
            cli.print_message("info> Failed to start Tor.")
            return

        chat_manager = ChatManager(own_onion, tor_proc, socks_port, incoming_port, cli)
        chat_manager.start_listener()

        chat_manager.print_onion()
        cli.print_prompt()
        
        while True:
            user_input = cli.read_line()
            if user_input == "":
                cli.print_prompt()
            elif user_input.startswith("/connect"):
                parts = user_input.split()
                if len(parts) < 2:
                    cli.print_message("info> Usage: \"/connect [onion]\".")
                    continue
                onion = parts[1]
                cli.start_loading()
                chat_manager.outgoing_connect(onion)
                cli.end_loading()
            elif user_input == "/end":
                if chat_manager.is_connected():
                    chat_manager.disconnect_active()
                else:
                    cli.print_message("info> No active connection.")
            elif user_input == "/clear":
                subprocess.run('cls' if os.name == 'nt' else 'clear', shell=True)
                chat_manager.print_onion()
                cli.print_prompt()
                if chat_manager.is_connected():
                    cli.print_message(f"info> connected with \"{chat_manager.active_remote_identity}\".")
            elif user_input == "/exit":
                if chat_manager.is_connected():
                    chat_manager.disconnect_active()
                chat_manager.stop_flag.set()
                break
            else:
                if chat_manager.is_connected():
                    chat_manager.send_message(user_input)
                else:
                    cli.print_message("info> No active connection. Use /connect to initiate a connection.")
    except KeyboardInterrupt:
        if chat_manager:
            if chat_manager.is_connected():
                chat_manager.disconnect_active()
            else:
                cli.clear_line()
            chat_manager.stop_flag.set()
    finally:
        if tor_proc:
            stop_tor(tor_proc)

class ChatManager:
    """
    Manages the chat connection, sending/receiving messages, and connection state.
    """
    def __init__(self, own_onion, tor_process, socks_port, incoming_port, cli):
        self.own_onion = own_onion
        self.tor_process = tor_process
        self.socks_port = socks_port
        self.incoming_port = incoming_port
        self.cli = cli

        self.active_connection = None
        self.requested_connection = None
        self.connection_direction = None
        self.active_remote_identity = None 
        self.connection_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.receiver_thread = None
        self.user_initiated_disconnect = False

    def _log_reject(self, direction, acting_peer, onion="unknown", reason=""):
        """
        Log a rejected connection.
        - direction: "in" or "out"
        - acting_peer: "self" or "remote"
        - onion: the identity (onion address)
        - reason: the reason for rejection
        """
        self.cli.print_message(f"info> connection {"from" if direction == "in" else "to"} \"{onion}\" rejected by {"remote peer" if acting_peer == "remote" else "self"}{f': "{reason}"' if reason else ''}.")
        log_event(acting_peer, "rejected", onion, reason)

    def _log_connect(self, direction, acting_peer, onion="unknown"):
        """
        Log a successful connection.
        - direction: "in" or "out"
        - acting_peer: "self" or "remote"
        - onion: the identity (onion address)
        """
        self.cli.print_message(f"info> connection {"from" if direction == "in" else "to"} \"{onion}\" established.")
        log_event(acting_peer, "connected", onion)

    def _log_disconnect(self, direction, acting_peer, onion="unknown"):
        """
        Log a disconnected connection.
        - direction: "in" or "out"
        - acting_peer: "self" or "remote"
        - onion: the identity (onion address)
        """
        self.cli.print_message(f"info> connection {"from" if direction == "in" else "to"} \"{onion}\" disconnected{" by remote peer" if acting_peer == "remote" else ""}.")
        log_event(acting_peer, "disconnected", onion)

    def _start_listener_target(self):
        """
        Listen for incoming connections on the designated port.
        Spawns a new thread for each incoming connection.
        """
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', self.incoming_port))
        listener.listen(5)
        while not self.stop_flag.is_set():
            try:
                listener.settimeout(1)
                self.requested_connection, _ = listener.accept()
            except socket.timeout:
                continue
            except Exception:
                continue
            threading.Thread(target=self._handle_incoming_target, daemon=True).start()
        listener.close()

    def _sign_challenge(self, challenge_hex):
        try:
            pynacl_secret_key = get_metor_key()
            
            message = challenge_hex.encode('utf-8')
            signed_message = nacl.bindings.crypto_sign(message, pynacl_secret_key)
            signature = signed_message[:64]
            
            return signature.hex()
        except FileNotFoundError:
            self.cli.print_message("info> Metor secret key file not found. Failed to sign challenge.")
            return None 
        except Exception:
            self.cli.print_message(f"info> Failed to sign challenge.")
            return None

    def _verify_signature(self, remote_onion, challenge_hex, signature_hex):
        try:
            # 1. Remove ".onion" if present, and use uppercase letters for Base32.
            onion_str = remote_onion.replace(".onion", "").upper()
            
            # Catch basic formatting errors early
            if len(onion_str) != 56:
                return False
            
            # Correct Base32 padding
            pad_len = 8 - (len(onion_str) % 8)
            if pad_len != 8:
                onion_str += "=" * pad_len
                
            # 2. Decode Base32 and extract the 32-byte public key
            try:
                decoded = base64.b32decode(onion_str)
            except binascii.Error:
                return False # Invalid Base32 alphabet
                
            public_key = decoded[:32] 
            
            # 3. Verify signature
            try:
                signature = bytes.fromhex(signature_hex)
            except ValueError:
                return False # Signature was not a valid hex string
                
            message = challenge_hex.encode('utf-8')
            
            # crypto_sign_open throws an error if the signature does not match the message/key
            nacl.bindings.crypto_sign_open(signature + message, public_key)
            
            return True
        except Exception:
            return False

    def _handle_incoming_target(self):
        """
        Handle an incoming connection. If a chat is already active, reject the new one.
        Otherwise, initiate a challenge-response authentication.
        """
        with self.connection_lock:
            # 1. If we are already busy, decline immediately (without a handshake)
            if self.active_connection is not None:
                try:
                    self.requested_connection.settimeout(5)
                    rejection_msg = f"/reject {self.own_onion}\n".encode()
                    self.requested_connection.sendall(rejection_msg)
                    self._log_reject("in", "self", reason="Busy")
                except Exception:
                    pass
                finally:
                    self.requested_connection.close()
                return
            
            # 2. Temporarily accept the connection
            self.active_connection = self.requested_connection
            self.user_initiated_disconnect = False

        # 3. Authentication handshake (Challenge-Response)
        auth_successful = False
        remote_identity = None

        try:
            self.requested_connection.settimeout(10) # 10 seconds for Tor latency
            
            # Generate and send challenge
            challenge = secrets.token_hex(32)
            challenge_msg = f"/challenge {challenge}\n".encode()
            self.requested_connection.sendall(challenge_msg)
            
            # Wait for signed response
            data = self.requested_connection.recv(2048)
            
            if data:
                decoded_data = data.decode().strip()
                if decoded_data.startswith("/auth "):
                    parts = decoded_data.split(" ")
                    
                    if len(parts) == 3:
                        remote_onion = parts[1]
                        signature = parts[2]
                        
                        # Cryptographic verification
                        if self._verify_signature(remote_onion, challenge, signature):
                            remote_identity = remote_onion
                            auth_successful = True
                        else:
                            self.cli.print_message(f"info> Invalid signature from \"{remote_onion}\".")
                    else:
                        self.cli.print_message(f"info> Malformed /auth format from \"{remote_onion}\".")
                else:
                    self.cli.print_message(f"info> Did not receive /auth command from \"{remote_onion}\".")
            else:
                self.cli.print_message(f"info> Remote \"{remote_onion}\" no longer available.")
                
        except Exception:
            # e.g., Timeout or connection drop during handshake
            self.cli.print_message("info> Connection dropped or timed out during handshake.")

        # 4. On failure: Clean up and abort
        if not auth_successful:
            self._log_reject("in", "self", reason="Handshake aborted")
            self.requested_connection.close()
            with self.connection_lock:
                self.active_connection = None
            return

        # 5. On success: Start chat
        self.requested_connection.settimeout(None) # Remove timeout for normal chat
        with self.connection_lock:
            self.active_remote_identity = remote_identity
            self.connection_direction = "in"
            
        self._log_connect("in", "remote", remote_identity)
        self._start_receiving_thread()

    def start_listener(self):
        listener_thread = threading.Thread(target=self._start_listener_target, daemon=True)
        listener_thread.start()

    def print_onion(self):
        self.cli.print_message(f"Your onion address: {self.own_onion}\n", skip_prompt=True)
        self.cli.print_message(chat_help(), skip_prompt=True)

    def _start_receiving_thread(self):
        self.receiver_thread = threading.Thread(target=self._receiver_target, daemon=True)
        self.receiver_thread.start()

    def _receiver_target(self):
        conn = self.active_connection
        if not conn:
            return
            
        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    break

                # With TCP, multiple messages can be contained within a single packet
                # Therefore, we split them at the newline character.
                raw_msgs = data.decode().strip().split("\n")
                for msg in raw_msgs:
                    msg = msg.strip()
                    if not msg:
                        continue
                    if msg.startswith("/disconnect "):
                        raise Exception() 
                    elif msg.startswith("/msg "):
                        # Format: /msg <id> <text>
                        parts = msg.split(" ", 2)
                        if len(parts) == 3:
                            msg_id = parts[1]
                            content = parts[2]

                            # Return the ACK immediately!
                            try:
                                ack_msg = f"/ack {msg_id}\n".encode()
                                conn.sendall(ack_msg)
                            except Exception:
                                pass     

                            self.cli.print_message("remote> " + content) 
                    elif msg.startswith("/ack "):
                        parts = msg.split(" ")
                        if len(parts) == 2:
                            msg_id = parts[1]
                            self.cli._update_message(msg_id)     
                    elif msg.startswith("/reject "):
                        continue  
        except Exception:
            pass

        with self.connection_lock:
            remote_identity = self.active_remote_identity
            connection_direction = self.connection_direction

            self.active_connection = None
            self.active_remote_identity = None
            self.connection_direction = None

        if not self.user_initiated_disconnect:
            self._log_disconnect(connection_direction, "remote", remote_identity)

    def disconnect_active(self):
        self.user_initiated_disconnect = True
        remote_identity = None
        connection_direction = None 

        with self.connection_lock:
            if self.active_connection:
                remote_identity = self.active_remote_identity
                connection_direction = self.connection_direction
                try:
                    disconnect_msg = f"/disconnect {self.own_onion}\n".encode()
                    self.active_connection.sendall(disconnect_msg)
                except Exception:
                    pass
        
                try:
                    self.active_connection.close()
                except Exception:
                    pass
                self.active_connection = None
                self.active_remote_identity = None
                self.connection_direction = None

        if self.receiver_thread:
            self.receiver_thread.join(timeout=1)
            self.receiver_thread = None
       
        self._log_disconnect(connection_direction, "self", remote_identity)
        self.user_initiated_disconnect = False

    def send_message(self, msg):
        with self.connection_lock:
            if self.active_connection:
                try:
                    # Generate an 8-digit hex ID
                    msg_id = secrets.token_hex(4)
                    
                    # Message format: /msg <id> <text>
                    formatted_msg = f"/msg {msg_id} {msg}\n".encode()
                    self.active_connection.sendall(formatted_msg)
                    
                    self.cli.print_message("self_pending> " + msg, msg_id=msg_id)
                except Exception:
                    self.cli.print_message("info> Error sending message.")

    def is_connected(self):
        with self.connection_lock:
            return self.active_connection is not None

    def outgoing_connect(self, onion):
        if onion == self.own_onion:
            self.cli.print_message("info> Cannot connect to yourself.")
            return

        if self.is_connected():
            self.cli.print_message("info> Already connected.")
            return
                
        try:
            conn = connect_via_tor(self.socks_port, onion)
        except Exception:
            self._log_reject("out", "self", onion, reason="Failed to connect via Tor")
            return
            
        with self.connection_lock:
            self.active_connection = conn
            self.user_initiated_disconnect = False
            
        # --- HANDSHAKE: Receive and respond to the challenge ---
        try:
            conn.settimeout(10) # 10-second buffer for the Tor network
            
            # 1. Wait for "/challenge <hex>"
            data = conn.recv(1024)
            if not data:
                self.cli.print_message(f"info> Failed to receive challenge from \"{onion}\".")
                raise Exception()
                
            decoded_data = data.decode().strip()
            if not decoded_data.startswith("/challenge "):
                self.cli.print_message(f"info> Malformed /challenge format from \"{onion}\".")
                raise Exception()
                
            challenge = decoded_data.split(" ")[1]
            
            # 2. Sign the challenge with our own private key
            signature = self._sign_challenge(challenge)
            if signature is None:
                raise Exception()
            
            # 3. Send /auth to the server
            auth_msg = f"/auth {self.own_onion} {signature}\n"
            conn.sendall(auth_msg.encode())
            
            # Remove timeout for normal chat operation
            conn.settimeout(None)
            
        except Exception:
            self._log_reject("out", "self", onion, reason=f"Handshake failed")
            conn.close()
            with self.connection_lock:
                self.active_connection = None
            return

        # If we reach this point, our sending was successful.
        # If the server rejects our signature, it simply closes the socket,
        # which our `_receiver_target` thread immediately notices and cleanly disconnects.
        with self.connection_lock:
            self.active_remote_identity = onion 
            self.connection_direction = "out" 
            
        self._log_connect("out", "self", onion)
        self._start_receiving_thread()
