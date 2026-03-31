"""
Module defining the CLI command router.
Implements the Command Pattern to direct parsed inputs to the correct proxy or handler.
"""

import argparse
from typing import List, Optional, Dict

from metor.core.api import JsonValue
from metor.data.profile import ProfileManager
from metor.ui import Help, UIPresenter

# Local Package Imports
from metor.ui.cli.handlers import CommandHandlers
from metor.ui.cli.proxy import CliProxy


class CliDispatcher:
    """Routes parsed CLI arguments to the corresponding application logic."""

    def __init__(
        self, args: argparse.Namespace, extra: List[str], pm: ProfileManager
    ) -> None:
        """
        Initializes the dispatcher with the parsed arguments and active profile.

        Args:
            args (argparse.Namespace): The parsed CLI arguments.
            extra (List[str]): Extra unparsed arguments.
            pm (ProfileManager): The active profile configuration.

        Returns:
            None
        """
        self._args: argparse.Namespace = args
        self._extra: List[str] = extra
        self._pm: ProfileManager = pm
        self._proxy: CliProxy = CliProxy(pm)

    def dispatch(self) -> None:
        """
        Evaluates the command string and executes the matching subsystem or proxy call.

        Args:
            None

        Returns:
            None
        """
        cmd: str = self._args.command
        sub: Optional[str] = self._args.subcommand

        # --- Pre-Routing Help Interceptor ---
        is_help_request: bool = False
        if cmd in ('-h', '--help'):
            is_help_request = True
            cmd = 'help'
        elif sub in ('-h', '--help'):
            is_help_request = True
        elif '-h' in self._extra or '--help' in self._extra:
            is_help_request = True

        if is_help_request:
            if cmd and cmd not in ('help', 'quickstart', '-h', '--help'):
                print(Help.show_command_help(cmd, sub))
            else:
                print(Help.show_main_help())
            return

        # --- Standard Command Routing ---
        if cmd == 'quickstart':
            print(Help.show_quick_start())

        elif cmd == 'help':
            print(Help.show_main_help())

        elif cmd == 'daemon':
            CommandHandlers.handle_daemon(self._pm)

        elif cmd == 'unlock':
            if not sub:
                print(Help.show_command_help(cmd))
            else:
                print(self._proxy.unlock_daemon(sub))

        elif cmd == 'settings':
            if sub == 'set' and len(self._extra) >= 2:
                print(self._proxy.handle_settings(self._extra[0], self._extra[1]))
            else:
                print(Help.show_command_help(cmd))

        elif cmd == 'chat':
            CommandHandlers.handle_chat(self._pm)

        elif cmd == 'cleanup':
            CommandHandlers.handle_cleanup()

        elif cmd == 'purge':
            is_nuke_remote: bool = (
                '--nuke-remote' in self._extra or sub == '--nuke-remote'
            )
            CommandHandlers.handle_purge(is_nuke_remote)

        elif cmd == 'send':
            if not sub or not self._extra:
                print(Help.show_command_help(cmd))
            else:
                print(self._proxy.send_drop(sub, ' '.join(self._extra)))

        elif cmd == 'inbox':
            print(self._proxy.handle_inbox(sub))

        elif cmd == 'messages':
            action: str = 'clear' if sub == 'clear' else 'show'
            non_contacts_only: bool = '--non-contacts' in self._extra
            clean_ext: List[str] = [x for x in self._extra if x != '--non-contacts']

            target: Optional[str] = (
                clean_ext[0]
                if clean_ext
                else (sub if sub not in ('show', 'clear') else None)
            )
            limit_str: Optional[str] = (
                clean_ext[1]
                if len(clean_ext) > 1
                else (
                    clean_ext[0]
                    if clean_ext and action == 'show' and sub != 'show'
                    else None
                )
            )
            limit: Optional[int] = (
                int(limit_str) if limit_str and limit_str.isdigit() else None
            )

            print(self._proxy.handle_messages(action, target, limit, non_contacts_only))

        elif cmd == 'history':
            action = 'clear' if sub == 'clear' else 'show'
            target = (
                self._extra[0]
                if self._extra
                else (sub if sub not in ('show', 'clear') else None)
            )
            limit_str = (
                self._extra[1]
                if len(self._extra) > 1
                else (
                    self._extra[0]
                    if self._extra and action == 'show' and sub != 'show'
                    else None
                )
            )
            limit = int(limit_str) if limit_str and limit_str.isdigit() else None

            print(self._proxy.handle_history(action, target, limit))

        elif cmd == 'address':
            print(self._proxy.get_address(generate=(sub == 'generate')))

        elif cmd == 'contacts':
            if sub == 'add':
                if len(self._extra) < 1:
                    print(Help.show_command_help(cmd))
                else:
                    onion: Optional[str] = (
                        self._extra[1] if len(self._extra) > 1 else None
                    )
                    print(self._proxy.contacts_add(self._extra[0], onion))
            elif sub in ('rm', 'remove'):
                if len(self._extra) < 1:
                    print(Help.show_command_help(cmd))
                else:
                    print(self._proxy.contacts_rm(self._extra[0]))
            elif sub == 'rename':
                if len(self._extra) < 2:
                    print(Help.show_command_help(cmd))
                else:
                    print(self._proxy.contacts_rename(self._extra[0], self._extra[1]))
            elif sub == 'clear':
                print(self._proxy.contacts_clear())
            elif sub in ('list', None):
                print(self._proxy.contacts_list())
            else:
                print(Help.show_command_help(cmd))

        elif cmd == 'profiles':
            if sub == 'add':
                if len(self._extra) < 1:
                    print(Help.show_command_help(cmd))
                else:
                    _, _, msg_dict = ProfileManager.add_profile_folder(
                        self._extra[0],
                        is_remote=getattr(self._args, 'remote', False),
                        port=getattr(self._args, 'port', None),
                    )
                    print(str(msg_dict))
            elif sub in ('rm', 'remove'):
                if len(self._extra) < 1:
                    print(Help.show_command_help(cmd))
                else:
                    target_profile: str = self._extra[0]
                    is_nuke_remote = '--nuke-remote' in self._extra

                    if is_nuke_remote:
                        remotes = (
                            [target_profile]
                            if ProfileManager(target_profile).is_remote()
                            else []
                        )
                        if remotes and not CommandHandlers._nuke_remote_profiles(
                            remotes
                        ):
                            print('Profile removal aborted.')
                            return

                    _, _, msg_dict = ProfileManager.remove_profile_folder(
                        target_profile, self._pm.profile_name
                    )
                    print(str(msg_dict))
            elif sub == 'rename':
                if len(self._extra) < 2:
                    print(Help.show_command_help(cmd))
                else:
                    _, _, msg_dict = ProfileManager.rename_profile_folder(
                        self._extra[0], self._extra[1]
                    )
                    print(str(msg_dict))
            elif sub == 'set-default':
                if len(self._extra) < 1:
                    print(Help.show_command_help(cmd))
                else:
                    _, _, msg_dict = ProfileManager.set_default_profile(self._extra[0])
                    print(str(msg_dict))
            elif sub == 'clear':
                if len(self._extra) < 1:
                    print(Help.show_command_help(cmd))
                else:
                    target_pm: ProfileManager = ProfileManager(self._extra[0])
                    target_proxy: CliProxy = CliProxy(target_pm)
                    print(target_proxy.clear_profile_db())
            elif sub in ('list', None):
                data: Dict[str, JsonValue] = ProfileManager.get_profiles_data(
                    self._pm.profile_name
                )
                print(UIPresenter.format_profiles(data))  # type: ignore
            else:
                print(Help.show_command_help(cmd))

        else:
            print("Unknown command. Use 'metor help' to see available commands.")
