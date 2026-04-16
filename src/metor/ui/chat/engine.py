"""
Module providing the interactive Chat User Interface Engine.
Acts as a clean Facade, orchestrating the Session, Renderer, Commands, and Events.
"""

import secrets
import socket
import threading
from datetime import datetime, timezone
from typing import Dict, Optional, TypeVar

from metor.core.api import (
    ConnectionsStateEvent,
    EventType,
    IpcEvent,
    InitCommand,
    InitEvent,
    IpcCommand,
    JsonValue,
    MsgCommand,
    RegisterLiveConsumerCommand,
    SendDropCommand,
    GetConnectionsCommand,
    SwitchCommand,
)
from metor.data.profile import ProfileManager
from metor.data.settings import SettingKey
from metor.ui.ipc import IpcAuthExchange
from metor.ui import (
    Help,
    PromptAbortedError,
    Theme,
    Translator,
    prompt_hidden,
    prompt_session_auth_proof,
)
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


BootstrapEventT = TypeVar('BootstrapEventT', bound=IpcEvent)


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

        self._handler: Optional[EventHandler] = None
        self._dispatcher: Optional[CommandDispatcher] = None

    @staticmethod
    def _build_prechat_event_params(event: IpcEvent) -> Dict[str, JsonValue]:
        """
        Builds the plain translator payload for one pre-chat daemon event.

        Args:
            event (IpcEvent): The incoming event.

        Returns:
            Dict[str, JsonValue]: The translator-safe parameter payload.
        """
        params_raw = event.__dict__.copy()
        return {
            key: value
            for key, value in params_raw.items()
            if isinstance(value, (str, int, float, bool, type(None), list, dict))
        }

    def _print_prechat_event(self, event: IpcEvent) -> None:
        """
        Prints one bootstrap/auth event before the chat renderer becomes active.

        Args:
            event (IpcEvent): The event to translate and print.

        Returns:
            None
        """
        params: Dict[str, JsonValue] = self._build_prechat_event_params(event)
        text, _ = Translator.get(event.event_type, params if params else None)
        if params and 'alias' in params and '{alias}' in text:
            text = text.replace('{alias}', str(params['alias']))
        elif '{alias}' in text:
            text = text.replace('{alias}', 'unknown')
        print(text, flush=True)

    def _format_prechat_event_text(self, event: IpcEvent) -> str:
        """
        Formats one bootstrap event into plain pre-chat console output.

        Args:
            event (IpcEvent): The event to translate.

        Returns:
            str: The translated plain text.
        """
        params: Dict[str, JsonValue] = self._build_prechat_event_params(event)
        text, _ = Translator.get(event.event_type, params if params else None)
        if params and 'alias' in params and '{alias}' in text:
            return text.replace('{alias}', str(params['alias']))
        if '{alias}' in text:
            return text.replace('{alias}', 'unknown')
        return text

    @staticmethod
    def _print_prechat_message(text: str) -> None:
        """
        Prints one plain bootstrap status line before chat UI rendering starts.

        Args:
            text (str): The text to print.

        Returns:
            None
        """
        print(text, flush=True)

    def _request_prechat_event(
        self,
        cmd: IpcCommand,
        expected_event_type: type[BootstrapEventT],
    ) -> Optional[BootstrapEventT]:
        """
        Executes one synchronous bootstrap request on the persistent chat IPC socket.

        Args:
            cmd (IpcCommand): The request command to send.
            expected_event_type (type[BootstrapEventT]): The response DTO type to await.

        Returns:
            Optional[BootstrapEventT]: The expected response event, or None on failure.
        """
        if self._ipc is None:
            return None

        self._ipc.send_command(cmd)
        auth_exchange = IpcAuthExchange(
            prompt_session_proof=lambda challenge, salt: prompt_session_auth_proof(
                'Enter Master Password: ',
                challenge,
                salt,
            ),
            prompt_unlock_password=lambda: (
                prompt_hidden(
                    f'{Theme.GREEN}Enter Master Password to unlock daemon: {Theme.RESET}'
                )
                or None
            ),
            send_command=self._ipc.send_command,
        )

        while True:
            try:
                event: Optional[IpcEvent] = self._ipc.read_event()
            except socket.timeout:
                self._print_prechat_message(
                    f'{Theme.RED}IPC Timeout:{Theme.RESET} The daemon is not responding. If this is a remote profile, check your SSH tunnel.'
                )
                return None
            except (OSError, ValueError):
                self._print_prechat_message(
                    f'{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}'
                )
                return None

            if event is None:
                self._print_prechat_message(
                    f'{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}'
                )
                return None

            if isinstance(event, expected_event_type):
                return event

            try:
                auth_result = auth_exchange.handle(event)
            except PromptAbortedError:
                return None

            if auth_result.handled:
                if auth_result.terminal_message is not None:
                    self._print_prechat_message(auth_result.terminal_message)
                    return None
                if auth_result.terminal_event is not None:
                    self._print_prechat_event(auth_result.terminal_event)
                    return None
                if auth_result.resend_original_command:
                    self._ipc.send_command(cmd)
                continue

            if event.event_type in (
                EventType.LOCAL_AUTH_RATE_LIMITED,
                EventType.IPC_CLIENT_LIMIT_REACHED,
                EventType.DB_CORRUPTED,
                EventType.DAEMON_OFFLINE,
                EventType.INTERNAL_ERROR,
                EventType.UNKNOWN_COMMAND,
            ):
                self._print_prechat_message(self._format_prechat_event_text(event))
                return None

    def _handle_daemon_disconnect_exit(self, *, show_divider: bool = False) -> None:
        """
        Renders the daemon-disconnect shutdown message without redrawing the prompt.

        Args:
            show_divider (bool): Whether to render a divider before the exit message.

        Returns:
            None
        """
        self._renderer.clear_input_area()
        if show_divider:
            self._renderer.print_divider(skip_prompt=True)
        self._renderer.print_message(
            f'{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}',
            msg_type=ChatMessageType.RAW,
            skip_prompt=True,
        )

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
            timeout=self._pm.config.get_float(SettingKey.IPC_TIMEOUT),
            on_event=self._on_ipc_event,
            on_disconnect=self._on_ipc_disconnect,
        )

        if not self._ipc.connect(start_listener=False):
            self._renderer.print_message(
                'Could not connect to Daemon. Is it running?',
                msg_type=ChatMessageType.STATUS,
                tone=StatusTone.SYSTEM,
            )
            return

        if not self._bootstrap_ipc_session():
            self._shutdown()
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

        self._ipc.start_listener()

        self._ipc.send_command(RegisterLiveConsumerCommand())

        self._print_header(refresh_state=False)

        try:
            while True:
                user_input: Optional[str] = self._renderer.read_line(
                    self._disconnect_event
                )

                if user_input is None:
                    if self._disconnect_event.is_set():
                        self._handle_daemon_disconnect_exit(show_divider=True)
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
        Ensures the terminal cursor is restored to a visible state natively.

        Args:
            None

        Returns:
            None
        """
        # Ensure cursor is visible before exiting to avoid OS zombie states.
        self._renderer.restore_cursor()

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
        is_live: bool = self._session.is_live_transport_available(
            self._session.focused_alias
        )
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
        if self._handler:
            self._handler.handle(event)

    def _bootstrap_ipc_session(self) -> bool:
        """
        Completes synchronous pre-chat bootstrap on the persistent IPC socket.

        Args:
            None

        Returns:
            bool: True when the persistent IPC session is ready for chat init.
        """
        if self._ipc is None:
            return False

        self._init_event.clear()
        init_event: Optional[InitEvent] = self._request_prechat_event(
            InitCommand(),
            InitEvent,
        )
        if init_event is None:
            return False

        self._session.my_onion = init_event.onion or 'unknown'
        self._init_event.set()

        connections_event: Optional[ConnectionsStateEvent] = (
            self._request_prechat_event(
                GetConnectionsCommand(is_header=True),
                ConnectionsStateEvent,
            )
        )
        if connections_event is None:
            return False

        self._session.active_connections = connections_event.active
        self._session.pending_connections = connections_event.pending
        self._session.header_active = connections_event.active
        self._session.header_pending = connections_event.pending
        self._session.header_contacts = connections_event.contacts
        return True

    def _print_header(
        self,
        clear_screen: bool = False,
        refresh_state: bool = True,
    ) -> None:
        """
        Prints the application welcome header, help info, and connection status.

        Args:
            clear_screen (bool): Whether to wipe the terminal display before printing.
            refresh_state (bool): Whether to refresh daemon session-state before rendering.

        Returns:
            None
        """
        if clear_screen:
            self._renderer.clear_screen()

        if refresh_state and not self._refresh_header_state():
            return

        self._renderer.print_empty_line()
        self._renderer.print_message(
            f'Your onion address: {Theme.YELLOW}{clean_onion(self._session.my_onion)}{Theme.RESET}.onion',
            skip_prompt=True,
        )
        self._renderer.print_empty_line()
        self._renderer.print_message(Help.show_chat_help(), skip_prompt=True)

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

    def _refresh_header_state(self) -> bool:
        """
        Refreshes the daemon session-state snapshot used by the chat header.

        Args:
            None

        Returns:
            bool: True when header state was refreshed successfully.
        """
        if self._ipc is None:
            return False

        self._conn_event.clear()
        self._ipc.send_command(GetConnectionsCommand(is_header=True))

        ipc_timeout: float = self._pm.config.get_float(SettingKey.IPC_TIMEOUT)
        if not self._conn_event.wait(timeout=ipc_timeout):
            if self._disconnect_event.is_set():
                self._handle_daemon_disconnect_exit()
                return False

            self._renderer.print_message(
                f'{Theme.RED}IPC Timeout:{Theme.RESET} The daemon is not responding. If this is a remote profile, check your SSH tunnel.',
                msg_type=ChatMessageType.STATUS,
                tone=StatusTone.ERROR,
            )
            return False

        return True
