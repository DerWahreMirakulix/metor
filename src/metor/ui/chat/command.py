"""Module defining the command parser and dispatcher for UI slash commands."""

from typing import List, Optional

from metor.core.api import (
    AcceptCommand,
    AddContactCommand,
    ConnectCommand,
    DisconnectCommand,
    FallbackCommand,
    GetConnectionsCommand,
    GetContactsListCommand,
    GetInboxCommand,
    MarkReadCommand,
    RejectCommand,
    RemoveContactCommand,
    RenameContactCommand,
    RetunnelCommand,
    SwitchCommand,
)
from metor.ui import Help
from metor.ui.models import StatusTone

from metor.ui.chat.ipc import IpcClient
from metor.ui.chat.models import ChatMessageType
from metor.ui.chat.renderer import Renderer
from metor.ui.chat.session import Session


class CommandDispatcher:
    """Parses raw text input and dispatches corresponding IPC commands."""

    def __init__(self, ipc: IpcClient, session: Session, renderer: Renderer) -> None:
        """Initializes the dispatcher with required dependencies.

        Args:
            ipc (IpcClient): The active IPC client connection.
            session (Session): The current UI state manager.
            renderer (Renderer): The UI renderer for printing errors and usage.

        Returns:
            None
        """
        self._ipc: IpcClient = ipc
        self._session: Session = session
        self._renderer: Renderer = renderer

    def _remember_pending_connect_focus(self, target: str) -> None:
        """
        Stores the next successful outbound connect target for auto-focus.

        Args:
            target (str): The requested alias or onion.

        Returns:
            None
        """
        if self._session.focused_alias is not None:
            return

        if self._session.pending_focus_target not in (None, target):
            return

        self._session.pending_focus_target = target

    def _remember_pending_accept_focus(self, target: str) -> None:
        """
        Stores the next successful accept target for auto-focus.

        Args:
            target (str): The requested alias.

        Returns:
            None
        """
        if self._session.focused_alias is not None:
            return

        if self._session.pending_accept_focus_target not in (None, target):
            return

        self._session.pending_accept_focus_target = target

    def _resolve_pending_target(self) -> Optional[str]:
        """
        Resolves one implicit pending-session target when the command omits it.

        Args:
            None

        Returns:
            Optional[str]: The inferred alias, or None when ambiguous.
        """
        focused_alias: Optional[str] = self._session.focused_alias
        if focused_alias and focused_alias in self._session.pending_connections:
            return focused_alias

        if len(self._session.pending_connections) == 1:
            return self._session.pending_connections[0]

        return None

    def _print_system(self, text: str) -> None:
        """Prints a chat status line with system tone.

        Args:
            text (str): The text to render.

        Returns:
            None
        """
        self._renderer.print_message(
            text,
            msg_type=ChatMessageType.STATUS,
            tone=StatusTone.SYSTEM,
        )

    def dispatch(self, input_str: str) -> bool:
        """Analyzes a user string, extracts parameters, and triggers daemon actions.

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
            else:
                self._print_system('No focused session to end.')
        elif cmd == '/connect':
            if arg:
                self._remember_pending_connect_focus(arg)
                self._ipc.send_command(ConnectCommand(target=arg))
            else:
                self._print_system(Help.show_command_help(cmd).strip())
        elif cmd == '/accept':
            target = arg if arg else self._resolve_pending_target()
            if target:
                self._remember_pending_accept_focus(target)
                self._ipc.send_command(AcceptCommand(target=target))
            else:
                self._print_system(Help.show_command_help(cmd).strip())
        elif cmd == '/reject':
            if arg:
                self._ipc.send_command(RejectCommand(target=arg))
            else:
                self._print_system(Help.show_command_help(cmd).strip())
        elif cmd == '/switch':
            if arg:
                if arg == '..':
                    self._ipc.send_command(SwitchCommand(target=None))
                else:
                    self._ipc.send_command(SwitchCommand(target=arg))
            else:
                self._print_system(Help.show_command_help(cmd).strip())
        elif cmd == '/fallback':
            target = arg if arg else self._session.focused_alias
            if target:
                self._ipc.send_command(FallbackCommand(target=target))
            else:
                self._print_system(Help.show_command_help(cmd).strip())
        elif cmd == '/retunnel':
            target = arg if arg else self._session.focused_alias
            if target:
                self._ipc.send_command(RetunnelCommand(target=target))
            else:
                self._print_system(Help.show_command_help(cmd).strip())
        elif cmd == '/inbox':
            if arg:
                self._ipc.send_command(MarkReadCommand(target=arg))
            else:
                self._ipc.send_command(GetInboxCommand())
        elif cmd == '/sessions':
            self._ipc.send_command(GetConnectionsCommand())
        elif cmd.startswith('/contacts'):
            self._dispatch_contacts(cmd, parts)
        else:
            return False

        return True

    def _dispatch_contacts(self, cmd: str, parts: List[str]) -> None:
        """Routes `/contacts` subcommands.

        Args:
            cmd (str): The base command invoked.
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
                self._print_system(Help.show_command_help(cmd).strip())
        elif subcmd in ('rm', 'remove'):
            if len(parts) == 2 and self._session.focused_alias:
                self._ipc.send_command(
                    RemoveContactCommand(alias=self._session.focused_alias)
                )
            elif len(parts) == 3:
                self._ipc.send_command(RemoveContactCommand(alias=parts[2].lower()))
            else:
                self._print_system(Help.show_command_help(cmd).strip())
        elif subcmd == 'rename':
            if len(parts) == 3 and self._session.focused_alias:
                old_alias, new_alias = self._session.focused_alias, parts[2].lower()
            elif len(parts) == 4:
                old_alias, new_alias = parts[2].lower(), parts[3].lower()
            else:
                self._print_system(Help.show_command_help(cmd).strip())
                return
            self._ipc.send_command(
                RenameContactCommand(old_alias=old_alias, new_alias=new_alias)
            )
        else:
            self._print_system(Help.show_command_help(cmd).strip())
