import os
import time
import socket
import threading
import sys
import select

import stem.process
import socks

from metor.config import get_hidden_service_dir
from metor.history import log_event

# Global ports (set when starting Tor)
socks_port = None
incoming_port = None
current_input = None

def get_char():
    """Return a single character if available (non-blocking), else None."""
    if os.name == 'nt':
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getwch()  # Unicode version (does not echo)
            return ch
        return None
    else:
        dr, _, _ = select.select([sys.stdin], [], [], 0)
        if dr:
            return sys.stdin.read(1)
        return None

def read_line(prompt="> "):
    """
    Read a line from standard input non-blockingly.
    The prompt is printed, and each character is appended to a buffer.
    The global 'current_input' is updated with the current buffer.
    When Enter is pressed, the complete line is returned.
    """
    global current_input
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = ""
    current_input = ""
    while True:
        ch = get_char()
        if ch is None:
            time.sleep(0.05)
            continue
        if ch in ("\n", "\r"):  # Handle Enter (13, 10)
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            current_input = ""
            return line
        elif ch in ("\b", "\x7f"):  # Handle backspace (8, 127)
            line = line[:-1]
            current_input = line
            # Clear current line and reprint prompt and text.
            sys.stdout.write("\r\033[K" + prompt + line)
            sys.stdout.flush()
        else:
            line += ch
            current_input = line
            sys.stdout.write(ch)
            sys.stdout.flush()

def print_incoming_message(msg):
    global current_input
    # Clear current line
    sys.stdout.write("\r\033[K")
    sys.stdout.write(msg + "\n")
    # Reprint the prompt with current partial input
    sys.stdout.write("> " + current_input)
    sys.stdout.flush()

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
            listener.settimeout(1)
            conn, _ = listener.accept()
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
                conn.settimeout(5)
                try:
                    data = conn.recv(1024)
                    identity = data.decode().strip() if data else "anonymous"
                except:
                    identity = "anonymous"
                rejection_msg = f"/reject {chat_manager.own_onion}\n".encode()
                conn.sendall(rejection_msg)
                print(f"info> {identity} incoming - rejected")
                log_event("in", "rejected", identity)
            except:
                pass
            conn.close()
            return
        chat_manager.active_connection = conn
    try:
        conn.settimeout(5)
        data = conn.recv(1024)
        if data and data.decode().startswith("/init "):
            remote_identity = data.decode().strip()[6:].strip()
        else:
            remote_identity = "anonymous"
    except:
        remote_identity = "anonymous"
    with chat_manager.connection_lock:
        chat_manager.active_remote_identity = remote_identity
    print(f"info> connected with {remote_identity}")
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
        self.user_initiated_disconnect = False

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
                    break
                elif msg.startswith("/reject "):
                    continue
                else:
                    print_incoming_message("other> " + msg)
        except Exception:
            pass
        with self.connection_lock:
            self.active_connection = None
            self.active_remote_identity = None
        if not self.user_initiated_disconnect:
            print("info> disconnected")
            log_event("in", "disconnected", self.own_onion)

    def disconnect_active(self, initiated_by_self=True):
        with self.connection_lock:
            if self.active_connection:
                if initiated_by_self:
                    self.user_initiated_disconnect = True
                    try:
                        msg = f"/disconnect {self.own_onion}\n".encode()
                        self.active_connection.sendall(msg)
                    except:
                        pass
                try:
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
                    print("info> Error sending message.")

    def is_connected(self):
        with self.connection_lock:
            return self.active_connection is not None

    def outgoing_connect(self, onion, anonymous=False):
        if onion == self.own_onion:
            print("info> Error: Cannot connect to yourself.")
            return
        with self.connection_lock:
            if self.active_connection is not None:
                print("info> already connected")
                return
        try:
            conn = connect_via_tor(onion)
        except Exception:
            print("info> rejected")
            log_event("out", "rejected", onion)
            return
        with self.connection_lock:
            self.active_connection = conn
        identity_to_send = "anonymous" if anonymous else self.own_onion
        try:
            conn.sendall(f"/init {identity_to_send}\n".encode())
        except Exception:
            print("info> rejected")
            log_event("out", "rejected", onion)
            with self.connection_lock:
                self.active_connection = None
            return
        with self.connection_lock:
            self.active_remote_identity = onion  # For outgoing, we assume remote identity is the onion
        print(f"info> connected with {identity_to_send}")
        log_event("out", "connected", onion if not anonymous else "anonymous")
        self.start_receiving_thread()

def run_chat_mode():
    """
    Run the interactive chat mode.

    Top-level commands (entered by the user):
      - /connect [onion] [--anonymous/-a] : Connect to a remote peer.
      - /end                             : Disconnect the current chat.
      - /clear                           : Clear the chat display.
      - /exit                            : Exit chat mode.
      - (Any other text is sent as a chat message.)

    A newline is printed before any connected message.
    Incoming messages are prefixed with "other>".
    No input prompt is printed.
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
            user_input = read_line("> ")
            if user_input.startswith("/connect"):
                parts = user_input.split()
                if len(parts) < 2:
                    print("info> Usage: /connect [onion] [--anonymous/-a]")
                    continue
                onion = parts[1]
                anonymous = ("--anonymous" in parts or "-a" in parts)
                if onion == own_onion:
                    print("info> Error: Cannot connect to yourself.")
                    continue
                if chat_manager.is_connected():
                    print("info> already connected")
                else:
                    chat_manager.outgoing_connect(onion, anonymous)
            elif user_input == "/end":
                if chat_manager.is_connected():
                    chat_manager.disconnect_active(initiated_by_self=True)
                    print("info> disconnected")
                    log_event("out", "disconnected", chat_manager.own_onion)
                else:
                    print("info> No active connection.")
            elif user_input == "/clear":
                os.system('cls' if os.name == 'nt' else 'clear')
                print(initial_help)
                if chat_manager.is_connected():
                    print(f"info> connected with {chat_manager.active_remote_identity}")
            elif user_input == "/exit":
                if chat_manager.is_connected():
                    chat_manager.disconnect_active(initiated_by_self=True)
                    print("info> disconnected")
                    log_event("out", "disconnected", chat_manager.own_onion)
                chat_manager.stop_flag.set()
                break
            else:
                if chat_manager.is_connected():
                    chat_manager.send_message(user_input)
                    sys.stdout.write("\r\033[Kself> " + user_input + "\n")
                    sys.stdout.flush()
                else:
                    print("info> No active connection. Use /connect to initiate a connection.")
    except KeyboardInterrupt:
        if chat_manager.is_connected():
            chat_manager.disconnect_active(initiated_by_self=True)
            print("info> disconnected")
            log_event("out", "disconnected", chat_manager.own_onion)
        chat_manager.stop_flag.set()
    stop_tor(tor_proc)
