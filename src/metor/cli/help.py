"""
Module providing static help texts, CLI command documentation, and a centralized Command Registry.
Enforces the DRY principle by dynamically generating help menus from strongly-typed dataclasses,
supporting nested subcommands for clean terminal alignment.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Local Package Imports
from metor.cli.theme import Theme


@dataclass
class SubCommandDef:
    """
    Strongly typed definition of a nested subcommand.

    Args:
        usage (str): The CLI usage pattern.
        description (str): A brief description of the command.
    """

    usage: str
    description: str


@dataclass
class CommandDef:
    """
    Strongly typed definition of a CLI or Chat command.

    Args:
        name (str): The primary command invocation.
        usage (str): The detailed usage syntax.
        description (str): Explains the command behavior.
        category (str): The help menu category group.
        subcommands (List[SubCommandDef]): Optional list of sub-operations.
    """

    name: str
    usage: str
    description: str
    category: str
    subcommands: List[SubCommandDef] = field(default_factory=list)


class Help:
    """Static help generator utilizing a DRY data-driven command registry."""

    DESC_COLUMN: int = 58
    SUBCOMMAND_DESC_COLUMN: int = 58

    CLI_CATEGORIES: List[str] = [
        'Global Options',
        'Core Operations',
        'Messaging & History',
        'Contact Management',
        'Profile & Identity',
        'System & Settings',
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
        'version': CommandDef(
            name='version',
            usage='metor version | metor --version',
            description='Show the coordinated application version.',
            category='Core Operations',
        ),
        'daemon': CommandDef(
            name='daemon',
            usage='metor daemon [--locked]',
            description='Start the Tor & IPC engine, optionally locked (IPC-only).',
            category='Core Operations',
        ),
        'unlock': CommandDef(
            name='unlock',
            usage='metor unlock',
            description='Unlock a locked daemon instance over IPC.',
            category='Core Operations',
        ),
        'chat': CommandDef(
            name='chat',
            usage='metor chat [--start-daemon|--no-start-daemon]',
            description='Enter the interactive multi-chat UI and optionally override local daemon autostart for this invocation.',
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
            description='Check unread message counts or read them.',
            category='Messaging & History',
        ),
        'messages': CommandDef(
            name='messages',
            usage='metor messages',
            description='View or delete stored message history with a contact.',
            category='Messaging & History',
            subcommands=[
                SubCommandDef(
                    'show <onion|alias> [limit]',
                    'View stored message history.',
                ),
                SubCommandDef(
                    'clear [onion|alias] [--non-contacts]',
                    'Delete message history.',
                ),
            ],
        ),
        'history': CommandDef(
            name='history',
            usage='metor history',
            description='View projected history or inspect the raw transport ledger.',
            category='Messaging & History',
            subcommands=[
                SubCommandDef(
                    'show [onion|alias] [limit] [--raw]',
                    'View projected history or use `--raw` for the transport ledger.',
                ),
                SubCommandDef('clear [onion|alias]', 'Wipe the connection event log.'),
            ],
        ),
        'transport': CommandDef(
            name='transport',
            usage='metor transport [onion|alias]',
            description='Show the current transport state for one peer or the whole daemon.',
            category='Messaging & History',
        ),
        'contacts': CommandDef(
            name='contacts',
            usage='metor contacts',
            description='Manage your address book.',
            category='Contact Management',
            subcommands=[
                SubCommandDef('list', 'List saved and discovered peers.'),
                SubCommandDef(
                    'add <alias> [onion]',
                    'Promote a discovered peer or add a new contact.',
                ),
                SubCommandDef(
                    'rm <onion|alias>',
                    'Anonymize (and demote) a saved or discovered peer.',
                ),
                SubCommandDef(
                    'rename <old> <new>', 'Rename a saved or discovered peer.'
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
                    'add <name> [--remote] [--port] [--plaintext]',
                    'Create a new isolated profile.',
                ),
                SubCommandDef(
                    'migrate <name> --to <encrypted|plaintext>',
                    'Migrate a local profile between encrypted and plaintext.',
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
            usage='metor settings',
            description='Configure global settings (affects all profiles).',
            category='System & Settings',
            subcommands=[
                SubCommandDef('get <domain.key>', 'Retrieve a global setting.'),
                SubCommandDef('set <domain.key> <val>', 'Update a global setting.'),
                SubCommandDef('list', 'List all current global settings.'),
            ],
        ),
        'config': CommandDef(
            name='config',
            usage='metor config',
            description='Configure profile-specific overrides.',
            category='System & Settings',
            subcommands=[
                SubCommandDef(
                    'get <domain.key>', 'Retrieve the resolved value for this profile.'
                ),
                SubCommandDef(
                    'set <domain.key> <val>', 'Override a global setting locally.'
                ),
                SubCommandDef('list', 'List the effective settings for this profile.'),
                SubCommandDef(
                    'sync', 'Wipe all profile overrides to restore global defaults.'
                ),
            ],
        ),
        'cleanup': CommandDef(
            name='cleanup',
            usage='metor cleanup [--force]',
            description='Kill managed daemon/Tor processes and clear daemon state.',
            category='System & Settings',
        ),
        'purge': CommandDef(
            name='purge',
            usage='metor purge [--nuke-remote]',
            description='Wipe ALL profiles, keys, and databases.',
            category='System & Settings',
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
        Returns compactly formatted error strings without trailing newlines if the command is unknown.

        Args:
            cmd (str): The command to look up (e.g., 'history' or '/contacts').
            sub (Optional[str]): The subcommand, if any.

        Returns:
            str: The formatted isolated help text.
        """
        if cmd in cls.CLI_COMMANDS:
            c: CommandDef = cls.CLI_COMMANDS[cmd]
            out: str = f'\n{Theme.GREEN}Usage:{Theme.RESET} {c.usage}\n'
            out += f'{Theme.YELLOW}Description:{Theme.RESET} {c.description}\n'

            if c.subcommands:
                out += f'\n{Theme.PURPLE}Subcommands:{Theme.RESET}\n'
                for subcmd in c.subcommands:
                    out += cls._format_line(
                        '  ',
                        f'{c.name} {subcmd.usage}',
                        subcmd.description,
                        cls.SUBCOMMAND_DESC_COLUMN,
                    )

            return out

        return f"Unknown command: '{cmd}'. Use 'metor help' to see available commands."

    @classmethod
    def show_chat_launcher_help(cls) -> str:
        """Builds chat launcher help without importing or initializing a UI.

        Args:
            None

        Returns:
            str: Frontend-neutral chat launcher usage.
        """
        return (
            f'\n{Theme.GREEN}Usage:{Theme.RESET} metor chat '
            '[--ui FRONTEND] [--list-uis] '
            '[--start-daemon|--no-start-daemon]\n'
            f'{Theme.YELLOW}Description:{Theme.RESET} Launch one independently '
            'installed interactive frontend.\n\n'
            f'{Theme.PURPLE}Options:{Theme.RESET}\n'
            + cls._format_line(
                '  ', '--ui FRONTEND', 'Select the installed frontend ID.', 32
            )
            + cls._format_line(
                '  ', '--list-uis', 'List installed frontend metadata.', 32
            )
            + cls._format_line(
                '  ', '-p, --profile PROFILE', 'Select the local profile.', 32
            )
            + cls._format_line('  ', '--remote', 'Use the selected remote profile.', 32)
            + cls._format_line('  ', '--port PORT', 'Override the daemon IPC port.', 32)
            + cls._format_line(
                '  ', '--start-daemon', 'Start a missing local daemon.', 32
            )
            + cls._format_line(
                '  ', '--no-start-daemon', 'Do not start a missing local daemon.', 32
            )
        )

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
                                cls.SUBCOMMAND_DESC_COLUMN,
                            )
            out += '\n'

        return out
