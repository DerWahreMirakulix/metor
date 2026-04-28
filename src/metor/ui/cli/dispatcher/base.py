"""CLI dispatcher facade coordinating modular command routing helpers."""

import argparse
from typing import List, Optional, Tuple

from metor.data import ProfileManager
from metor.ui import Help

# Local Package Imports
from metor.ui.cli.dispatcher.history import HistoryDispatchMixin
from metor.ui.cli.dispatcher.messages import MessagesDispatchMixin
from metor.ui.cli.dispatcher.profiles import ProfilesDispatchMixin
from metor.ui.cli.handlers import CommandHandlers
from metor.ui.cli.proxy import CliProxy


class CliDispatcher(ProfilesDispatchMixin, MessagesDispatchMixin, HistoryDispatchMixin):
    """Routes parsed CLI arguments to the corresponding application logic."""

    _help = Help

    @staticmethod
    def _collect_command_args(
        sub: Optional[str],
        extra: List[str],
        reserved_subcommands: Tuple[str, ...],
    ) -> List[str]:
        """
        Collects positional arguments while supporting shorthand target invocation.

        Args:
            sub (Optional[str]): Parsed subcommand token.
            extra (List[str]): Additional raw positional arguments.
            reserved_subcommands (Tuple[str, ...]): Reserved subcommand keywords.

        Returns:
            List[str]: Ordered positional arguments for the command action.
        """
        args: List[str] = list(extra)
        if sub and sub not in reserved_subcommands:
            args.insert(0, sub)
        return args

    @staticmethod
    def _parse_optional_limit(limit_raw: Optional[str]) -> Optional[int]:
        """
        Parses a decimal limit argument.

        Args:
            limit_raw (Optional[str]): Raw CLI token.

        Returns:
            Optional[int]: Parsed limit, or None if absent or invalid.
        """
        if limit_raw is None:
            return None
        if not limit_raw.isdigit():
            return None
        return int(limit_raw)

    def __init__(
        self,
        args: argparse.Namespace,
        extra: List[str],
        pm: ProfileManager,
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
                print(self._help.show_command_help(cmd, sub))
            else:
                print(self._help.show_main_help())
            return

        if cmd == 'quickstart':
            print(self._help.show_quick_start())

        elif cmd == 'help':
            print(self._help.show_main_help())

        elif cmd == 'daemon':
            if sub or self._extra:
                print(self._help.show_command_help(cmd))
            else:
                CommandHandlers.handle_daemon(
                    self._pm,
                    start_locked=getattr(self._args, 'locked', False),
                )

        elif cmd == 'unlock':
            if sub or self._extra:
                print(self._help.show_command_help(cmd))
            else:
                print(self._proxy.unlock_daemon())

        elif cmd == 'settings':
            if sub == 'set' and len(self._extra) >= 2:
                print(self._proxy.handle_settings_set(self._extra[0], self._extra[1]))
            elif sub == 'get' and len(self._extra) >= 1:
                print(self._proxy.handle_settings_get(self._extra[0]))
            elif sub == 'list' or (sub is None and not self._extra):
                print(self._proxy.handle_settings_list())
            else:
                print(self._help.show_command_help(cmd))

        elif cmd == 'config':
            if sub == 'set' and len(self._extra) >= 2:
                print(self._proxy.handle_config_set(self._extra[0], self._extra[1]))
            elif sub == 'get' and len(self._extra) >= 1:
                print(self._proxy.handle_config_get(self._extra[0]))
            elif sub == 'list' or (sub is None and not self._extra):
                print(self._proxy.handle_config_list())
            elif sub == 'sync':
                print(self._proxy.handle_config_sync())
            else:
                print(self._help.show_command_help(cmd))

        elif cmd == 'chat':
            CommandHandlers.handle_chat(self._pm)

        elif cmd == 'cleanup':
            cleanup_tokens: List[str] = []
            if sub:
                cleanup_tokens.append(sub)
            cleanup_tokens.extend(self._extra)

            invalid_tokens: List[str] = [
                token for token in cleanup_tokens if token != '--force'
            ]
            if invalid_tokens:
                print(self._help.show_command_help(cmd))
            else:
                CommandHandlers.handle_cleanup(force='--force' in cleanup_tokens)

        elif cmd == 'purge':
            is_nuke_remote: bool = (
                '--nuke-remote' in self._extra or sub == '--nuke-remote'
            )
            CommandHandlers.handle_purge(is_nuke_remote)

        elif cmd == 'send':
            if not sub or not self._extra:
                print(self._help.show_command_help(cmd))
            else:
                print(self._proxy.send_drop(sub, ' '.join(self._extra)))

        elif cmd == 'inbox':
            print(self._proxy.handle_inbox(sub))

        elif cmd == 'messages':
            self._dispatch_messages(sub)

        elif cmd == 'history':
            self._dispatch_history(sub)

        elif cmd == 'address':
            if sub in (None, 'show', 'generate'):
                print(self._proxy.get_address(generate=(sub == 'generate')))
            else:
                print(self._help.show_command_help(cmd))

        elif cmd == 'contacts':
            if sub == 'add':
                if len(self._extra) < 1:
                    print(self._help.show_command_help(cmd))
                else:
                    onion: Optional[str] = (
                        self._extra[1] if len(self._extra) > 1 else None
                    )
                    print(self._proxy.contacts_add(self._extra[0], onion))
            elif sub in ('rm', 'remove'):
                if len(self._extra) < 1:
                    print(self._help.show_command_help(cmd))
                else:
                    print(self._proxy.contacts_rm(self._extra[0]))
            elif sub == 'rename':
                if len(self._extra) < 2:
                    print(self._help.show_command_help(cmd))
                else:
                    print(self._proxy.contacts_rename(self._extra[0], self._extra[1]))
            elif sub == 'clear':
                print(self._proxy.contacts_clear())
            elif sub in ('list', None):
                print(self._proxy.contacts_list())
            else:
                print(self._help.show_command_help(cmd))

        elif cmd == 'profiles':
            self._dispatch_profiles(sub)

        else:
            print("Unknown command. Use 'metor help' to see available commands.")
