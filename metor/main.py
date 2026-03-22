"""
Main entry point for the Metor application. Handles command-line arguments and dispatches commands.
"""

import argparse
import json
import socket
import psutil
import os
import shutil
from typing import List, Dict, Any, Optional

from metor.ui.help import Help
from metor.data.profile import ProfileManager
from metor.core.key import KeyManager
from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.core.tor import TorManager
from metor.data.history import HistoryManager
from metor.data.contact import ContactManager
from metor.data.messages import MessageManager
from metor.ui.chat import Chat
from metor.core.daemon import Daemon
from metor.core.api import IpcCommand, IpcEvent, Action


class MetorApp:
    """Main application orchestrator and CLI dispatcher."""

    def __init__(self) -> None:
        """
        Initializes the CLI parser and core managers.

        Args:
            None

        Returns:
            None
        """
        self.parser: argparse.ArgumentParser = argparse.ArgumentParser(
            prog='metor', add_help=False
        )
        self.parser.add_argument(
            '-p', '--profile', default=ProfileManager.load_default_profile()
        )
        self.parser.add_argument('command', nargs='?', default='help')
        self.parser.add_argument('subcommand', nargs='?')
        self.parser.add_argument('extra', nargs='*')

        self.args: argparse.Namespace = self.parser.parse_args()

        self._pm: ProfileManager = ProfileManager(self.args.profile)
        self._km: KeyManager = KeyManager(self._pm)
        self._hm: HistoryManager = HistoryManager(self._pm)
        self._cm: ContactManager = ContactManager(self._pm)
        self._mm: MessageManager = MessageManager(self._pm)

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

    def _send_to_daemon(self, cmd: IpcCommand) -> bool:
        """
        Sends a strongly-typed command to the running daemon and immediately disconnects.

        Args:
            cmd (IpcCommand): The command payload to send.

        Returns:
            bool: True if the command was successfully sent, False otherwise.
        """
        port: Optional[int] = self._pm.get_daemon_port()
        if not port:
            return False

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((Constants.LOCALHOST, port))
                s.sendall((cmd.to_json() + '\n').encode('utf-8'))
            return True
        except Exception:
            return False

    def _request_from_daemon(self, cmd: IpcCommand) -> Optional[IpcEvent]:
        """
        Sends a command to the running daemon and waits for an IpcEvent response.

        Args:
            cmd (IpcCommand): The command payload to request data with.

        Returns:
            Optional[IpcEvent]: The parsed event response from the Daemon, or None if failed.
        """
        port: Optional[int] = self._pm.get_daemon_port()
        if not port:
            return None

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((Constants.LOCALHOST, port))
                s.sendall((cmd.to_json() + '\n').encode('utf-8'))

                buffer: str = ''
                while True:
                    chunk: bytes = s.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk.decode('utf-8')
                    if '\n' in buffer:
                        break

                if buffer:
                    resp_dict: Dict[str, Any] = json.loads(buffer.split('\n')[0])
                    return IpcEvent.from_dict(resp_dict)
        except Exception:
            pass
        return None

    def execute(self) -> None:
        """Parses the CLI arguments and executes the corresponding application logic."""
        cmd: str = self.args.command
        sub: Optional[str] = self.args.subcommand
        ext: List[str] = self.args.extra

        if cmd == 'help':
            print(Help.show_main_help())

        elif cmd == 'daemon':
            if self._pm.is_daemon_running():
                print(
                    f"Daemon for profile '{self._pm.profile_name}' is already running!"
                )
                return
            tm = TorManager(self._pm, self._km)
            daemon = Daemon(self._pm, self._km, tm, self._cm, self._hm, self._mm)
            daemon.run()

        elif cmd == 'chat':
            if not self._pm.is_daemon_running():
                print('The background daemon is not running.')
                return
            chat = Chat(self._pm, self._cm)
            chat.run()

        elif cmd == 'cleanup':
            print('Cleaning up Metor processes and locks...')
            killed: int = self._cleanup_processes()
            if killed > 0:
                print(
                    f'{Theme.GREEN}Success:{Theme.RESET} Killed {killed} active Tor process(es) and cleared locks.'
                )
            else:
                print(
                    f'{Theme.YELLOW}Info:{Theme.RESET} No active Tor processes found. Locks cleared.'
                )

        elif cmd == 'purge':
            print(
                f'{Theme.RED}WARNING: You are about to PERMANENTLY wipe the entire Metor directory!{Theme.RESET}'
            )
            print('This will destroy ALL profiles, Tor private keys and the database.')
            confirmation: str = input("Type 'yes' to proceed: ")

            if confirmation.strip().lower() == 'yes':
                self._cleanup_processes()
                if os.path.exists(Constants.DATA):
                    shutil.rmtree(Constants.DATA)
                    print(
                        f'{Theme.GREEN}Purge complete. All data destroyed.{Theme.RESET}'
                    )
                else:
                    print('Data directory does not exist. Nothing to purge.')
            else:
                print('Purge aborted.')

        elif cmd == 'send':
            if not sub or not ext:
                print('Usage: metor send <alias> "msg"')
                return

            target_alias: str = sub
            message_text: str = ' '.join(ext)

            _, onion = self._cm.resolve_target(target_alias)
            if not onion:
                print(f"Contact '{target_alias}' not found in address book.")
                return

            if self._pm.is_daemon_running():
                success: bool = self._send_to_daemon(
                    IpcCommand(
                        action=Action.SEND_DROP, target=target_alias, text=message_text
                    )
                )
                if success:
                    print(
                        f"{Theme.GREEN}Drop queued for '{target_alias}'. The Outbox Worker will handle delivery.{Theme.RESET}"
                    )
                else:
                    print(
                        f'{Theme.RED}Failed to queue drop. Daemon communication error.{Theme.RESET}'
                    )
            else:
                print('The background daemon must be running to send drops.')

        elif cmd == 'inbox':
            print(self._mm.show_inbox(self._cm))

        elif cmd == 'read':
            if not sub:
                print('Usage: metor read <alias>')
                return
            print(self._mm.show_read(sub, self._cm))

        elif cmd == 'messages':
            if sub == 'clear':
                target_alias: Optional[str] = ext[0] if len(ext) > 0 else None
                if target_alias:
                    _, onion = self._cm.resolve_target(target_alias)
                    if not onion:
                        print(f"Contact '{target_alias}' not found.")
                        return
                    _, msg = self._mm.clear_messages(onion)
                else:
                    _, msg = self._mm.clear_messages()
                print(msg)
            else:
                if sub == 'show':
                    target_alias = ext[0] if len(ext) > 0 else None
                    limit_str = ext[1] if len(ext) > 1 else None
                else:
                    target_alias = sub
                    limit_str = ext[0] if len(ext) > 0 else None

                if not target_alias:
                    print('Usage: metor messages [show] <alias> [limit]')
                    print('       metor messages clear [alias]')
                    return

                limit: int = int(limit_str) if limit_str and limit_str.isdigit() else 50
                print(self._mm.show_history(target_alias, self._cm, limit))

        elif cmd == 'address':
            if sub == 'generate':
                tm = TorManager(self._pm, self._km)
                _, msg = tm.generate_address()
                print(msg)
            elif sub == 'show' or not sub:
                tm = TorManager(self._pm, self._km)
                _, msg = tm.get_address()
                print(msg)
            else:
                print('Usage: metor address [show|generate]')

        elif cmd == 'history':
            if sub == 'clear':
                target_alias: Optional[str] = ext[0] if len(ext) > 0 else None
                if target_alias:
                    _, onion = self._cm.resolve_target(target_alias)
                    if not onion:
                        print(f"Contact '{target_alias}' not found.")
                        return
                    _, msg = self._hm.clear_history(onion)
                else:
                    _, msg = self._hm.clear_history()
                print(msg)
            else:
                if sub == 'show':
                    target_alias = ext[0] if len(ext) > 0 else None
                else:
                    target_alias = sub

                print(self._hm.show(self._cm, target_alias))

        elif cmd == 'contacts':
            if sub == 'add':
                if len(ext) < 1:
                    print('Usage: metor contacts add <alias> [onion]')
                elif len(ext) == 1:
                    if self._pm.is_daemon_running():
                        success: bool = self._send_to_daemon(
                            IpcCommand(action=Action.ADD_CONTACT, alias=ext[0])
                        )
                        if success:
                            print('Command sent to running daemon.')
                        else:
                            print('Failed to communicate with daemon.')
                    else:
                        print(
                            'Daemon not running. Cannot save a RAM alias without an active session.'
                        )
                else:
                    if self._pm.is_daemon_running():
                        success = self._send_to_daemon(
                            IpcCommand(
                                action=Action.ADD_CONTACT, alias=ext[0], onion=ext[1]
                            )
                        )
                        if success:
                            print('Command sent to running daemon.')
                        else:
                            print('Failed to communicate with daemon.')
                    else:
                        _, msg = self._cm.add_contact(ext[0], ext[1])
                        print(msg)

            elif sub in ('rm', 'remove'):
                if len(ext) < 1:
                    print('Usage: metor contacts rm <alias>')
                else:
                    if self._pm.is_daemon_running():
                        success = self._send_to_daemon(
                            IpcCommand(action=Action.REMOVE_CONTACT, alias=ext[0])
                        )
                        if success:
                            print(
                                'Command sent to running daemon. Active sessions will be downgraded.'
                            )
                        else:
                            print('Failed to communicate with daemon.')
                    else:
                        _, msg = self._cm.remove_contact(ext[0])
                        print(msg)

            elif sub == 'rename':
                if len(ext) < 2:
                    print('Usage: metor contacts rename <old> <new>')
                else:
                    old_alias, new_alias = ext[0], ext[1]

                    if self._pm.is_daemon_running():
                        success = self._send_to_daemon(
                            IpcCommand(
                                action=Action.RENAME_CONTACT,
                                old_alias=old_alias,
                                new_alias=new_alias,
                            )
                        )
                        if success:
                            print(
                                'Command sent to running daemon. Check active chat windows to verify.'
                            )
                        else:
                            print('Failed to communicate with daemon.')
                    else:
                        success, msg = self._cm.rename_contact(old_alias, new_alias)
                        if success:
                            self._hm.update_alias(old_alias, new_alias)
                        print(msg)

            elif sub == 'clear':
                _, msg = self._cm.clear_contacts()
                print(msg)

            elif sub == 'list' or not sub:
                if self._pm.is_daemon_running():
                    resp: Optional[IpcEvent] = self._request_from_daemon(
                        IpcCommand(action=Action.GET_CONTACTS_LIST, chat_mode=False)
                    )
                    if resp and resp.text:
                        print(resp.text)
                    else:
                        print('Failed to fetch contacts from daemon.')
                else:
                    print(self._cm.show(chat_mode=False))
            else:
                print('Usage: metor contacts [list|add|rm|rename|clear] <args>')

        elif cmd == 'profiles':
            if sub == 'add':
                if len(ext) < 1:
                    print('Usage: metor profiles add <name>')
                else:
                    _, msg = ProfileManager.add_profile_folder(ext[0])
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
                    print('Usage: metor profiles rename <old_name> <new_name>')
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
                    _, msg = ProfileManager.clear_profile_db(ext[0])
                    print(msg)
            elif sub == 'list' or not sub:
                print(ProfileManager.show(self._pm.profile_name))
            else:
                print(
                    'Usage: metor profiles [list|add|rm|rename|set-default|clear] <args>'
                )

        else:
            print("Unknown command. Use 'metor help' to see available commands.")


def main() -> None:
    """Invokes the Metor application."""
    app = MetorApp()
    app.execute()


if __name__ == '__main__':
    main()
