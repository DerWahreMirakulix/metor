import argparse

from metor.config import ProfileManager, KeyManager, HelpMenu
from metor.tor import TorManager
from metor.history import HistoryManager
from metor.contacts import ContactsManager
from metor.cli import CommandLineInput
from metor.chat import ChatManager

class MetorApp:
    """The central application orchestrator."""
    
    def __init__(self):
        self.parser = argparse.ArgumentParser(prog="metor", add_help=False)
        self.parser.add_argument('-p', '--profile', default=ProfileManager.load_default_profile())
        self.parser.add_argument('command', nargs='?', default='help')
        self.parser.add_argument('subcommand', nargs='?')
        self.parser.add_argument('extra', nargs='*')
        self.args = self.parser.parse_args()

        # Core Managers
        self.pm = ProfileManager(self.args.profile)
        self.km = KeyManager(self.pm)
        self.history = HistoryManager(self.pm)
        self.contacts = ContactsManager(self.pm)

    def execute(self):
        cmd = self.args.command
        sub = self.args.subcommand
        ext = self.args.extra

        if cmd == "help":
            print(HelpMenu.show_main_help())
            
        elif cmd == "chat":
            if self.pm.is_chat_running():
                print(f"A chat session for profile '{self.pm.profile_name}' is already running!")
                print("Hint: Close the other session first before starting a new one.")
                return
            
            self.pm.set_chat_lock()
            try:
                tor = TorManager(self.pm, self.km)
                cli = CommandLineInput()
                chat = ChatManager(self.pm, self.km, tor, self.contacts, self.history, cli)
                chat.run()
            finally:
                self.pm.clear_chat_lock()
                
        elif cmd == "address":
            if sub == "show":
                tor = TorManager(self.pm, self.km)
                address = tor.get_address()
                if address: print(f"Current onion address for profile '{self.pm.profile_name}': {address}")
                else: print(f"No onion address generated yet for profile '{self.pm.profile_name}'. Start chat mode or generate a new address.")
            elif sub == "generate":
                tor = TorManager(self.pm, self.km)
                _, msg = tor.generate_address()
                print(msg)
            else:
                print("Usage: metor address [show|generate]")
                
        elif cmd == "history":
            if sub == "clear":
                if self.history.clear_history(): print(f"History from profile '{self.pm.profile_name}' cleared.")
                else: print(f"Failed to clear history for profile '{self.pm.profile_name}'.")
            else:
                print(self.history.show())
                
        elif cmd == "contacts":
            if sub == "list" or not sub:
                print(self.contacts.show())
                        
            elif sub == "add":
                if len(ext) < 2: print("Usage: metor contacts add [alias] [onion]")
                else:
                    alias = self.contacts.add_contact(ext[0], ext[1])
                    print(f"Contact '{alias}' added successfully to profile '{self.pm.profile_name}'.")
                    
            elif sub in ("rm", "remove"):
                if len(ext) < 1: print("Usage: metor contacts rm [alias]")
                elif self.pm.is_chat_running(): 
                    print(f"Cannot remove contacts while a chat session is running for profile '{self.pm.profile_name}'.")
                    print("Hint: Use the '/remove' command directly inside the active chat!")
                else:
                    alias = ext[0]
                    if self.contacts.remove_contact(alias): print(f"Contact '{alias}' removed from profile '{self.pm.profile_name}'.")
                    else: print(f"Contact '{alias}' not found in profile '{self.pm.profile_name}'.")
                        
            elif sub == "rename":
                if len(ext) < 2: print("Usage: metor contacts rename [old_alias] [new_alias]")
                elif self.pm.is_chat_running():
                    print(f"Cannot rename contacts externally while a chat session is running for profile '{self.pm.profile_name}'.")
                    print("Hint: Use the '/rename' command directly inside the active chat!")
                else:
                    old_alias, new_alias = ext[0], ext[1]
                    if self.contacts.rename_contact(old_alias, new_alias):
                        print(f"Contact renamed from '{old_alias}' to '{new_alias}' in profile '{self.pm.profile_name}'.")
                    else:
                        print(f"Failed to rename contact in profile '{self.pm.profile_name}'. Check if old alias exists and new alias is free.")
            else:
                print("Usage: metor contacts [list|add|rm|rename]")

        elif cmd == "profile":
            if sub == "list" or not sub:
                print(ProfileManager.show(self.pm.profile_name))

            elif sub == "add":
                if len(ext) < 1: print("Usage: metor profile add [name]")
                else:
                    _, msg = ProfileManager.add_profile_folder(ext[0])
                    print(msg)

            elif sub in ("rm", "remove"):
                if len(ext) < 1: print("Usage: metor profile rm [name]")
                else:
                    _, msg = ProfileManager.remove_profile_folder(ext[0])
                    print(msg)
                        
            elif sub == "rename":
                if len(ext) < 2: print("Usage: metor profile rename [old_name] [new_name]")
                else:
                    _, msg = ProfileManager.rename_profile_folder(ext[0], ext[1])
                    print(msg)
            
            elif sub == "set-default":
                if len(ext) < 1: print("Usage: metor profile set-default [name]")
                else:
                    _, msg = ProfileManager.set_default_profile(ext[0])
                    print(msg)
            
            else:
                print("Usage: metor profile [list|add|rm|rename|set-default]")
                
        else:
            print("Unknown command. Use 'metor help' to see available commands.")

def main():
    app = MetorApp()
    app.execute()
