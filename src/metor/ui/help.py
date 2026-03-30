"""
Module providing static help texts, CLI command documentation, and a centralized Command Registry.
Enforces the DRY principle by dynamically generating help menus from strongly-typed dataclasses,
supporting nested subcommands for clean terminal alignment.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Local Package Imports
from metor.ui.theme import Theme
from metor.ui.presenter import UIPresenter


@dataclass
class SubCommandDef:
    """Strongly typed definition of a nested subcommand."""

    usage: str
    description: str


@dataclass
class CommandDef:
    """Strongly typed definition of a CLI or Chat command."""

    name: str
    usage: str
    description: str
    category: str
    subcommands: List[SubCommandDef] = field(default_factory=list)


class Help:
    """Static help generator utilizing a DRY data-driven command registry."""

    DESC_COLUMN: int = 45

    CLI_CATEGORIES: List[str] = [
        'Global Options',
        'Core Operations',
        'Messaging & History',
        'Contact Management',
        'Profile & Identity',
        'System & Settings',
    ]

    CHAT_CATEGORIES: List[str] = [
        'Session & Connection',
        'Messaging & Display',
        'Contact Management',
        'System',
    ]

    CLI_COMMANDS: Dict[str, CommandDef] = {
        'profile': CommandDef(
            name='profile',
            usage='-p, --profile <name>',
            description="Set the active profile (default: 'default').",
            category='Global Options',
        ),
        'help': CommandDef(
            name='help',
            usage='metor help',
            description='Show this help overview.',
            category='Core Operations',
        ),
        'daemon': CommandDef(
            name='daemon',
            usage='metor daemon',
            description='Start the background Tor & IPC engine.',
            category='Core Operations',
        ),
        'unlock': CommandDef(
            name='unlock',
            usage='metor unlock <password>',
            description='Unlock a remote daemon instance over IPC.',
            category='Core Operations',
        ),
        'chat': CommandDef(
            name='chat',
            usage='metor chat',
            description='Enter the interactive multi-chat UI.',
            category='Core Operations',
        ),
        'send': CommandDef(
            name='send',
            usage='metor send <onion|alias> "msg"',
            description='Drop an offline message to a contact.',
            category='Messaging & History',
        ),
        'inbox': CommandDef(
            name='inbox',
            usage='metor inbox [onion|alias]',
            description='Check for unread offline messages or read them.',
            category='Messaging & History',
        ),
        'messages': CommandDef(
            name='messages',
            usage='metor messages',
            description='View or delete chat history with a contact.',
            category='Messaging & History',
            subcommands=[
                SubCommandDef('show <onion|alias> [limit]', 'View past chat history.'),
                SubCommandDef(
                    'clear <onion|alias> [--non-contacts]', 'Delete message history.'
                ),
            ],
        ),
        'history': CommandDef(
            name='history',
            usage='metor history',
            description='View or wipe the connection event log.',
            category='Messaging & History',
            subcommands=[
                SubCommandDef(
                    'show [onion|alias] [limit]', 'View connection event log.'
                ),
                SubCommandDef('clear [onion|alias]', 'Wipe the connection event log.'),
            ],
        ),
        'contacts': CommandDef(
            name='contacts',
            usage='metor contacts',
            description='Manage your address book.',
            category='Contact Management',
            subcommands=[
                SubCommandDef('list', 'List all contacts in your address book.'),
                SubCommandDef(
                    'add <alias> [onion]', 'Save a RAM alias or add a new contact.'
                ),
                SubCommandDef(
                    'rm <onion|alias>', 'Remove from disk (active chat reverts to RAM).'
                ),
                SubCommandDef(
                    'rename <old> <new>', 'Rename a saved contact or active session.'
                ),
                SubCommandDef('clear', 'Wipe the address book completely.'),
            ],
        ),
        'profiles': CommandDef(
            name='profiles',
            usage='metor profiles',
            description='Manage isolated profiles.',
            category='Profile & Identity',
            subcommands=[
                SubCommandDef('list', 'List all isolated profiles.'),
                SubCommandDef(
                    'add <name> [--remote] [--port]', 'Create a new isolated profile.'
                ),
                SubCommandDef(
                    'rm <name> [--nuke-remote]',
                    'Remove a profile and optionally its daemon.',
                ),
                SubCommandDef('rename <old> <new>', 'Rename an existing profile.'),
                SubCommandDef('set-default <name>', 'Set the default startup profile.'),
                SubCommandDef('clear <name>', 'Wipe the SQLite database of a profile.'),
            ],
        ),
        'address': CommandDef(
            name='address',
            usage='metor address',
            description='View or cycle your hidden service address.',
            category='Profile & Identity',
            subcommands=[
                SubCommandDef('show', 'View your current hidden service address.'),
                SubCommandDef('generate', 'Generate a new hidden service address.'),
            ],
        ),
        'settings': CommandDef(
            name='settings',
            usage='metor settings set <domain.key> <val>',
            description='Configure specific domain settings.',
            category='System & Settings',
        ),
        'cleanup': CommandDef(
            name='cleanup',
            usage='metor cleanup',
            description='Kill zombie Tor processes and clear locks.',
            category='System & Settings',
        ),
        'purge': CommandDef(
            name='purge',
            usage='metor purge [--nuke-remote]',
            description='Wipe ALL profiles, keys, and databases.',
            category='System & Settings',
        ),
    }

    CHAT_COMMANDS: Dict[str, CommandDef] = {
        'connect': CommandDef(
            name='connect',
            usage='/connect <onion|alias>',
            description='Establish a new secure connection.',
            category='Session & Connection',
        ),
        'accept': CommandDef(
            name='accept',
            usage='/accept [onion|alias]',
            description='Accept a background connection request.',
            category='Session & Connection',
        ),
        'reject': CommandDef(
            name='reject',
            usage='/reject [onion|alias]',
            description='Reject a background connection request.',
            category='Session & Connection',
        ),
        'switch': CommandDef(
            name='switch',
            usage='/switch [..|<onion|alias>]',
            description="Switch focus (use '..' to remove focus).",
            category='Session & Connection',
        ),
        'end': CommandDef(
            name='end',
            usage='/end [onion|alias]',
            description='Terminate an active or pending connection.',
            category='Session & Connection',
        ),
        'fallback': CommandDef(
            name='fallback',
            usage='/fallback [onion|alias]',
            description='Force pending live messages into offline drops.',
            category='Session & Connection',
        ),
        'sessions': CommandDef(
            name='sessions',
            usage='/sessions',
            description='List all active and pending sessions.',
            category='Session & Connection',
        ),
        'inbox': CommandDef(
            name='inbox',
            usage='/inbox [onion|alias]',
            description='Check inbox counts or read drops from an alias.',
            category='Messaging & Display',
        ),
        'clear': CommandDef(
            name='clear',
            usage='/clear',
            description='Wipe the current chat display.',
            category='Messaging & Display',
        ),
        'contacts': CommandDef(
            name='contacts',
            usage='/contacts',
            description='Manage your address book in chat.',
            category='Contact Management',
            subcommands=[
                SubCommandDef('list', 'Show saved contacts and temporary RAM aliases.'),
                SubCommandDef(
                    'add <alias> [onion]',
                    'Save a RAM alias or add a new manual contact.',
                ),
                SubCommandDef(
                    'rm <onion|alias>', 'Remove from disk (active chat reverts to RAM).'
                ),
                SubCommandDef(
                    'rename <old> <new>', 'Change the name of any RAM or Disk alias.'
                ),
            ],
        ),
        'exit': CommandDef(
            name='exit',
            usage='/exit',
            description='Close the UI (Daemon stays active).',
            category='System',
        ),
    }

    @staticmethod
    def _format_line(
        indent_spaces: str, cmd: str, desc: str, target_column: int
    ) -> str:
        """
        Pads the command string so the description starts at the target column.

        Args:
            indent_spaces (str): The leading whitespace for indentation.
            cmd (str): The command syntax string.
            desc (str): The description of the command.
            target_column (int): The column index where the description should start.

        Returns:
            str: The fully formatted help line.
        """
        pad_length: int = target_column - len(indent_spaces)
        pad_length = max(pad_length, len(cmd) + 2)
        padded_cmd: str = f'{cmd:<{pad_length}}'
        return f'{indent_spaces}{Theme.CYAN}{padded_cmd}{Theme.RESET} - {desc}\n'

    @classmethod
    def show_command_help(cls, cmd: str, sub: Optional[str] = None) -> str:
        """
        Generates the isolated usage string and description for a specific command.
        Automatically routes to Chat or CLI registries based on the '/' prefix.
        Returns compactly formatted error strings without trailing newlines if the command is unknown.

        Args:
            cmd (str): The command to look up (e.g., 'history' or '/contacts').
            sub (Optional[str]): The subcommand, if any.

        Returns:
            str: The formatted isolated help text.
        """
        is_chat: bool = cmd.startswith('/')
        lookup_cmd: str = cmd.lstrip('/')
        registry: Dict[str, CommandDef] = (
            cls.CHAT_COMMANDS if is_chat else cls.CLI_COMMANDS
        )

        if lookup_cmd in registry:
            c: CommandDef = registry[lookup_cmd]
            out: str = f'\n{Theme.GREEN}Usage:{Theme.RESET} {c.usage}\n'
            out += f'{Theme.YELLOW}Description:{Theme.RESET} {c.description}\n'

            if c.subcommands:
                out += f'\n{Theme.PURPLE}Subcommands:{Theme.RESET}\n'
                for subcmd in c.subcommands:
                    base_cmd: str = c.usage.split()[0] if is_chat else c.name
                    out += f'  {base_cmd} {subcmd.usage:<30} - {subcmd.description}\n'

            return out

        if is_chat:
            return f"Unknown command: '{cmd}'."
        return f"Unknown command: '{cmd}'. Use 'metor help' to see available commands."

    @classmethod
    def show_quick_start(cls) -> str:
        """
        Generates a compact quick start guide for beginners.

        Args:
            None

        Returns:
            str: The formatted quick start menu.
        """
        out: str = f'\n{Theme.GREEN}Metor - Quick Start Guide{Theme.RESET}\n\n'
        out += 'Welcome to Metor. Here are the core commands to get you started:\n\n'

        for key in ('daemon', 'chat', 'help'):
            if key in cls.CLI_COMMANDS:
                c: CommandDef = cls.CLI_COMMANDS[key]
                out += cls._format_line('  ', c.usage, c.description, cls.DESC_COLUMN)

        out += f"\nUse {Theme.CYAN}'metor help'{Theme.RESET} to see the complete list of commands.\n"
        return out

    @classmethod
    def show_chat_help(cls, start: int = 0, intend: int = 2) -> str:
        """
        Generates the help text specific to the interactive Chat Mode dynamically.
        Renders nested subcommands automatically to maintain neat alignment.

        Args:
            start (int): The starting indentation level.
            intend (int): The number of spaces per indentation level.

        Returns:
            str: The formatted chat help text.
        """
        ind: str = ' ' * intend * start
        sub_ind: str = ' ' * intend * (start + 1)
        sub_sub_ind: str = ' ' * intend * (start + 2)

        out: str = (
            f'{ind}{Theme.PURPLE}Chat Mode:{Theme.RESET}\n\n'
            f'{ind}* The [alias] can be omitted if you are currently focused on a peer.\n'
            f'{ind}* Any other text entered is sent to the focused peer.\n\n'
        )

        for cat in cls.CHAT_CATEGORIES:
            out += f'{sub_ind}{Theme.PURPLE}{cat}:{Theme.RESET}\n'
            for cmd in cls.CHAT_COMMANDS.values():
                if cmd.category == cat:
                    out += cls._format_line(
                        sub_sub_ind, cmd.usage, cmd.description, cls.DESC_COLUMN
                    )
                    if cmd.subcommands:
                        for subcmd in cmd.subcommands:
                            out += cls._format_line(
                                sub_sub_ind + '  ',
                                subcmd.usage,
                                subcmd.description,
                                cls.DESC_COLUMN,
                            )
            out += '\n'

        return out.rstrip('\n') + '\n'

    @classmethod
    def show_main_help(cls, start: int = 0, intend: int = 2) -> str:
        """
        Generates the exhaustive help text for the main CLI application dynamically.
        Renders nested subcommands automatically to maintain neat alignment.

        Args:
            start (int): The starting indentation level.
            intend (int): The number of spaces per indentation level.

        Returns:
            str: The formatted main help text.
        """
        ind: str = ' ' * intend * start
        sub_ind: str = ' ' * intend * (start + 1)
        sub_sub_ind: str = ' ' * intend * (start + 2)

        out: str = (
            f'\n{ind}{Theme.GREEN}Metor - A Tor Messenger Framework{Theme.RESET}\n\n'
            f'{ind}Usage: metor [-p PROFILE] <command> [subcommand] [args...]\n\n'
        )

        for cat in cls.CLI_CATEGORIES:
            out += f'{ind}{Theme.YELLOW}{cat}:{Theme.RESET}\n'
            for cmd in cls.CLI_COMMANDS.values():
                if cmd.category == cat:
                    out += cls._format_line(
                        sub_ind, cmd.usage, cmd.description, cls.DESC_COLUMN
                    )
                    if cmd.subcommands:
                        for subcmd in cmd.subcommands:
                            out += cls._format_line(
                                sub_sub_ind,
                                subcmd.usage,
                                subcmd.description,
                                cls.DESC_COLUMN,
                            )
            out += '\n'

        out += f'{ind}{UIPresenter.get_divider_string(3, add_spaces=True)}\n\n'
        out += cls.show_chat_help(start, intend)
        return out
