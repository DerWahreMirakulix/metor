"""
Module providing the interactive Chat User Interface connected to the local Daemon.
"""

import socket
import threading
import secrets
import json
import sys
import os
import signal
from typing import List, Dict, Optional, Any

from metor.ui.help import Help
from metor.data.profile import ProfileManager
from metor.ui.cli import CommandLineInput
from metor.data.contact import ContactManager
from metor.data.history import HistoryManager
from metor.ui.theme import Theme
from metor.utils.constants import Constants
from metor.utils.helper import clean_onion
from metor.core.api import IpcCommand, IpcEvent, Action, EventType


class Chat:
    """The UI frontend. Connects to the local Metor Daemon via strongly-typed IPC."""

    def __init__(
        self,
        pm: ProfileManager,
        cm: ContactManager,
        hm: HistoryManager,
        cli: CommandLineInput,
    ) -> None:
        """Initializes the Chat UI."""
        self._pm: ProfileManager = pm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._cli: CommandLineInput = cli

        self._ipc_socket: Optional[socket.socket] = None
        self._my_onion: str = 'unknown'
        self._focused_alias: Optional[str] = None
        self._pending_focus_target: Optional[str] = None

        self._stop_flag: threading.Event = threading.Event()
        self._init_event: threading.Event = threading.Event()
        self._conn_event: threading.Event = threading.Event()

        self._header_active: List[str] = []
        self._header_pending: List[str] = []
        self._header_contacts: List[str] = []

    def run(self) -> None:
        """Starts the main chat UI loop, establishes IPC connection, and handles inputs."""
        ipc_port: Optional[int] = self._pm.get_daemon_port()
        if not ipc_port:
            self._cli.print_message(
                "Daemon is not running! Use 'metor daemon' to start it.",
                msg_type='system',
            )
            return

        try:
            self._ipc_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._ipc_socket.connect((Constants.LOCALHOST, ipc_port))
        except Exception:
            self._cli.print_message(
                'Could not connect to Daemon. Is it running?', msg_type='system'
            )
            return

        threading.Thread(target=self._ipc_listener, daemon=True).start()

        self._send_cmd(IpcCommand(action=Action.INIT))
        self._init_event.wait(timeout=2.0)

        self._print_header()

        try:
            while True:
                user_input: str = self._cli.read_line()

                if user_input == '':
                    self._cli.print_prompt()
                elif user_input.startswith('/'):
                    if user_input == '/clear':
                        self._print_header(clear_screen=True)
                    elif user_input == '/connections':
                        self._send_cmd(IpcCommand(action=Action.GET_CONNECTIONS))
                    elif user_input == '/exit':
                        break
                    elif user_input.startswith('/contacts'):
                        self._handle_contacts_command(user_input.split())
                    else:
                        command_found: bool = self._handle_network_command(
                            user_input.split()
                        )
                        if not command_found:
                            self._cli.print_message(
                                f"Unknown command: '{user_input}'", msg_type='system'
                            )
                else:
                    self._send_chat_message(user_input)

        except KeyboardInterrupt:
            self._cli.clear_input_area()
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        """Helper to safely kill all threads, close sockets, and exit the UI without breaking the terminal."""
        self._stop_flag.set()
        try:
            if self._ipc_socket:
                self._ipc_socket.close()
        except Exception:
            pass

        if threading.current_thread() is threading.main_thread():
            sys.exit(0)
        else:
            os.kill(os.getpid(), signal.SIGINT)

    def _handle_network_command(self, parts: List[str]) -> bool:
        """Dispatches all network-related commands."""
        cmd: str = parts[0]
        arg: Optional[str] = parts[1].lower() if len(parts) > 1 else None

        if cmd == '/end':
            target = arg if arg else self._focused_alias
            if target:
                self._send_cmd(IpcCommand(action=Action.DISCONNECT, target=target))
            else:
                self._cli.print_message(
                    'No active connection to end.', msg_type='system'
                )

        elif cmd == '/connect':
            if arg:
                self._pending_focus_target = arg
                self._send_cmd(IpcCommand(action=Action.CONNECT, target=arg))
            else:
                self._cli.print_message(
                    'Usage: "/connect <onion|alias>".', msg_type='system'
                )

        elif cmd == '/accept':
            if arg:
                if self._focused_alias is None:
                    self._pending_focus_target = arg
                self._send_cmd(IpcCommand(action=Action.ACCEPT, target=arg))
            else:
                self._cli.print_message('Usage: "/accept [alias]".', msg_type='system')

        elif cmd == '/reject':
            if arg:
                self._send_cmd(IpcCommand(action=Action.REJECT, target=arg))
            else:
                self._cli.print_message('Usage: "/reject [alias]".', msg_type='system')

        elif cmd == '/switch':
            if arg:
                if arg == '..':
                    self._switch_focus(None)
                else:
                    self._send_cmd(IpcCommand(action=Action.SWITCH, target=arg))
            else:
                self._cli.print_message(
                    'Usage: "/switch [..|alias]".', msg_type='system'
                )

        else:
            return False

        return True

    def _handle_contacts_command(self, parts: List[str]) -> None:
        """Dispatches all contact-related commands."""
        subcmd: str = parts[1] if len(parts) > 1 else 'list'

        if subcmd == 'list':
            self._send_cmd(IpcCommand(action=Action.GET_CONTACTS_LIST, chat_mode=True))

        elif subcmd == 'add':
            if len(parts) == 2 and self._focused_alias:
                self._send_cmd(
                    IpcCommand(action=Action.ADD_CONTACT, alias=self._focused_alias)
                )
            elif len(parts) == 3:
                self._send_cmd(
                    IpcCommand(action=Action.ADD_CONTACT, alias=parts[2].lower())
                )
            elif len(parts) == 4:
                self._send_cmd(
                    IpcCommand(
                        action=Action.ADD_CONTACT,
                        alias=parts[2].lower(),
                        onion=parts[3],
                    )
                )
            else:
                self._cli.print_message(
                    'Usage: "/contacts add [<alias>] [<onion>]"', msg_type='system'
                )

        elif subcmd in ('rm', 'remove'):
            if len(parts) == 2 and self._focused_alias:
                self._send_cmd(
                    IpcCommand(action=Action.REMOVE_CONTACT, alias=self._focused_alias)
                )
            elif len(parts) == 3:
                self._send_cmd(
                    IpcCommand(action=Action.REMOVE_CONTACT, alias=parts[2].lower())
                )
            else:
                self._cli.print_message(
                    'Usage: "/contacts rm [<alias>]"', msg_type='system'
                )

        elif subcmd == 'rename':
            if len(parts) == 3 and self._focused_alias:
                old_alias: str = self._focused_alias
                new_alias: str = parts[2].lower()
            elif len(parts) == 4:
                old_alias = parts[2].lower()
                new_alias = parts[3].lower()
            else:
                self._cli.print_message(
                    'Usage: "/contacts rename [<old>] <new>"', msg_type='system'
                )
                return
            self._send_cmd(
                IpcCommand(
                    action=Action.RENAME_CONTACT,
                    old_alias=old_alias,
                    new_alias=new_alias,
                )
            )
        else:
            self._cli.print_message(
                'Usage: "/contacts [list|add|rm|rename] ..options".', msg_type='system'
            )

    def _send_chat_message(self, msg_text: str) -> None:
        """Sends a regular text message to the currently focused peer."""
        if self._focused_alias:
            msg_id: str = secrets.token_hex(4)
            self._send_cmd(
                IpcCommand(
                    action=Action.MSG,
                    target=self._focused_alias,
                    text=msg_text,
                    msg_id=msg_id,
                )
            )
            self._cli.print_message(
                msg_text, msg_type='self', alias=self._focused_alias, msg_id=msg_id
            )
        else:
            self._cli.print_message(
                'No active focus. Use /switch or /connect.', msg_type='system'
            )

    def _send_cmd(self, cmd: IpcCommand) -> None:
        """Serializes and sends an IpcCommand object over the socket."""
        try:
            if self._ipc_socket:
                self._ipc_socket.sendall((cmd.to_json() + '\n').encode())
        except Exception:
            pass

    def _ipc_listener(self) -> None:
        """Reads strongly-typed IpcEvents from the Daemon continuously."""
        buffer: str = ''
        try:
            while not self._stop_flag.is_set():
                if not self._ipc_socket:
                    break

                data: bytes = self._ipc_socket.recv(4096)
                if not data:
                    self._cli.print_divider()
                    self._cli.print_message(
                        f'{Theme.RED}Alert:{Theme.RESET} Connection to Daemon lost! Exiting...'
                    )
                    self._cli.clear_input_area()
                    self._shutdown()

                buffer += data.decode()

                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event_dict: Dict[str, Any] = json.loads(line)
                        event: IpcEvent = IpcEvent.from_dict(event_dict)

                        if event.type == EventType.INIT:
                            self._my_onion = event.onion or 'unknown'
                            self._init_event.set()

                        elif event.type == EventType.INFO:
                            self._cli.print_message(
                                event.text, msg_type='info', alias=event.alias
                            )

                        elif event.type == EventType.SYSTEM:
                            self._cli.print_message(event.text, msg_type='system')

                        elif event.type == EventType.REMOTE_MSG:
                            self._cli.print_message(
                                event.text, msg_type='remote', alias=event.alias
                            )

                        elif event.type == EventType.ACK:
                            if event.msg_id:
                                self._cli.mark_acked(event.msg_id)

                        elif event.type == EventType.CONNECTED:
                            if event.alias and event.onion:
                                self._cli.print_message(
                                    event.text, msg_type='info', alias=event.alias
                                )
                                if self._pending_focus_target and (
                                    self._pending_focus_target == event.alias
                                    or self._pending_focus_target == event.onion
                                    or self._pending_focus_target
                                    == clean_onion(event.onion)
                                ):
                                    self._switch_focus(event.alias)
                                    self._pending_focus_target = None

                        elif event.type == EventType.DISCONNECTED:
                            self._cli.print_message(
                                event.text, msg_type='info', alias=event.alias
                            )
                            if self._focused_alias == event.alias:
                                self._switch_focus(None)

                        elif event.type == EventType.RENAME_SUCCESS:
                            if event.old_alias and event.new_alias:
                                self._cli.rename_alias_in_history(
                                    event.old_alias, event.new_alias
                                )
                                if self._focused_alias == event.old_alias:
                                    self._switch_focus(
                                        event.new_alias, hide_message=True
                                    )
                                if event.is_demotion:
                                    self._cli.print_message(
                                        f"Contact '{event.old_alias}' removed from profile '{self._pm.profile_name}'. Active session downgraded to volatile alias '{event.new_alias}'.",
                                        msg_type='system',
                                    )
                                else:
                                    self._cli.print_message(
                                        f"Renamed '{event.old_alias}' to '{event.new_alias}'.",
                                        msg_type='system',
                                    )
                                    if not event.history_updated:
                                        self._cli.print_message(
                                            f'{Theme.RED}Note:{Theme.RESET} The history log did not update.',
                                            msg_type='system',
                                        )

                        elif event.type == EventType.CONNECTIONS_STATE:
                            if event.is_header:
                                self._header_active = event.active
                                self._header_pending = event.pending
                                self._header_contacts = event.contacts
                                self._conn_event.set()
                            else:
                                self._render_connections(
                                    event.active, event.pending, event.contacts
                                )

                        elif event.type == EventType.SWITCH_SUCCESS:
                            self._switch_focus(event.alias)

                        elif event.type == EventType.CONTACT_LIST:
                            self._cli.print_message(event.text, msg_type='system')

                    except Exception:
                        pass

        except Exception:
            pass

    def _switch_focus(self, alias: Optional[str], hide_message: bool = False) -> None:
        """Changes the active chat target in the CLI."""
        old_alias: Optional[str] = self._focused_alias
        self._focused_alias = alias
        self._cli.set_focus(alias)

        if not hide_message:
            if alias:
                self._cli.print_message(
                    f"Switched focus to '{alias}'", alias=alias, msg_type='info'
                )
            else:
                self._cli.print_message(
                    f"Removed focus from '{old_alias}'.",
                    alias=old_alias,
                    msg_type='info',
                )

    def _render_connections(
        self,
        active: List[str],
        pending: List[str],
        contacts: List[str],
        header_mode: bool = False,
    ) -> None:
        """
        Renders the list of active and pending connections to the terminal.

        Colors active connections based on their status:
        - Green: Saved contact aliases.
        - Dark Grey: Temporary RAM/session aliases.
        - Preprends a '*' if the alias is currently focused.

        Args:
            active (List[str]): A list of aliases currently connected.
            pending (List[str]): A list of aliases waiting in the handshake room.
            contacts (List[str]): A list of aliases that are permanently saved to disk.
            header_mode (bool): If True, formats the output without decorators for the top header.

        Returns:
            None
        """
        msg_type: str = 'raw' if header_mode else 'system'

        if not active and not pending and not header_mode:
            self._cli.print_message(
                'No active or pending connections.', msg_type=msg_type
            )
            return

        lines: List[str] = []

        if active:
            lines.append('Active connections:')
            for alias in active:
                # Determine color: Green for saved contacts, Dark Grey for RAM sessions
                color: str = Theme.GREEN if alias in contacts else Theme.DARK_GREY

                # Determine focus indicator
                marker: str = '*' if alias == self._focused_alias else ' '

                lines.append(f' {marker} {color}{alias}{Theme.RESET}')

            if pending:
                lines.append('')

        if pending:
            lines.append('Pending connections:')
            for p in pending:
                lines.append(f'   {Theme.DARK_GREY}{p}{Theme.RESET}')

        self._cli.print_message('\n'.join(lines), msg_type=msg_type)

    def _print_header(self, clear_screen: bool = False) -> None:
        """Prints the welcome header and connection status."""
        if clear_screen:
            self._cli.clear_screen()

        self._cli.print_empty_line()
        self._cli.print_message(
            f'Your onion address: {Theme.YELLOW}{clean_onion(self._my_onion)}{Theme.RESET}.onion',
            skip_prompt=True,
        )
        self._cli.print_empty_line()
        self._cli.print_message(Help.show_chat_help(), skip_prompt=True)

        self._conn_event.clear()
        self._send_cmd(IpcCommand(action=Action.GET_CONNECTIONS, is_header=True))
        self._conn_event.wait(timeout=1.0)

        if self._header_active or self._header_pending:
            self._render_connections(
                self._header_active,
                self._header_pending,
                self._header_contacts,
                header_mode=True,
            )
            self._cli.print_empty_line()

        self._cli.print_empty_line()
        self._cli.print_prompt()
