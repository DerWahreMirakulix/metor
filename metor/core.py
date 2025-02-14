import os
import time
import socket
import threading
import sys
import platform

import stem.process
import socks

from metor.config import get_hidden_service_dir
from metor.history import log_event

# Global ports (set when starting Tor)
socks_port = None
incoming_port = None

def get_free_port():
    """Return a free port number on localhost."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def start_tor():
    """
    Start a Tor process using the persistent hidden-service directory.
    Returns (tor_process, own_onion)
    """
    hs_dir = get_hidden_service_dir()
    global socks_port, incoming_port
    socks_port = get_free_port()
    control_port = get_free_port()
    incoming_port = get_free_port()
    config = {
        'SocksPort': str(socks_port),
        'ControlPort': str(control_port),
        'HiddenServiceDir': hs_dir,
        'HiddenServicePort': f'80 127.0.0.1:{incoming_port}'
    }
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    # Select the appropriate Tor binary based on OS.
    if os.name == "nt":
        tor_cmd = os.path.join(pkg_dir, "tor.exe")
    else:
        tor_cmd = "tor"  # Assumes 'tor' is installed and in the PATH on Linux/Mac
    print("Starting Tor process (this may take a few seconds)...")
    tor_proc = stem.process.launch_tor_with_config(
        config=config,
        timeout=90,
        take_ownership=True,
        tor_cmd=tor_cmd
    )
    hostname_file = os.path.join(hs_dir, "hostname")
    for _ in range(10):
        if os.path.exists(hostname_file):
            break
        time.sleep(1)
    if os.path.exists(hostname_file):
        with open(hostname_file, "r") as f:
            own_onion = f.read().strip()
    else:
        own_onion = "unknown"
    return tor_proc, own_onion

def stop_tor(tor_proc):
    tor_proc.terminate()

def connect_via_tor(onion):
    """
    Connect to a remote onion address via Tor's SOCKS proxy.
    """
    s = socks.socksocket()
    s.set_proxy(proxy_type=socks.SOCKS5, addr='127.0.0.1', port=socks_port)
    s.settimeout(10)
    s.connect((onion, 80))
    return s

def start_listener(chat_manager):
    """
    Listener thread: waits on the incoming port and accepts connections.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', incoming_port))
    listener.listen(5)
    while not chat_manager.stop_flag.is_set():
        try:
            listener.settimeout(1.0)
            conn, addr = listener.accept()
        except socket.timeout:
            continue
        except Exception:
            continue
        threading.Thread(target=handle_incoming, args=(conn, chat_manager), daemon=True).start()
    listener.close()

def handle_incoming(conn, chat_manager):
    """
    Handle an incoming connection. If already in a chat, reject it.
    Otherwise, read the initial identity message.
    """
    with chat_manager.connection_lock:
        if chat_manager.active_connection is not None:
            try:
                conn.settimeout(5.0)
                try:
                    data = conn.recv(1024)
                    identity = data.decode().strip() if data else "anonymous"
                except:
                    identity = "anonymous"
                rejection_msg = f"/reject {chat_manager.own_onion}\n".encode()
                conn.sendall(rejection_msg)
                print(f"-- {identity} incoming - rejected --")
                log_event("in", "rejected", identity)
            except:
                pass
            conn.close()
            return
        chat_manager.active_connection = conn
    try:
        conn.settimeout(5.0)
        data = conn.recv(1024)
        if data and data.decode().startswith("/init "):
            remote_identity = data.decode().strip()[6:].strip()
        else:
            remote_identity = "anonymous"
    except:
        remote_identity = "anonymous"
    with chat_manager.connection_lock:
        chat_manager.active_remote_identity = remote_identity
    print(f"-- connected with {remote_identity} --")
    log_event("in", "connected", remote_identity)
    chat_manager.start_receiving_thread()

