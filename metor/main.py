import argparse
import json
import socket
import psutil

from metor.help import Help
from metor.profile import ProfileManager
from metor.key import KeyManager
from metor.settings import Settings
from metor.tor import TorManager
from metor.history import HistoryManager
from metor.contact import ContactManager
from metor.cli import CommandLineInput
from metor.chat import Chat
from metor.deamon import Daemon

class MetorApp:
    def __init__(self):
        self.parser = argparse.ArgumentParser(prog="metor", add_help=False)
        self.parser.add_argument('-p', '--profile', default=ProfileManager.load_default_profile())
        self.parser.add_argument('command', nargs='?', default='help')
        self.parser.add_argument('subcommand', nargs='?')
        self.parser.add_argument('extra', nargs='*')
        self.args = self.parser.parse_args()

        self.pm = ProfileManager(self.args.profile)
        self.km = KeyManager(self.pm)
        self.hm = HistoryManager(self.pm)
        self.cm = ContactManager(self.pm)

    def _send_to_daemon(self, action_dict):
        """Sends a single JSON command to the daemon and immediately disconnects."""
        port = self.pm.get_daemon_port()
        if not port: return False
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(('127.0.0.1', port))
                s.sendall((json.dumps(action_dict) + "\n").encode())
            return True
        except Exception:
            return False
        
    def _request_from_daemon(self, action_dict):
        """Sends a command and waits for a single JSON response line."""
        port = self.pm.get_daemon_port()
        if not port: return None
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(('127.0.0.1', port))
                s.sendall((json.dumps(action_dict) + "\n").encode())
                
                buffer = ""
                while True:
                    chunk = s.recv(4096)
                    if not chunk: break
                    buffer += chunk.decode()
                    if "\n" in buffer:
                        break
                        
                if buffer:
                    return json.loads(buffer.split("\n")[0])
        except Exception:
            pass
        return None

    def execute(self):
        cmd, sub, ext = self.args.command, self.args.subcommand, self.args.extra

        if cmd == "help":
            print(Help.show_main_help())
            
        elif cmd == "daemon":
            if self.pm.is_daemon_running():
                print(f"Daemon for profile '{self.pm.profile_name}' is already running!")
                return
            tm = TorManager(self.pm, self.km)
            daemon = Daemon(self.pm, self.km, tm, self.cm, self.hm)
            daemon.run()
            
        elif cmd == "chat":
            if not self.pm.is_daemon_running():
                print(f"The background daemon is not running.")
                print(f"{Settings.CYAN}Hint:{Settings.RESET} Start it first in another terminal: {Settings.CYAN}metor daemon{Settings.RESET}")
                return
            
            cli = CommandLineInput()
            chat = Chat(self.pm, self.cm, self.hm, cli)
            chat.run()
                
        elif cmd == "address":
            if sub == "show":
                tm = TorManager(self.pm, self.km)
                _, msg = tm.get_address()
                print(msg)
            elif sub == "generate":
                tm = TorManager(self.pm, self.km)
                _, msg = tm.generate_address()
                print(msg)
            else:
                print("Usage: metor address [show|generate]")
                
        elif cmd == "history":
            if sub == "clear":
                _, msg = self.hm.clear_history()
                print(msg)
            else:
                print(self.hm.show())
                
        elif cmd == "contacts":
            if sub == "list" or not sub:
                if self.pm.is_daemon_running():
                    resp = self._request_from_daemon({"action": "get_contacts_list", "chat_mode": False})
                    if resp and "text" in resp:
                        print(resp["text"])
                    else:
                        print(f"{Settings.RED}Error:{Settings.RESET} Failed to fetch contacts from daemon.")
                else:
                    # if no deamon there is no ram contacts, so we show the normal list which only contains saved contacts
                    print(self.cm.show(chat_mode=False))
                        
            elif sub == "add":
                if len(ext) < 1: 
                    print("Usage: metor contacts add <alias> [onion]")
                elif len(ext) == 1:
                    if self.pm.is_daemon_running():
                        success = self._send_to_daemon({"action": "add_contact", "alias": ext[0]})
                        if success: print("Command sent to running daemon.")
                        else: print(f"{Settings.RED}Error:{Settings.RESET} Failed to communicate with daemon.")
                    else:
                        print(f"{Settings.RED}Error:{Settings.RESET} Daemon not running. Cannot save a RAM alias without an active session.")
                else:
                    if self.pm.is_daemon_running():
                        success = self._send_to_daemon({"action": "add_contact", "alias": ext[0], "onion": ext[1]})
                        if success: print("Command sent to running daemon.")
                        else: print(f"{Settings.RED}Error:{Settings.RESET} Failed to communicate with daemon.")
                    else:
                        _, msg = self.cm.add_contact(ext[0], ext[1])
                        print(msg)
                    
            elif sub in ("rm", "remove"):
                if len(ext) < 1: 
                    print("Usage: metor contacts rm <alias>")
                else:
                    if self.pm.is_daemon_running():
                        success = self._send_to_daemon({"action": "remove_contact", "alias": ext[0]})
                        if success: print("Command sent to running daemon. Active sessions will be downgraded.")
                        else: print(f"{Settings.RED}Error:{Settings.RESET} Failed to communicate with daemon.")
                    else:
                        _, msg = self.cm.remove_contact(ext[0])
                        print(msg)
                        
            elif sub == "rename":
                if len(ext) < 2: 
                    print("Usage: metor contacts rename <old_alias> <new_alias>")
                else:
                    old_alias, new_alias = ext[0], ext[1]
                    
                    if self.pm.is_daemon_running():
                        success = self._send_to_daemon({
                            "action": "rename_contact", 
                            "old_alias": old_alias, 
                            "new_alias": new_alias
                        })
                        if success:
                            print(f"Command sent to running daemon. Check active chat windows to verify.")
                        else:
                            print(f"{Settings.RED}Error:{Settings.RESET} Failed to communicate with daemon.")
                    else:
                        success, msg = self.cm.rename_contact(old_alias, new_alias)
                        if success:
                            self.hm.update_alias(old_alias, new_alias)
                        print(msg)
            else:
                print("Usage: metor contacts [list|add|rm|rename] ..options")

        elif cmd == "profiles":
            if sub == "list" or not sub:
                print(ProfileManager.show(self.pm.profile_name))
            elif sub == "add":
                if len(ext) < 1: print("Usage: metor profiles add [name]")
                else:
                    _, msg = ProfileManager.add_profile_folder(ext[0])
                    print(msg)
            elif sub in ("rm", "remove"):
                if len(ext) < 1: print("Usage: metor profiles rm [name]")
                else:
                    _, msg = ProfileManager.remove_profile_folder(ext[0])
                    print(msg)
            elif sub == "rename":
                if len(ext) < 2: print("Usage: metor profiles rename [old_name] [new_name]")
                else:
                    _, msg = ProfileManager.rename_profile_folder(ext[0], ext[1])
                    print(msg)
            elif sub == "set-default":
                if len(ext) < 1: print("Usage: metor profiles set-default [name]")
                else:
                    _, msg = ProfileManager.set_default_profile(ext[0])
                    print(msg)
            else:
                print("Usage: metor profiles [list|add|rm|rename|set-default] ..options")

        elif cmd == "cleanup":
            print(f"Cleaning up Metor processes and locks...")
            killed = 0
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    proc_name = proc.info['name'].lower() if proc.info['name'] else ""
                    if proc_name in ('tor', 'tor.exe'):
                        proc.kill()
                        killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            for profile_name in ProfileManager.get_all_profiles():
                temp_pm = ProfileManager(profile_name)
                temp_pm.clear_daemon_port()

            if killed > 0:
                print(f"{Settings.GREEN}Success:{Settings.RESET} Killed {killed} zombie Tor process(es) and cleared locks.")
            else:
                print(f"{Settings.YELLOW}Info:{Settings.RESET} No zombie Tor processes found. Locks cleared.")
                
        else:
            print("Unknown command. Use 'metor help' to see available commands.")
    
def main():
    app = MetorApp()
    app.execute()
