"""
Module defining the command parser and dispatcher for UI slash commands.
"""

from typing import List, Optional

from metor.core.api import (
    DisconnectCommand,
    ConnectCommand,
    AcceptCommand,
    RejectCommand,
    SwitchCommand,
    GetConnectionsCommand,
    GetContactsListCommand,
    AddContactCommand,
    RemoveContactCommand,
    RenameContactCommand,
    GetInboxCommand,
    MarkReadCommand,
    FallbackCommand,
)
from metor.ui import Help

# Local Package Imports
from metor.ui.chat.renderer import Renderer
from metor.ui.chat.ipc import IpcClient
from metor.ui.chat.session import Session
from metor.ui.chat.models import ChatMessageType


class CommandDispatcher:
    """Parses raw text input and dispatches corresponding IpcCommands."""

    def __init__(self, ipc: IpcClient, session: Session, renderer: Renderer) -> None:
        """
        Initializes the dispatcher with required dependencies.

        Args:
            ipc (IpcClient): The active IPC client connection.
            session (Session): The current UI state manager.
            renderer (Renderer): The UI renderer for printing errors/usages.

        Returns:
            None
        """
        self._ipc: IpcClient = ipc
        self._session: Session = session
        self._renderer: Renderer = renderer

    def dispatch(self, input_str: str) -> bool:
        """
        Analyzes a user string, extracts parameters, and triggers daemon actions.
        Dynamically fetches usage strings from the centralized Help registry if arguments are missing.

        Args:
            input_str (str): The raw string typed by the user.

        Returns:
            bool: True if a command was successfully resolved and fired, False otherwise.
        """
        parts: List[str] = input_str.split()
        if not parts:
            return False

        cmd: str = parts[0]
        arg: Optional[str] = parts[1].lower() if len(parts) > 1 else None

        if cmd == '/end':
            target: Optional[str] = arg if arg else self._session.focused_alias
            if target:
                self._ipc.send_command(DisconnectCommand(target=target))
                if target == self._session.focused_alias:
                    self._session.focused_alias = None
                    self._renderer.set_focus(None)
            else:
                self._renderer.print_message(
                    'No focused session to end.', msg_type=ChatMessageType.SYSTEM
                )

        elif cmd == '/connect':
            if arg:
                if self._session.focused_alias is None:
                    self._session.pending_focus_target = arg
                self._ipc.send_command(ConnectCommand(target=arg))
            else:
                self._renderer.print_message(
                    Help.show_command_help(cmd).strip(), msg_type=ChatMessageType.SYSTEM
                )

        elif cmd == '/accept':
            if arg:
                if self._session.focused_alias is None:
                    self._session.pending_focus_target = arg
                self._ipc.send_command(AcceptCommand(target=arg))
            else:
                self._renderer.print_message(
                    Help.show_command_help(cmd).strip(), msg_type=ChatMessageType.SYSTEM
                )

        elif cmd == '/reject':
            if arg:
                self._ipc.send_command(RejectCommand(target=arg))
            else:
                self._renderer.print_message(
                    Help.show_command_help(cmd).strip(), msg_type=ChatMessageType.SYSTEM
                )

        elif cmd == '/switch':
            if arg:
                if arg == '..':
                    self._ipc.send_command(SwitchCommand(target=None))
                else:
                    self._ipc.send_command(SwitchCommand(target=arg))
            else:
                self._renderer.print_message(
                    Help.show_command_help(cmd).strip(), msg_type=ChatMessageType.SYSTEM
                )

        elif cmd == '/fallback':
            target = arg if arg else self._session.focused_alias
            if target:
                self._ipc.send_command(FallbackCommand(target=target))
            else:
                self._renderer.print_message(
                    Help.show_command_help(cmd).strip(), msg_type=ChatMessageType.SYSTEM
                )

        elif cmd == '/inbox':
            if arg:
                self._ipc.send_command(MarkReadCommand(target=arg))
            else:
                self._ipc.send_command(GetInboxCommand(cli_mode=True))

        elif cmd == '/sessions':
            self._ipc.send_command(GetConnectionsCommand())

        elif cmd.startswith('/contacts'):
            self._dispatch_contacts(cmd, parts)

        else:
            return False

        return True

    def _dispatch_contacts(self, cmd: str, parts: List[str]) -> None:
        """
        Helper routing specifically for /contacts subcommands.
        Dynamically fetches usage strings from the centralized Help registry if arguments are missing.

        Args:
            cmd (str): The base command invoked (e.g. '/contacts').
            parts (List[str]): The space-separated components of the typed command.

        Returns:
            None
        """
        subcmd: str = parts[1] if len(parts) > 1 else 'list'

        if subcmd == 'list':
            self._ipc.send_command(GetContactsListCommand(chat_mode=True))
        elif subcmd == 'add':
            if len(parts) == 2 and self._session.focused_alias:
                self._ipc.send_command(
                    AddContactCommand(alias=self._session.focused_alias)
                )
            elif len(parts) == 3:
                self._ipc.send_command(AddContactCommand(alias=parts[2].lower()))
            elif len(parts) == 4:
                self._ipc.send_command(
                    AddContactCommand(alias=parts[2].lower(), onion=parts[3])
                )
            else:
                self._renderer.print_message(
                    Help.show_command_help(cmd).strip(),
                    msg_type=ChatMessageType.SYSTEM,
                )
        elif subcmd in ('rm', 'remove'):
            if len(parts) == 2 and self._session.focused_alias:
                self._ipc.send_command(
                    RemoveContactCommand(alias=self._session.focused_alias)
                )
            elif len(parts) == 3:
                self._ipc.send_command(RemoveContactCommand(alias=parts[2].lower()))
            else:
                self._renderer.print_message(
                    Help.show_command_help(cmd).strip(), msg_type=ChatMessageType.SYSTEM
                )
        elif subcmd == 'rename':
            if len(parts) == 3 and self._session.focused_alias:
                old_alias, new_alias = self._session.focused_alias, parts[2].lower()
            elif len(parts) == 4:
                old_alias, new_alias = parts[2].lower(), parts[3].lower()
            else:
                self._renderer.print_message(
                    Help.show_command_help(cmd).strip(), msg_type=ChatMessageType.SYSTEM
                )
                return
            self._ipc.send_command(
                RenameContactCommand(old_alias=old_alias, new_alias=new_alias)
            )
        else:
            self._renderer.print_message(
                Help.show_command_help(cmd).strip(), msg_type=ChatMessageType.SYSTEM
            )