class ChatManager:
    def __init__(self, own_onion, tor_process):
        self.own_onion = own_onion
        self.tor_process = tor_process
        self.active_connection = None
        self.active_remote_identity = None
        self.connection_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.receiver_thread = None

    def start_receiving_thread(self):
        self.receiver_thread = threading.Thread(target=self.receiver_loop, daemon=True)
        self.receiver_thread.start()

    def receiver_loop(self):
        conn = self.active_connection
        if not conn:
            return
        try:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                msg = data.decode().strip()
                if msg.startswith("/disconnect "):
                    identity = msg[len("/disconnect "):].strip()
                    print(f"-- {identity} disconnected --")
                    break
                elif msg.startswith("/reject "):
                    continue
                else:
                    print(f"{self.active_remote_identity}: {msg}")
        except:
            pass
        with self.connection_lock:
            self.active_connection = None
            self.active_remote_identity = None
        log_event("in", "disconnected", self.own_onion)
        print("-- disconnected --")

    def disconnect_active(self, initiated_by_self=True):
        with self.connection_lock:
            if self.active_connection:
                try:
                    if initiated_by_self:
                        msg = f"/disconnect {self.own_onion}\n".encode()
                        self.active_connection.sendall(msg)
                    self.active_connection.close()
                except:
                    pass
                self.active_connection = None
                self.active_remote_identity = None

    def send_message(self, msg):
        with self.connection_lock:
            if self.active_connection:
                try:
                    self.active_connection.sendall((msg + "\n").encode())
                except Exception:
                    print("Error sending message.")

    def is_connected(self):
        with self.connection_lock:
            return self.active_connection is not None

    def outgoing_connect(self, onion, anonymous=False):
        if onion == self.own_onion:
            print("Error: Cannot connect to yourself.")
            return
        with self.connection_lock:
            if self.active_connection is not None:
                print("-- already connected --")
                return
        try:
            conn = connect_via_tor(onion)
        except Exception:
            print("-- rejected --")
            log_event("out", "rejected", onion)
            return
        with self.connection_lock:
            self.active_connection = conn
        identity_to_send = "anonymous" if anonymous else self.own_onion
        try:
            conn.sendall(f"/init {identity_to_send}\n".encode())
        except Exception:
            print("-- rejected --")
            log_event("out", "rejected", onion)
            with self.connection_lock:
                self.active_connection = None
            return
        with self.connection_lock:
            self.active_remote_identity = onion  # For outgoing, we assume remote identity is the onion
        print(f"-- connected with {identity_to_send} --")
        log_event("out", "connected", onion if not anonymous else "anonymous")
        self.start_receiving_thread()

def run_chat_mode():
    """
    Run the interactive chat mode.

    Top-level commands (run at metor> prompt):
      - /connect [onion] [--anonymous/-a] : Connect to a remote peer.
      - /end                             : Disconnect the current chat.
      - /clear                           : Clear the chat display.
      - /exit                            : Exit chat mode.
      - (Any other text is sent as a chat message.)

    When a connection is established, the connector always sends its identity (or "anonymous"),
    and the receiver prints: "-- connected with [onion] --" (or "anonymous" as applicable).

    If an incoming connection is received while a chat is active, it is rejected with:
      "-- [onion or anonymous] incoming - rejected --"
    """
    tor_proc, own_onion = start_tor()
    print(f"Your onion address: {own_onion}")
    chat_manager = ChatManager(own_onion, tor_proc)
    listener = threading.Thread(target=start_listener, args=(chat_manager,), daemon=True)
    listener.start()
    initial_help = (
        "Chat mode commands:\n"
        "  /connect [onion] [--anonymous/-a]   Connect to a remote peer\n"
        "  /end                                End the current connection\n"
        "  /clear                              Clear the chat display\n"
        "  /exit                               Exit chat mode\n"
    )
    print(initial_help)
    try:
        while True:
            user_input = input("metor> ").strip()
            if user_input.startswith("/connect"):
                parts = user_input.split()
                if len(parts) < 2:
                    print("Usage: /connect [onion] [--anonymous/-a]")
                    continue
                onion = parts[1]
                anonymous = ("--anonymous" in parts or "-a" in parts)
                if onion == own_onion:
                    print("Error: Cannot connect to yourself.")
                    continue
                if chat_manager.is_connected():
                    print("-- already connected --")
                else:
                    chat_manager.outgoing_connect(onion, anonymous)
            elif user_input == "/end":
                if chat_manager.is_connected():
                    chat_manager.disconnect_active(initiated_by_self=True)
                    print("-- disconnected --")
                    log_event("out", "disconnected", chat_manager.own_onion)
                else:
                    print("No active connection.")
            elif user_input == "/clear":
                # Clear the screen and reprint the initial help text and connection status
                os.system('cls' if os.name == 'nt' else 'clear')
                print(initial_help)
                if chat_manager.is_connected():
                    print(f"-- connected with {chat_manager.active_remote_identity} --")
            elif user_input == "/exit":
                if chat_manager.is_connected():
                    chat_manager.disconnect_active(initiated_by_self=True)
                    print("-- disconnected --")
                    log_event("out", "disconnected", chat_manager.own_onion)
                chat_manager.stop_flag.set()
                break
            else:
                if chat_manager.is_connected():
                    chat_manager.send_message(user_input)
                else:
                    print("No active connection. Use /connect to initiate a connection.")
    except KeyboardInterrupt:
        if chat_manager.is_connected():
            chat_manager.disconnect_active(initiated_by_self=True)
            print("-- disconnected --")
            log_event("out", "disconnected", chat_manager.own_onion)
        chat_manager.stop_flag.set()
    stop_tor(tor_proc)
