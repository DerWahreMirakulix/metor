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


def get_free_port():
    """Return a free port number on localhost."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_tor():
    """
    Start a Tor process using a persistent hidden-service directory.
    Returns (tor_proc, own_onion, socks_port, incoming_port).
    """
    hs_dir = get_hidden_service_dir()
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
    tor_cmd = os.path.join(pkg_dir, "tor.exe") if os.name == "nt" else "tor"
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
    return tor_proc, own_onion, socks_port, incoming_port


def stop_tor(tor_proc):
    """Terminate the Tor process."""
    tor_proc.terminate()


def connect_via_tor(socks_port, onion):
    """
    Connect to a remote onion address via Tor's SOCKS proxy.
    Returns the connected socket.
    """
    s = socks.socksocket()
    s.set_proxy(proxy_type=socks.SOCKS5, addr='127.0.0.1', port=socks_port)
    s.settimeout(10)
    s.connect((onion, 80))
    s.settimeout(None)
    return s


def start_listener(chat_manager, incoming_port):
    """
    Listen for incoming connections on the designated port.
    Spawns a new thread for each incoming connection.
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
    Handle an incoming connection. If a chat is already active, reject the new one.
    Otherwise, process the initial /init message.
    """
    with chat_manager.connection_lock:
        if chat_manager.active_connection is not None:
            try:
                conn.settimeout(5)
                try:
                    data = conn.recv(1024)
                    identity = data.decode().strip() if data else "anonymous"
                except Exception:
                    identity = "anonymous"
                rejection_msg = f"/reject {chat_manager.own_onion}\n".encode()
                conn.sendall(rejection_msg)
                print_message(f"info> {identity} incoming - rejected", cli=chat_manager.cli)
                log_event("in", "rejected", identity)
            except Exception:
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
    except Exception:
        remote_identity = "anonymous"
    conn.settimeout(None)
    with chat_manager.connection_lock:
        chat_manager.active_remote_identity = remote_identity
    print_message(f"info> connected with {remote_identity}", cli=chat_manager.cli)
    log_event("in", "connected", remote_identity)
    chat_manager.start_receiving_thread()


def print_message(msg, cli=None, skip_prompt=False):
    """
    Print a message to the console with colored prefixes.
    If a CommandLineInput instance (cli) is provided, the current prompt and input are reprinted.
    """
    GREEN, BLUE, YELLOW, RESET = "\033[32m", "\033[34m", "\033[33m", "\033[0m"
    sys.stdout.write("\r\033[K")
    if msg.startswith("self>"):
        msg = msg.replace("self>", f"{GREEN}self>{RESET}", 1)
    elif msg.startswith("other>"):
        msg = msg.replace("other>", f"{BLUE}other>{RESET}", 1)
    elif msg.startswith("info>"):
        msg = msg.replace("info>", f"{YELLOW}info>{RESET}", 1)
    sys.stdout.write(msg + "\n")
    if not skip_prompt and cli is not None:
        sys.stdout.write(cli.prompt + cli.current_input)
        sys.stdout.flush()


class CommandLineInput:
    """
    Handles non-blocking input with command history and arrow-key navigation.
    """
    def __init__(self, prompt="> "):
        self.prompt = prompt
        self.command_history = []
        self.history_index = -1
        self.current_input = ""

    def get_char(self):
        """Return a single character or a special marker if an arrow key is pressed."""
        if os.name == 'nt':
            import msvcrt
            if msvcrt.kbhit():
                ch = msvcrt.getwch()  # Unicode version (does not echo)
                if ch in ("\x00", "\xe0"):
                    ch2 = msvcrt.getwch()
                    if ch2 == "H":
                        return "SPECIAL:UP"
                    elif ch2 == "P":
                        return "SPECIAL:DOWN"
                    elif ch2 == "K":
                        return "SPECIAL:LEFT"
                    elif ch2 == "M":
                        return "SPECIAL:RIGHT"
                    else:
                        return ""
                return ch
            return None
        else:
            import termios, tty
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                dr, _, _ = select.select([sys.stdin], [], [], 0)
                if dr:
                    ch = sys.stdin.read(1)
                    if ch == "\x1b":
                        if select.select([sys.stdin], [], [], 0)[0]:
                            ch2 = sys.stdin.read(1)
                            if ch2 == "[":
                                if select.select([sys.stdin], [], [], 0)[0]:
                                    ch3 = sys.stdin.read(1)
                                    if ch3 == "A":
                                        return "SPECIAL:UP"
                                    elif ch3 == "B":
                                        return "SPECIAL:DOWN"
                                    elif ch3 == "D":
                                        return "SPECIAL:LEFT"
                                    elif ch3 == "C":
                                        return "SPECIAL:RIGHT"
                                    else:
                                        return ""
                    return ch
                return None
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def read_line(self):
        """
        Read a line non-blockingly while handling arrow keys and history.
        Returns the completed input line.
        """
        line_chars = []
        cursor_index = 0

        def render_line():
            line_str = ''.join(line_chars)
            sys.stdout.write("\r\033[K" + self.prompt + line_str)
            if cursor_index < len(line_chars):
                move_left = len(line_chars) - cursor_index
                sys.stdout.write(f"\033[{move_left}D")
            sys.stdout.flush()

        while True:
            ch = self.get_char()
            if ch is None:
                time.sleep(0.05)
                continue

            if ch.startswith("SPECIAL:"):
                key = ch.split(":")[1]
                if key == "UP":
                    if self.command_history and self.history_index < len(self.command_history) - 1:
                        self.history_index += 1
                        new_line = self.command_history[-(self.history_index + 1)]
                    else:
                        new_line = self.command_history[0] if self.command_history else ""
                    line_chars = list(new_line)
                    cursor_index = len(line_chars)
                    self.current_input = new_line
                    render_line()
                    continue
                elif key == "DOWN":
                    if self.history_index > 0:
                        self.history_index -= 1
                        new_line = self.command_history[-(self.history_index + 1)]
                    else:
                        self.history_index = -1
                        new_line = ""
                    line_chars = list(new_line)
                    cursor_index = len(line_chars)
                    self.current_input = new_line
                    render_line()
                    continue
                elif key == "LEFT":
                    if cursor_index > 0:
                        cursor_index -= 1
                    render_line()
                    continue
                elif key == "RIGHT":
                    if cursor_index < len(line_chars):
                        cursor_index += 1
                    render_line()
                    continue
                else:
                    continue

            if ch in ("\n", "\r"):
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()
                line = ''.join(line_chars)
                if line.strip().startswith("/"):
                    self.command_history.append(line)
                self.history_index = -1
                self.current_input = ""
                return line

            elif ch in ("\b", "\x7f"):
                if cursor_index > 0:
                    del line_chars[cursor_index - 1]
                    cursor_index -= 1
                render_line()
                self.current_input = ''.join(line_chars)
                continue

            else:
                line_chars.insert(cursor_index, ch)
                cursor_index += 1
                render_line()
                self.current_input = ''.join(line_chars)


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
                    print_message("other> " + msg, cli=self.cli)
        except Exception:
            pass
        with self.connection_lock:
            remote_identity = self.active_remote_identity
            self.active_connection = None
            self.active_remote_identity = None
        if not self.user_initiated_disconnect:
            print_message("info> disconnected", cli=self.cli)
            log_event("in", "disconnected", remote_identity)

    def disconnect_active(self, initiated_by_self=True):
        remote_identity = None
        with self.connection_lock:
            if self.active_connection:
                remote_identity = self.active_remote_identity
                if initiated_by_self:
                    self.user_initiated_disconnect = True
                    try:
                        msg = f"/disconnect {self.own_onion}\n".encode()
                        self.active_connection.sendall(msg)
                    except Exception:
                        pass
                try:
                    self.active_connection.close()
                except Exception:
                    pass
                self.active_connection = None
                self.active_remote_identity = None
        return remote_identity

    def send_message(self, msg):
        with self.connection_lock:
            if self.active_connection:
                try:
                    self.active_connection.sendall((msg + "\n").encode())
                except Exception:
                    print_message("info> Error sending message.", cli=self.cli)

    def is_connected(self):
        with self.connection_lock:
            return self.active_connection is not None

    def outgoing_connect(self, onion, anonymous=False):
        if onion == self.own_onion:
            print_message("info> Error: Cannot connect to yourself.", cli=self.cli)
            return
        with self.connection_lock:
            if self.active_connection is not None:
                print_message("info> already connected", cli=self.cli)
                return
        try:
            conn = connect_via_tor(self.socks_port, onion)
        except Exception:
            print_message("info> rejected", cli=self.cli)
            log_event("out", "rejected", onion)
            return
        with self.connection_lock:
            self.active_connection = conn
        identity_to_send = "anonymous" if anonymous else self.own_onion
        try:
            conn.sendall(f"/init {identity_to_send}\n".encode())
        except Exception:
            print_message("info> rejected", cli=self.cli)
            log_event("out", "rejected", onion)
            with self.connection_lock:
                self.active_connection = None
            return
        with self.connection_lock:
            self.active_remote_identity = onion  # For outgoing, assume remote identity is the onion.
        print_message(f"info> connected with {onion}", cli=self.cli)
        log_event("out", "connected", onion)
        self.start_receiving_thread()


def run_chat_mode():
    """
    Main interactive chat loop.
    Commands:
      - /connect [onion] [--anonymous/-a] : Connect to a remote peer.
      - /end                             : Disconnect the current chat.
      - /clear                           : Clear the chat display.
      - /exit                            : Exit chat mode.
      - All other text is sent as a chat message.
    """
    cli = CommandLineInput(prompt="> ")
    chat_manager = None
    tor_proc = None

    try:
        tor_proc, own_onion, socks_port, incoming_port = start_tor()
        print(f"Your onion address: {own_onion}")
        chat_manager = ChatManager(own_onion, tor_proc, socks_port, incoming_port, cli)
        listener_thread = threading.Thread(target=start_listener, args=(chat_manager, incoming_port), daemon=True)
        listener_thread.start()

        initial_help = (
            "Chat mode commands:\n"
            "  /connect [onion] [--anonymous/-a]   Connect to a remote peer\n"
            "  /end                                End the current connection\n"
            "  /clear                              Clear the chat display\n"
            "  /exit                               Exit chat mode\n"
        )
        print(initial_help)
        print(cli.prompt, end="")
        
        while True:
            user_input = cli.read_line()
            if user_input.startswith("/connect"):
                parts = user_input.split()
                if len(parts) < 2:
                    print_message("info> Usage: /connect [onion] [--anonymous/-a]", cli=cli)
                    continue
                onion = parts[1]
                anonymous = ("--anonymous" in parts or "-a" in parts)
                if onion == own_onion:
                    print_message("info> Error: Cannot connect to yourself.", cli=cli)
                    continue
                if chat_manager.is_connected():
                    print_message("info> already connected", cli=cli)
                else:
                    chat_manager.outgoing_connect(onion, anonymous)
            elif user_input == "/end":
                if chat_manager.is_connected():
                    remote_identity = chat_manager.disconnect_active(initiated_by_self=True)
                    print_message("info> disconnected", cli=cli)
                    log_event("out", "disconnected", remote_identity)
                else:
                    print_message("info> No active connection.", cli=cli)
            elif user_input == "/clear":
                os.system('cls' if os.name == 'nt' else 'clear')
                print(initial_help)
                print(cli.prompt, end="")
                if chat_manager.is_connected():
                    print_message(f"info> connected with {chat_manager.active_remote_identity}", cli=cli)
            elif user_input == "/exit":
                if chat_manager.is_connected():
                    remote_identity = chat_manager.disconnect_active(initiated_by_self=True)
                    print_message("info> disconnected", cli=cli, skip_prompt=True)
                    log_event("out", "disconnected", remote_identity)
                chat_manager.stop_flag.set()
                break
            else:
                if chat_manager.is_connected():
                    chat_manager.send_message(user_input)
                    print_message("self> " + user_input, cli=cli)
                else:
                    print_message("info> No active connection. Use /connect to initiate a connection.", cli=cli)
    except KeyboardInterrupt:
        if chat_manager:
            if chat_manager.is_connected():
                remote_identity = chat_manager.disconnect_active(initiated_by_self=True)
                print_message("info> disconnected", cli=cli, skip_prompt=True)
                log_event("out", "disconnected", remote_identity)
            else:
                sys.stdout.write("\r\033[K")
                sys.stdout.flush()
            chat_manager.stop_flag.set()
    finally:
        if tor_proc:
            stop_tor(tor_proc)
