"""
Module providing static help texts and CLI command documentation.
"""

# Local Package Imports
from metor.ui.theme import Theme


class Help:
    """Static help texts with professional CLI formatting."""

    DESC_COLUMN: int = 55

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

    @staticmethod
    def show_chat_help(start: int = 0, intend: int = 2) -> str:
        """
        Generates the help text specific to the interactive Chat Mode.

        Args:
            start (int): The starting indentation level.
            intend (int): The number of spaces per indentation level.

        Returns:
            str: The formatted chat help text.
        """
        ind: str = ' ' * intend * start
        sub_ind: str = ' ' * intend * (start + 1)
        sub_sub_ind: str = ' ' * intend * (start + 2)

        return (
            f'{ind}{Theme.PURPLE}Chat Mode:{Theme.RESET}\n\n'
            + f'{ind}* The [alias] can be omitted if you are currently focused on a peer.\n'
            + f'{ind}* Any other text entered is sent to the focused peer.\n\n'
            + f'{sub_ind}{Theme.PURPLE}Core Commands:{Theme.RESET}\n'
            + Help._format_line(
                sub_sub_ind,
                '/connect <onion|alias>',
                'Establish a new secure connection.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_sub_ind,
                '/accept [alias]',
                'Accept a background connection request.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_sub_ind,
                '/reject [alias]',
                'Reject a background connection request.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_sub_ind,
                '/switch [..|<onion|alias>]',
                "Switch focus (use '..' to remove focus).",
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_sub_ind,
                '/end [alias]',
                'Terminate an active or pending connection.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_sub_ind,
                '/sessions',
                'List all active and pending sessions.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_sub_ind,
                '/clear',
                'Wipe the current chat display.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_sub_ind,
                '/exit',
                'Close the UI (Daemon stays active).\n',
                Help.DESC_COLUMN,
            )
            + f'{sub_ind}{Theme.PURPLE}Contact Management:{Theme.RESET}\n'
            + Help._format_line(
                sub_sub_ind,
                '/contacts list',
                'Show saved contacts and temporary RAM aliases.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_sub_ind,
                '/contacts add [alias] [onion]',
                'Save a RAM alias or add a new manual contact.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_sub_ind,
                '/contacts rm [alias]',
                'Remove from disk (active chat reverts to RAM).',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_sub_ind,
                '/contacts rename [old] <new>',
                'Change the name of any RAM or Disk alias.',
                Help.DESC_COLUMN,
            )
        )

    @staticmethod
    def show_main_help(start: int = 0, intend: int = 2) -> str:
        """
        Generates the help text for the main CLI application.

        Args:
            start (int): The starting indentation level.
            intend (int): The number of spaces per indentation level.

        Returns:
            str: The formatted main help text.
        """
        ind: str = ' ' * intend * start
        sub_ind: str = ' ' * intend * (start + 1)

        return (
            '\n'
            + f'{ind}{Theme.GREEN}Metor - Secure Tor Messenger{Theme.RESET}\n\n'
            + f'{ind}Usage: metor [-p PROFILE] <command> [subcommand] [args...]\n\n'
            + f'{ind}{Theme.YELLOW}Global Options:{Theme.RESET}\n'
            + Help._format_line(
                sub_ind,
                '-p, --profile <name>',
                "Set the active profile (default: 'default').\n",
                Help.DESC_COLUMN,
            )
            + f'{ind}{Theme.YELLOW}Core Commands:{Theme.RESET}\n'
            + Help._format_line(
                sub_ind, 'metor help', 'Show this help overview.', Help.DESC_COLUMN
            )
            + Help._format_line(
                sub_ind,
                'metor daemon',
                'Start the background Tor & IPC engine.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor unlock <password>',
                'Unlock an encrypted daemon instance over IPC.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor settings set <domain.key> <val>',
                'Configure specific domain settings (ui, daemon, data, security).',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor chat',
                'Enter the interactive multi-chat UI.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor cleanup',
                'Kill zombie Tor processes and clear locks.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor purge [--nuke-remote]',
                'Wipe ALL profiles, keys, and databases.\n',
                Help.DESC_COLUMN,
            )
            + f'{ind}{Theme.YELLOW}Asynchronous Messaging (Headless):{Theme.RESET}\n'
            + Help._format_line(
                sub_ind,
                'metor send <alias> "msg"',
                'Drop an offline message to a contact.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor inbox',
                'Check for unread offline messages.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor read <alias>',
                'Read and clear unread messages from an alias.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor messages [show] <alias> [limit]',
                'View past chat history with a contact.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor messages clear [alias] [--non-contacts]',
                'Delete message history (or only from unsaved peers).\n',
                Help.DESC_COLUMN,
            )
            + f'{ind}{Theme.YELLOW}Profile & Identity:{Theme.RESET}\n'
            + Help._format_line(
                sub_ind,
                'metor address [show|generate]',
                'View or cycle your hidden service address.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor profiles [list|add]',
                'List or create isolated profiles.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor profiles rm <name> [--nuke-remote]',
                'Remove a profile and optionally its remote daemon.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor profiles [rename|set-default|clear]',
                'Manage existing profile configurations.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor history [show|clear] [alias] [limit]',
                'View or wipe the connection event log.\n',
                Help.DESC_COLUMN,
            )
            + f'{ind}{Theme.YELLOW}External Contact Management:{Theme.RESET}\n'
            + Help._format_line(
                sub_ind,
                'metor contacts [list]',
                'List all contacts in your address book.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor contacts add <alias> [onion]',
                'Add a manual contact or save a running RAM alias.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor contacts rm <alias>',
                'Delete contact (active sessions revert to RAM).',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor contacts rename <old> <new>',
                'Rename a saved contact or active session.',
                Help.DESC_COLUMN,
            )
            + Help._format_line(
                sub_ind,
                'metor contacts clear',
                'Wipe the address book completely.\n',
                Help.DESC_COLUMN,
            )
            + f'{ind}- - -\n\n'
            + Help.show_chat_help(start, intend)
        )
