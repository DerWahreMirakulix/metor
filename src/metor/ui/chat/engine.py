"""
Module providing the interactive Chat User Interface Engine.
Acts as a clean Facade, orchestrating the Session, Renderer, Commands, and Events.
"""

import threading
import secrets
from datetime import datetime, timezone
from typing import Optional

from metor.core.api import (
    AuthenticateSessionCommand,
    EventType,
    IpcEvent,
    InitCommand,
    MsgCommand,
    RegisterLiveConsumerCommand,
    SendDropCommand,
    GetConnectionsCommand,
    SwitchCommand,
    UnlockCommand,
)
from metor.data.profile import ProfileManager
from metor.data.settings import SettingKey
from metor.ui import Help, PromptAbortedError, Theme, prompt_hidden
from metor.ui.models import AliasPolicy, StatusTone
from metor.utils import clean_onion, Constants

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
        self._renderer: Renderer = Renderer(self._pm.config)
        self._session: Session = Session()
        self._renderer.set_alias_resolver(self._session.get_peer_alias)
        self._ipc: Optional[IpcClient] = None

        self._init_event: threading.Event = threading.Event()
        self._conn_event: threading.Event = threading.Event()
        self._disconnect_event: threading.Event = threading.Event()
        self._startup_gate_event: threading.Event = threading.Event()
        self._startup_gate_type: Optional[EventType] = None

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
        self._disconnect_event.clear()

        if not ipc_port:
            self._renderer.print_message(
                "Daemon is not running! Use 'metor daemon' to start it.",
                msg_type=ChatMessageType.STATUS,
                tone=StatusTone.SYSTEM,
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
                msg_type=ChatMessageType.STATUS,
                tone=StatusTone.SYSTEM,
            )
            return

        self._handler = EventHandler(
            self._ipc,
            self._session,
            self._renderer,
            self._init_event,
            self._conn_event,
            lambda: self._pm.config.get_float(SettingKey.INBOX_NOTIFICATION_DELAY),
        )
        self._dispatcher = CommandDispatcher(self._ipc, self._session, self._renderer)

        if not self._bootstrap_ipc_session():
            self._shutdown()
            return

        self._ipc.send_command(RegisterLiveConsumerCommand())

        self._print_header()

        try:
            while True:
                user_input: Optional[str] = self._renderer.read_line(
                    self._disconnect_event
                )

                if user_input is None:
                    if self._disconnect_event.is_set():
                        self._renderer.print_divider()
                        self._renderer.print_message(
                            f'{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}',
                            msg_type=ChatMessageType.RAW,
                        )
                        break
                    continue

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
                                msg_type=ChatMessageType.STATUS,
                                tone=StatusTone.SYSTEM,
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
        Propagates focus removal to ensure Daemon TTL Keep-Alives update correctly.
        Avoids sys.exit(0) core dumps by cleanly terminating thread loops.

        Args:
            None

        Returns:
            None
        """
        if self._ipc:
            if self._session.focused_alias:
                self._ipc.send_command(SwitchCommand(target=None))
            self._ipc.stop()

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
                msg_type=ChatMessageType.STATUS,
                tone=StatusTone.SYSTEM,
            )
            return

        msg_id: str = secrets.token_hex(Constants.UUID_MSG_BYTES)
        is_live: bool = self._session.is_connected(self._session.focused_alias)
        timestamp: str = datetime.now(timezone.utc).isoformat()
        peer_onion: Optional[str] = self._session.get_peer_onion(
            self._session.focused_alias
        )
        alias_policy: AliasPolicy = (
            AliasPolicy.DYNAMIC if peer_onion else AliasPolicy.STATIC
        )

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
                peer_onion=peer_onion,
                alias_policy=alias_policy,
                timestamp=timestamp,
                msg_id=msg_id,
                is_drop=False,
            )
        else:
            self._ipc.send_command(
                SendDropCommand(
                    target=self._session.focused_alias,
                    text=msg_text,
                    msg_id=msg_id,
                )
            )
            self._renderer.print_message(
                msg_text,
                msg_type=ChatMessageType.SELF,
                alias=self._session.focused_alias,
                peer_onion=peer_onion,
                alias_policy=alias_policy,
                timestamp=timestamp,
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
        self._disconnect_event.set()

    def _on_ipc_event(self, event: IpcEvent) -> None:
        """
        Forwards incoming IPC events to the EventHandler.

        Args:
            event (IpcEvent): The incoming IPC event.

        Returns:
            None
        """
        if not self._init_event.is_set() and event.event_type in (
            EventType.INIT,
            EventType.AUTH_REQUIRED,
            EventType.DAEMON_LOCKED,
            EventType.DAEMON_UNLOCKED,
            EventType.SESSION_AUTHENTICATED,
            EventType.INVALID_PASSWORD,
        ):
            if event.event_type is EventType.INIT and self._handler:
                self._handler.handle(event)

            self._startup_gate_type = event.event_type
            self._startup_gate_event.set()

            return

        if self._handler:
            self._handler.handle(event)

    def _bootstrap_ipc_session(self) -> bool:
        """
        Completes any required daemon unlock or per-session auth before chat init.

        Args:
            None

        Returns:
            bool: True when the persistent IPC session is ready for chat init.
        """
        if self._ipc is None:
            return False

        self._init_event.clear()
        self._startup_gate_event.clear()
        self._startup_gate_type = None
        self._ipc.send_command(InitCommand())

        ipc_timeout: float = self._pm.config.get_float(SettingKey.IPC_TIMEOUT)
        pending_gate: Optional[EventType] = None

        while not self._init_event.is_set():
            if self._disconnect_event.is_set():
                self._renderer.print_message(
                    f'{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}',
                    msg_type=ChatMessageType.RAW,
                )
                return False

            if not self._startup_gate_event.wait(timeout=ipc_timeout):
                self._renderer.print_message(
                    f'{Theme.RED}IPC Timeout:{Theme.RESET} The daemon is not responding. If this is a remote profile, check your SSH tunnel.',
                    msg_type=ChatMessageType.STATUS,
                    tone=StatusTone.ERROR,
                )
                return False

            self._startup_gate_event.clear()
            gate: Optional[EventType] = self._startup_gate_type
            self._startup_gate_type = None

            if self._init_event.is_set():
                return True

            if gate is EventType.INVALID_PASSWORD:
                self._renderer.print_message(
                    'Invalid master password.',
                    msg_type=ChatMessageType.STATUS,
                    tone=StatusTone.ERROR,
                )
                gate = pending_gate

            if gate is EventType.DAEMON_UNLOCKED:
                pending_gate = None
                self._ipc.send_command(InitCommand())
                continue

            if gate is EventType.SESSION_AUTHENTICATED:
                pending_gate = None
                self._ipc.send_command(InitCommand())
                continue

            if gate not in (EventType.AUTH_REQUIRED, EventType.DAEMON_LOCKED):
                continue

            pending_gate = gate
            prompt: str = (
                'Enter Master Password to unlock daemon: '
                if gate is EventType.DAEMON_LOCKED
                else 'Enter Master Password: '
            )
            try:
                password: str = prompt_hidden(f'{Theme.GREEN}{prompt}{Theme.RESET}')
            except PromptAbortedError:
                return False
            if not password:
                self._renderer.print_message(
                    'Master password cannot be empty.',
                    msg_type=ChatMessageType.STATUS,
                    tone=StatusTone.ERROR,
                )
                return False

            if gate is EventType.DAEMON_LOCKED:
                self._ipc.send_command(UnlockCommand(password=password))
            else:
                self._ipc.send_command(AuthenticateSessionCommand(password=password))

        return True

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

        ipc_timeout: float = self._pm.config.get_float(SettingKey.IPC_TIMEOUT)
        self._conn_event.wait(timeout=ipc_timeout)

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
