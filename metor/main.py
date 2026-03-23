"""
Main entry point for the Metor application. Handles command-line arguments and dispatches commands.
"""

import argparse
import os
import shutil
import psutil
from typing import List, Optional

from metor.ui.help import Help
from metor.data.profile import ProfileManager
from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.ui.chat import Chat
from metor.core.daemon import Daemon
from metor.core.proxy import CliProxy


class MetorApp:
    """Main application orchestrator and CLI dispatcher."""

    def __init__(self) -> None:
        """
        Initializes the CLI parser and core managers.

        Args:
            None
        """
        self.parser: argparse.ArgumentParser = argparse.ArgumentParser(
            prog='metor', add_help=False
        )
        self.parser.add_argument(
            '-p', '--profile', default=ProfileManager.load_default_profile()
        )
        self.parser.add_argument(
            '--remote', action='store_true', help='Set profile as remote client'
        )
        self.parser.add_argument('--port', type=int, help='Set static daemon port')

        self.parser.add_argument('command', nargs='?', default='help')
        self.parser.add_argument('subcommand', nargs='?')
        self.parser.add_argument('extra', nargs='*')

        self.args: argparse.Namespace = self.parser.parse_args()
        self._pm: ProfileManager = ProfileManager(self.args.profile)
        self.proxy: CliProxy = CliProxy(self._pm)

    def _cleanup_processes(self) -> int:
        """
        Kills all active Tor processes and removes ghost Daemon locks.

        Returns:
            int: The number of processes killed.
        """
        killed: int = 0
        for proc in psutil.process_iter(['pid', 'name', 'status']):
            try:
                if proc.info.get('status') == psutil.STATUS_ZOMBIE:
                    continue
                proc_name: str = proc.info['name'].lower() if proc.info['name'] else ''
                if proc_name in ('tor', 'tor.exe'):
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        for profile_name in ProfileManager.get_all_profiles():
            temp_pm = ProfileManager(profile_name)
            temp_pm.clear_daemon_port()
        return killed

    def execute(self) -> None:
        """Parses the CLI arguments and executes the corresponding application logic."""
        cmd: str = self.args.command
        sub: Optional[str] = self.args.subcommand
        ext: List[str] = self.args.extra

        if cmd == 'help':
            print(Help.show_main_help())

        elif cmd == 'daemon':
            if self._pm.is_remote():
                print(
                    f'{Theme.RED}Error:{Theme.RESET} Cannot start a daemon on a remote profile!'
                )
                return
            if self._pm.is_daemon_running():
                print(
                    f"Daemon for profile '{self._pm.profile_name}' is already running!"
                )
                return

            from metor.core.key import KeyManager
            from metor.core.tor import TorManager
            from metor.data.history import HistoryManager
            from metor.data.contact import ContactManager
            from metor.data.messages import MessageManager

            km = KeyManager(self._pm)
            tm = TorManager(self._pm, km)
            cm = ContactManager(self._pm)
            hm = HistoryManager(self._pm)
            mm = MessageManager(self._pm)

            daemon = Daemon(self._pm, km, tm, cm, hm, mm)
            daemon.run()

        elif cmd == 'chat':
            if not self._pm.is_daemon_running():
                print('The background daemon is not running or unreachable.')
                return

            # The UI is completely stateless and handles no SQLite connections.
            chat = Chat(self._pm)
            chat.run()

        elif cmd == 'cleanup':
            print('Cleaning up Metor processes and locks...')
            killed: int = self._cleanup_processes()
            print(
                f'{Theme.GREEN}Success:{Theme.RESET} Killed {killed} Tor process(es) and cleared locks.'
            )

        elif cmd == 'purge':
            print(
                f'{Theme.RED}WARNING: You are about to PERMANENTLY wipe the entire Metor directory!{Theme.RESET}'
            )
            confirmation: str = input("Type 'yes' to proceed: ")
            if confirmation.strip().lower() == 'yes':
                self._cleanup_processes()
                if os.path.exists(Constants.DATA):
                    shutil.rmtree(Constants.DATA)
                    print(
                        f'{Theme.GREEN}Purge complete. All data destroyed.{Theme.RESET}'
                    )
            else:
                print('Purge aborted.')

        elif cmd == 'send':
            if not sub or not ext:
                print('Usage: metor send <alias> "msg"')
            else:
                print(self.proxy.send_drop(sub, ' '.join(ext)))

        elif cmd == 'inbox':
            print(self.proxy.handle_inbox('inbox'))

        elif cmd == 'read':
            if not sub:
                print('Usage: metor read <alias>')
            else:
                print(self.proxy.handle_inbox('read', sub))

        elif cmd == 'messages':
            action: str = 'clear' if sub == 'clear' else 'show'
            target: Optional[str] = (
                ext[0] if ext else (sub if sub not in ('show', 'clear') else None)
            )
            limit_str: Optional[str] = (
                ext[1]
                if len(ext) > 1
                else (ext[0] if ext and action == 'show' and sub != 'show' else None)
            )
            limit: int = int(limit_str) if limit_str and limit_str.isdigit() else 50

            print(self.proxy.handle_messages(action, target, limit))

        elif cmd == 'history':
            action = 'clear' if sub == 'clear' else 'show'
            target = ext[0] if ext else (sub if sub not in ('show', 'clear') else None)
            print(self.proxy.handle_history(action, target))

        elif cmd == 'address':
            print(self.proxy.get_address(generate=(sub == 'generate')))

        elif cmd == 'contacts':
            if sub == 'add':
                if len(ext) < 1:
                    print('Usage: metor contacts add <alias> [onion]')
                else:
                    onion: Optional[str] = ext[1] if len(ext) > 1 else None
                    print(self.proxy.contacts_add(ext[0], onion))
            elif sub in ('rm', 'remove'):
                if len(ext) < 1:
                    print('Usage: metor contacts rm <alias>')
                else:
                    print(self.proxy.contacts_rm(ext[0]))
            elif sub == 'rename':
                if len(ext) < 2:
                    print('Usage: metor contacts rename <old> <new>')
                else:
                    print(self.proxy.contacts_rename(ext[0], ext[1]))
            elif sub == 'clear':
                print(self.proxy.contacts_clear())
            else:
                print(self.proxy.contacts_list())

        elif cmd == 'profiles':
            if sub == 'add':
                if len(ext) < 1:
                    print('Usage: metor profiles add <name> [--remote] [--port <int>]')
                else:
                    _, msg = ProfileManager.add_profile_folder(
                        ext[0], is_remote=self.args.remote, port=self.args.port
                    )
                    print(msg)
            elif sub in ('rm', 'remove'):
                if len(ext) < 1:
                    print('Usage: metor profiles rm <name>')
                else:
                    _, msg = ProfileManager.remove_profile_folder(
                        ext[0], self._pm.profile_name
                    )
                    print(msg)
            elif sub == 'rename':
                if len(ext) < 2:
                    print('Usage: metor profiles rename <old> <new>')
                else:
                    _, msg = ProfileManager.rename_profile_folder(ext[0], ext[1])
                    print(msg)
            elif sub == 'set-default':
                if len(ext) < 1:
                    print('Usage: metor profiles set-default <name>')
                else:
                    _, msg = ProfileManager.set_default_profile(ext[0])
                    print(msg)
            elif sub == 'clear':
                if len(ext) < 1:
                    print('Usage: metor profiles clear <name>')
                else:
                    # FIX 3: Prevent local clears on remote profiles to avoid confusion.
                    target_pm = ProfileManager(ext[0])
                    if target_pm.is_remote():
                        print(
                            f"{Theme.RED}Error:{Theme.RESET} '{ext[0]}' is a remote profile.\n"
                            f"Please SSH into the remote server and run 'metor profiles clear {ext[0]}' locally."
                        )
                    else:
                        _, msg = ProfileManager.clear_profile_db(ext[0])
                        print(msg)
            else:
                print(ProfileManager.show(self._pm.profile_name))

        else:
            print("Unknown command. Use 'metor help' to see available commands.")


def main() -> None:
    """Invokes the Metor application."""
    app = MetorApp()
    app.execute()


if __name__ == '__main__':
    main()
