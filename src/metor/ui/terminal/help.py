"""
Terminal-owned interactive chat command definitions and help rendering.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Local Package Imports
from metor.ui.terminal.theme import Theme


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
    Strongly typed definition of an interactive chat command.

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

    CHAT_CATEGORIES: List[str] = [
        'Session & Connection',
        'Messaging & Display',
        'Contact Management',
        'System',
    ]

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
        'transport': CommandDef(
            name='transport',
            usage='/transport [onion|alias]',
            description='Show the current transport state for one peer or the focused session.',
            category='Session & Connection',
        ),
        'retunnel': CommandDef(
            name='retunnel',
            usage='/retunnel [onion|alias]',
            description='Force Tor circuit rotation (NEWNYM) and reconnect.',
            category='Session & Connection',
        ),
        'inbox': CommandDef(
            name='inbox',
            usage='/inbox [onion|alias]',
            description='Check inbox counts or read unread messages from an alias.',
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
                SubCommandDef('list', 'List saved and discovered peers.'),
                SubCommandDef(
                    'add <alias> [onion]',
                    'Promote a discovered peer or add a new manual contact.',
                ),
                SubCommandDef(
                    'rm <onion|alias>',
                    'Anonymize (and demote) a saved or discovered peer.',
                ),
                SubCommandDef(
                    'rename <old> <new>',
                    'Change the name of any saved or discovered peer.',
                ),
            ],
        ),
        'help': CommandDef(
            name='help',
            usage='/help',
            description='Show the chat command overview.',
            category='System',
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
        Generates isolated usage for a Terminal interactive command.
        Returns compactly formatted error strings without trailing newlines if the command is unknown.

        Args:
            cmd (str): The command to look up (e.g., 'history' or '/contacts').
            sub (Optional[str]): The subcommand, if any.

        Returns:
            str: The formatted isolated help text.
        """
        lookup_cmd: str = cmd.lstrip('/')
        registry: Dict[str, CommandDef] = cls.CHAT_COMMANDS

        if lookup_cmd in registry:
            c: CommandDef = registry[lookup_cmd]
            out: str = f'\n{Theme.GREEN}Usage:{Theme.RESET} {c.usage}\n'
            out += f'{Theme.YELLOW}Description:{Theme.RESET} {c.description}\n'

            if c.subcommands:
                out += f'\n{Theme.PURPLE}Subcommands:{Theme.RESET}\n'
                for subcmd in c.subcommands:
                    base_cmd: str = c.usage.split()[0]
                    out += cls._format_line(
                        '  ',
                        f'{base_cmd} {subcmd.usage}',
                        subcmd.description,
                        cls.SUBCOMMAND_DESC_COLUMN,
                    )

            return out

        return f"Unknown command: '{cmd}'."

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
                                cls.SUBCOMMAND_DESC_COLUMN,
                            )
            out += '\n'

        return out.rstrip('\n') + '\n'
