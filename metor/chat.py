import socket
import threading
import secrets
import json
import os

from metor.help import Help
from metor.profile import ProfileManager
from metor.cli import CommandLineInput
from metor.contact import ContactManager
from metor.history import HistoryManager
from metor.settings import Settings
from metor.utils import clean_onion

class Chat:
    """The UI frontend. Connects to the local Metor Daemon via IPC."""
    
    def __init__(self, pm: ProfileManager, cm: ContactManager, hm: HistoryManager, cli: CommandLineInput):
        self.pm = pm
        self.cm = cm
        self.hm = hm
        self.cli = cli
        
        self.ipc_socket = None
        self.my_onion = "unknown"
        self._focused_alias = None 
        self._pending_focus = None

        self.stop_flag = threading.Event()
        self.init_event = threading.Event()
        self.conn_event = threading.Event()

        self.header_active = []
        self.header_pending = []

    def run(self):
        ipc_port = self.pm.get_daemon_port()
        if not ipc_port:
            self.cli.print_message("Daemon is not running! Use 'metor daemon' to start it.", msg_type="system")
            return

        try:
            self.ipc_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.ipc_socket.connect(('127.0.0.1', ipc_port))
        except Exception:
            self.cli.print_message("Could not connect to Daemon. Is it running?", msg_type="system")
            return

        threading.Thread(target=self._ipc_listener, daemon=True).start()
        
        self._send_cmd({"action": "init"})
        self.init_event.wait(timeout=2.0) 
        
        self.print_header()
            
        try:
            while True:
                user_input = self.cli.read_line()
                
                if user_input == "": 
                    self.cli.print_prompt()
                elif user_input.startswith("/"):
                    if user_input == "/clear": 
                        self.print_header(clear_screen=True)
                    elif user_input == "/connections": 
                        self._send_cmd({"action": "get_connections"})
                    elif user_input == "/exit": 
                        break
                    elif user_input.startswith("/contacts"):
                        self._handle_contacts_command(user_input.split())
                    else:
                        command_found = self._handle_network_command(user_input.split())
                        if not command_found:
                            self.cli.print_message(f"Unknown command: {user_input}", msg_type="system")
                else:
                    self._send_chat_message(user_input)
                        
        except KeyboardInterrupt:
            self.cli.clear_input_area() 
        finally:
            self._shutdown()

    def _shutdown(self):
        """Helper to safely kill all threads, close sockets and exit the UI."""
        self.stop_flag.set()
        try: self.ipc_socket.close()
        except Exception: pass
        os._exit(0)

    def _handle_network_command(self, parts):
        """Dispatches all /connect, /accept, /reject, /switch, /end commands."""
        cmd = parts[0]
        arg = parts[1].lower() if len(parts) > 1 else None

        if cmd == "/end":
            target = arg if arg else self._focused_alias
            if target: 
                self._send_cmd({"action": "disconnect", "target": target})
            else:
                self.cli.print_message("No active connection to end.", msg_type="system")
                
        elif cmd == "/connect":
            if arg: 
                alias, _ = self.cm.resolve_target(arg)
                self._pending_focus = alias
                self._send_cmd({"action": "connect", "target": arg})
            else: self.cli.print_message("Usage: \"/connect [onion/alias]\".", msg_type="system")
                
        elif cmd == "/accept":
            if arg:
                # arg is always the alias
                if self._focused_alias is None:
                    self._pending_focus = arg
                self._send_cmd({"action": "accept", "target": arg})
            else: self.cli.print_message("Usage: \"/accept [alias]\".", msg_type="system")
                
        elif cmd == "/reject":
            if arg: self._send_cmd({"action": "reject", "target": arg})
            else: self.cli.print_message("Usage: \"/reject [alias]\".", msg_type="system")
                
        elif cmd == "/switch":
            if arg:
                self.switch_focus(None if arg == ".." else arg)
            else: self.cli.print_message("Usage: \"/switch [..|alias]\".", msg_type="system")
        else:
            return False
            
        return True

    def _handle_contacts_command(self, parts):
        """Dispatches all /contacts list, add, rm, rename commands."""
        subcmd = parts[1] if len(parts) > 1 else "list"

        if subcmd == "list":
            self.cli.print_divider()
            self.cli.print_message(self.cm.show(chat_mode=True))
            self.cli.print_divider()
            
        elif subcmd == "add":
            if len(parts) < 4:
                self.cli.print_message("Usage: \"/contacts add [alias] [onion]\".", msg_type="system")
            else:
                _, msg = self.cm.add_contact(parts[2], parts[3])
                self.cli.print_message(msg, msg_type="system")
                
        elif subcmd in ("rm", "remove"):
            if len(parts) < 3:
                self.cli.print_message("Usage: \"/contacts rm [alias]\".", msg_type="system")
            else:
                _, msg = self.cm.remove_contact(parts[2])
                self.cli.print_message(msg, msg_type="system")
                
        elif subcmd == "rename":
            if len(parts) < 4:
                self.cli.print_message("Usage: \"/contacts rename [old_alias] [new_alias]\".", msg_type="system")
            else:
                self._send_cmd({"action": "rename_contact", "old_alias": parts[2].lower(), "new_alias": parts[3].lower()})
        else:
            self.cli.print_message("Usage: \"/contacts [list|add|rm|rename] ..options\".", msg_type="system")

    def _send_chat_message(self, msg_text):
        """Sends a regular text message to the focused peer."""
        if self._focused_alias:
            msg_id = secrets.token_hex(4)
            self._send_cmd({"action": "msg", "target": self._focused_alias, "text": msg_text, "msg_id": msg_id})
            self.cli.print_message(msg_text, msg_type="self", alias=self._focused_alias, msg_id=msg_id)
        else:
            self.cli.print_message("No active focus. Use /switch or /connect.", msg_type="system")

    def _send_cmd(self, cmd_dict):
        try: self.ipc_socket.sendall((json.dumps(cmd_dict) + "\n").encode())
        except Exception: pass

    def _ipc_listener(self):
        """Reads events arriving from the background Daemon."""
        buffer = ""
        try:
            while not self.stop_flag.is_set():
                data = self.ipc_socket.recv(4096)
                if not data:
                    self.cli.print_divider()
                    self.cli.print_message(f"{Settings.RED}Alert:{Settings.RESET} Connection to Daemon lost! Exiting...")
                    self.cli.clear_input_area() 
                    self._shutdown()
                
                buffer += data.decode()
                
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line: continue
                    
                    try:
                        event = json.loads(line)
                        evt_type = event.get("type")
                        
                        if evt_type == "init": 
                            self.my_onion = event.get("onion")
                            self.init_event.set()
                        elif evt_type == "info": self.cli.print_message(event["text"], msg_type="info", alias=event.get("alias"))
                        elif evt_type == "system": self.cli.print_message(event["text"], msg_type="system", alias=event.get("alias"))
                        elif evt_type == "remote_msg": self.cli.print_message(event["text"], msg_type="remote", alias=event["alias"])
                        elif evt_type == "ack": self.cli.mark_acked(event["msg_id"])
                        elif evt_type == "connected":
                            alias = event["alias"]
                            self.cli.print_message(event["text"], msg_type="info", alias=alias)
                            if self._pending_focus == alias:
                                self.switch_focus(alias)
                                self._pending_focus = None
                        elif evt_type == "disconnected":
                            alias = event["alias"]
                            self.cli.print_message(event["text"], msg_type="info", alias=alias)
                            if self._focused_alias == alias:
                                self.switch_focus(None)
                        elif evt_type == "rename_success":
                            old_alias = event["old_alias"]
                            new_alias = event["new_alias"]
                            self.cli.rename_alias_in_history(old_alias, new_alias)
                            if self._focused_alias == old_alias:
                                self.switch_focus(new_alias, hide_message=True)
                            self.cli.print_message(f'Renamed "{old_alias}" to "{new_alias}".', msg_type="system")
                            if not event.get("history_updated"):
                                self.cli.print_message(f"{Settings.RED}Note:{Settings.RESET} The history log did not update.", msg_type="system")
                        elif evt_type == "connections_state":
                            if event.get("is_header"):
                                self.header_active = event.get("active", [])
                                self.header_pending = event.get("pending", [])
                                self.conn_event.set()
                            else:
                                self._render_connections(event.get("active", []), event.get("pending", []))
                    except Exception: pass
        except Exception: pass

    def switch_focus(self, alias, hide_message=False):
        self._focused_alias = alias
        self.cli.set_focus(alias)
        if not hide_message:
            if alias:
                self.cli.print_message("Switched focus to {alias}", alias=alias, msg_type="system")
            else:
                self.cli.print_message("Removed focus.", msg_type="system")

    def _render_connections(self, active, pending, header_mode=False):
        if not header_mode: self.cli.print_divider()
        if not active and not pending and not header_mode:
            self.cli.print_message("No active or pending connections.")
            return
        if active:     
            self.cli.print_message("Active connections:")
            for alias in active:
                if alias == self._focused_alias:
                    self.cli.print_message(f" * {Settings.CYAN}{alias}{Settings.RESET}")
                else:
                    self.cli.print_message(f"   {alias}")
            if pending: self.cli.print_empty_line()
        if pending:
            self.cli.print_message("Pending connections:")
            for p in pending: 
                self.cli.print_message(f"   {p}")
        if not header_mode: self.cli.print_divider()

    def print_header(self, clear_screen=False):
        if clear_screen: self.cli.clear_screen()
        self.cli.print_empty_line()
        self.cli.print_message(f"Your onion address: {Settings.YELLOW}{clean_onion(self.my_onion)}{Settings.RESET}.onion", skip_prompt=True)
        self.cli.print_empty_line()
        self.cli.print_message(Help.show_chat_help(), skip_prompt=True)
        self.cli.print_empty_line()

        self.conn_event.clear()
        self._send_cmd({"action": "get_connections", "is_header": True})
        self.conn_event.wait(timeout=1.0)
        
        if self.header_active or self.header_pending:
            self._render_connections(self.header_active, self.header_pending, header_mode=True)
            self.cli.print_empty_line()
            
        self.cli.print_prompt()
