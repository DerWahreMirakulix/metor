"""
Module providing the interactive Chat User Interface Engine.
Acts as a clean Facade, orchestrating the Session, Renderer, Commands, and Events.
"""

import sys
import os
import signal
import threading
import secrets
from typing import Optional

from metor.core.api import (
    IpcEvent,
    InitCommand,
    MsgCommand,
    SendDropCommand,
    GetConnectionsCommand,
)
from metor.data.profile import ProfileManager
from metor.ui import Help, Theme
from metor.utils import clean_onion

# Local Package Imports
from metor.ui.chat.models import ChatMessageType
from metor.ui.chat.renderer import Renderer
from metor.ui.chat.presenter import ChatPresenter
from metor.ui.chat.ipc import IpcClient
from metor.ui.chat.session import Session
from metor.ui.chat.command import CommandDispatcher
from metor.ui.chat.event import EventHandler


class Chat:
    """The UI Engine. Orchestrates input handling and Daemon IPC communication."""

    def __init__(self, pm: ProfileManager) -> None:
        """
        Initializes the Chat UI orchestrator.

        Args:
            pm (ProfileManager): The manager handling the profile's daemon connection state.

        Returns:
            None
        """
        self._pm: ProfileManager = pm
        self._renderer: Renderer = Renderer()
        self._session: Session = Session()
        self._ipc: Optional[IpcClient] = None

        self._init_event: threading.Event = threading.Event()
        self._conn_event: threading.Event = threading.Event()

        self._handler: Optional[EventHandler] = None
        self._dispatcher: Optional[CommandDispatcher] = None

    def run(self) -> None:
        """
        Starts the main chat UI loop, establishes the IPC Client, and handles inputs.

        Args:
            None

        Returns:
            None
        """
        ipc_port: Optional[int] = self._pm.get_daemon_port()
        if not ipc_port:
            self._renderer.print_message(
                "Daemon is not running! Use 'metor daemon' to start it.",
                msg_type=ChatMessageType.SYSTEM,
            )
            return

        self._ipc = IpcClient(
            port=ipc_port,
            on_event=self._on_ipc_event,
            on_disconnect=self._on_ipc_disconnect,
        )

        if not self._ipc.connect():
            self._renderer.print_message(
                'Could not connect to Daemon. Is it running?',
                msg_type=ChatMessageType.SYSTEM,
            )
            return

        self._handler = EventHandler(
            self._ipc, self._session, self._renderer, self._init_event, self._conn_event
        )
        self._dispatcher = CommandDispatcher(self._ipc, self._session, self._renderer)

        self._ipc.send_command(InitCommand())
        self._init_event.wait(timeout=2.0)

        self._print_header()

        try:
            while True:
                user_input: str = self._renderer.read_line()

                if user_input == '':
                    self._renderer.print_prompt()
                elif user_input.startswith('/'):
                    if user_input == '/clear':
                        self._print_header(clear_screen=True)
                    elif user_input == '/exit':
                        break
                    else:
                        command_found: bool = self._dispatcher.dispatch(user_input)
                        if not command_found:
                            self._renderer.print_message(
                                f"Unknown command: '{user_input}'",
                                msg_type=ChatMessageType.SYSTEM,
                            )
                else:
                    self._send_chat_message(user_input)

        except KeyboardInterrupt:
            self._renderer.clear_input_area()
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        """
        Safely shuts down the IPC client and exits the UI process.

        Args:
            None

        Returns:
            None
        """
        if self._ipc:
            self._ipc.stop()

        if threading.current_thread() is threading.main_thread():
            sys.exit(0)
        else:
            os.kill(os.getpid(), signal.SIGINT)

    def _send_chat_message(self, msg_text: str) -> None:
        """
        Routes a text payload dynamically via Live-Chat or Async-Drop.

        Args:
            msg_text (str): The text payload to route.

        Returns:
            None
        """
        if not self._session.focused_alias or not self._ipc:
            self._renderer.print_message(
                'No active focus. Use /switch or /connect.',
                msg_type=ChatMessageType.SYSTEM,
            )
            return

        msg_id: str = secrets.token_hex(4)
        is_live: bool = self._session.focused_alias in self._session.active_connections

        if is_live:
            self._ipc.send_command(
                MsgCommand(
                    target=self._session.focused_alias,
                    text=msg_text,
                    msg_id=msg_id,
                )
            )
            self._renderer.print_message(
                msg_text,
                msg_type=ChatMessageType.SELF,
                alias=self._session.focused_alias,
                msg_id=msg_id,
                is_drop=False,
            )
        else:
            self._ipc.send_command(
                SendDropCommand(
                    target=self._session.focused_alias,
                    text=msg_text,
                )
            )
            self._renderer.print_message(
                msg_text,
                msg_type=ChatMessageType.SELF,
                alias=self._session.focused_alias,
                msg_id=msg_id,
                is_drop=True,
                is_pending=True,
            )

    def _on_ipc_disconnect(self) -> None:
        """
        Callback fired when the IPC Client detects a broken pipe.

        Args:
            None

        Returns:
            None
        """
        self._renderer.print_divider()
        self._renderer.print_message(
            f'{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}',
            msg_type=ChatMessageType.RAW,
        )
        self._renderer.clear_input_area()
        self._shutdown()

    def _on_ipc_event(self, event: IpcEvent) -> None:
        """
        Forwards incoming IPC events to the EventHandler.

        Args:
            event (IpcEvent): The incoming IPC event.

        Returns:
            None
        """
        if self._handler:
            self._handler.handle(event)

    def _print_header(self, clear_screen: bool = False) -> None:
        """
        Prints the application welcome header, help info, and connection status.

        Args:
            clear_screen (bool): Whether to wipe the terminal display before printing.

        Returns:
            None
        """
        if clear_screen:
            self._renderer.clear_screen()

        self._renderer.print_empty_line()
        self._renderer.print_message(
            f'Your onion address: {Theme.YELLOW}{clean_onion(self._session.my_onion)}{Theme.RESET}.onion',
            skip_prompt=True,
        )
        self._renderer.print_empty_line()
        self._renderer.print_message(Help.show_chat_help(), skip_prompt=True)

        self._conn_event.clear()
        if self._ipc:
            self._ipc.send_command(GetConnectionsCommand(is_header=True))

        self._conn_event.wait(timeout=1.0)

        self._renderer.print_divider(compact=True)

        if self._session.header_active or self._session.header_pending:
            self._renderer.print_empty_line()
            formatted_state: str = ChatPresenter.format_session_state(
                self._session.header_active,
                self._session.header_pending,
                self._session.header_contacts,
                self._session.focused_alias,
                is_header_mode=True,
            )
            self._renderer.print_message(formatted_state, msg_type=ChatMessageType.RAW)

        self._renderer.print_empty_line()
        self._renderer.print_prompt()
