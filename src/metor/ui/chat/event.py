"""
Module providing the handler for incoming Daemon IPC events.
Updates Session state and triggers Renderer UI updates via the central Translator and Presenter.
Maps generic UISeverity types to domain-specific ChatMessageTypes.
"""

import threading
from typing import Optional, Dict

from metor.core.api import (
    IpcEvent,
    TransCode,
    MarkReadCommand,
    InitEvent,
    NotificationEvent,
    CommandResponseEvent,
    RemoteMsgEvent,
    AckEvent,
    ConnectedEvent,
    DisconnectedEvent,
    MsgFallbackToDropEvent,
    InboxNotificationEvent,
    InboxDataEvent,
    RenameSuccessEvent,
    ContactRemovedEvent,
    ConnectionsStateEvent,
    SwitchSuccessEvent,
    ConnectionPendingEvent,
    ConnectionAutoAcceptedEvent,
    ConnectionRetryEvent,
    ConnectionFailedEvent,
    IncomingConnectionEvent,
    ConnectionRejectedEvent,
)
from metor.ui import Translator, UIPresenter, UISeverity
from metor.utils import clean_onion

# Local Package Imports
from metor.ui.chat.renderer import Renderer
from metor.ui.chat.presenter import ChatPresenter
from metor.ui.chat.ipc import IpcClient
from metor.ui.chat.session import Session
from metor.ui.chat.models import ChatMessageType


_SEVERITY_MAP: Dict[UISeverity, ChatMessageType] = {
    UISeverity.INFO: ChatMessageType.INFO,
    UISeverity.SYSTEM: ChatMessageType.SYSTEM,
    UISeverity.ERROR: ChatMessageType.SYSTEM,  # Chat routes generic errors as system info
}


class EventHandler:
    """Processes incoming strictly-typed IPC events from the daemon."""

    def __init__(
        self,
        ipc: IpcClient,
        session: Session,
        renderer: Renderer,
        init_event: threading.Event,
        conn_event: threading.Event,
    ) -> None:
        """
        Initializes the EventHandler with dependencies.

        Args:
            ipc (IpcClient): The IPC client.
            session (Session): The current chat session state.
            renderer (Renderer): The terminal UI renderer.
            init_event (threading.Event): Event to signal successful initialization.
            conn_event (threading.Event): Event to signal connection state updates.

        Returns:
            None
        """
        self._ipc: IpcClient = ipc
        self._session: Session = session
        self._renderer: Renderer = renderer
        self._init_event: threading.Event = init_event
        self._conn_event: threading.Event = conn_event

    def handle(self, event: IpcEvent) -> None:
        """
        Routes a single IPC event to the appropriate state-change or rendering logic.

        Args:
            event (IpcEvent): The strongly-typed event received from the Daemon.

        Returns:
            None
        """
        try:
            if isinstance(event, InitEvent):
                self._session.my_onion = event.onion or 'unknown'
                self._init_event.set()

            elif isinstance(event, NotificationEvent):
                text, severity = Translator.get(event.code, event.params)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(
                    text, msg_type=msg_type, alias=event.params.get('alias')
                )

            elif isinstance(event, CommandResponseEvent):
                if event.data:
                    text_fmt: str = UIPresenter.format_response(
                        event.action, event.data, chat_mode=True
                    )
                    self._renderer.print_message(
                        text_fmt,
                        msg_type=ChatMessageType.RAW,
                        alias=event.params.get('alias'),
                    )
                else:
                    text, severity = Translator.get(event.code, event.params)
                    msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                    self._renderer.print_message(
                        text, msg_type=msg_type, alias=event.params.get('alias')
                    )

            elif isinstance(event, RemoteMsgEvent):
                self._renderer.print_message(
                    event.text,
                    msg_type=ChatMessageType.REMOTE,
                    alias=event.alias,
                    is_drop=False,
                )

            elif isinstance(event, AckEvent):
                self._renderer.mark_acked(msg_id=event.msg_id, text=event.text)

            elif isinstance(event, IncomingConnectionEvent):
                text, severity = Translator.get(TransCode.INCOMING_CONNECTION)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=event.alias)

            elif isinstance(event, ConnectionPendingEvent):
                text, severity = Translator.get(TransCode.CONNECTION_PENDING)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=event.alias)

            elif isinstance(event, ConnectionAutoAcceptedEvent):
                text, severity = Translator.get(TransCode.CONNECTION_AUTO_ACCEPTED)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=event.alias)

            elif isinstance(event, ConnectionRetryEvent):
                params = {'attempt': event.attempt, 'max_retries': event.max_retries}
                text, severity = Translator.get(TransCode.CONNECTION_RETRY, params)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=event.alias)

            elif isinstance(event, ConnectionFailedEvent):
                text, severity = Translator.get(TransCode.CONNECTION_FAILED)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=event.alias)

            elif isinstance(event, ConnectionRejectedEvent):
                text, severity = Translator.get(TransCode.CONNECTION_REJECTED)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=event.alias)

            elif isinstance(event, ConnectedEvent):
                if event.alias not in self._session.active_connections:
                    self._session.active_connections.append(event.alias)

                text, severity = Translator.get(TransCode.CONNECTED)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=event.alias)

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=True)

                if self._session.pending_focus_target and (
                    self._session.pending_focus_target == event.alias
                    or self._session.pending_focus_target == event.onion
                    or clean_onion(self._session.pending_focus_target)
                    == clean_onion(event.onion or '')
                ):
                    self._switch_focus(event.alias)
                    self._session.pending_focus_target = None

            elif isinstance(event, DisconnectedEvent):
                text, severity = Translator.get(TransCode.DISCONNECTED)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=event.alias)

                if event.alias in self._session.active_connections:
                    self._session.active_connections.remove(event.alias)

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=False)

            elif isinstance(event, MsgFallbackToDropEvent):
                self._renderer.apply_fallback_to_drop(event.msg_ids)

            elif isinstance(event, InboxNotificationEvent):
                if event.alias and event.alias == self._session.focused_alias:
                    self._ipc.send_command(MarkReadCommand(target=event.alias))
                else:
                    text, severity = Translator.get(
                        TransCode.INBOX_NOTIFICATION, {'count': event.count}
                    )
                    msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                    self._renderer.print_message(
                        text, msg_type=msg_type, alias=event.alias
                    )

            elif isinstance(event, InboxDataEvent):
                if event.alias and event.messages:
                    self._renderer.print_messages_batch(
                        event.messages, event.alias, event.is_live_flush
                    )

            elif isinstance(event, RenameSuccessEvent):
                if event.old_alias in self._session.active_connections:
                    self._session.active_connections.remove(event.old_alias)
                    self._session.active_connections.append(event.new_alias)

                self._renderer.rename_alias_in_history(event.old_alias, event.new_alias)

                if self._session.focused_alias == event.old_alias:
                    self._switch_focus(event.new_alias, hide_message=True)

            elif isinstance(event, ContactRemovedEvent):
                if event.alias in self._session.active_connections:
                    self._session.active_connections.remove(event.alias)
                if self._session.focused_alias == event.alias:
                    self._switch_focus(None, hide_message=True)

            elif isinstance(event, ConnectionsStateEvent):
                self._session.active_connections = event.active
                if event.is_header:
                    self._session.header_active = event.active
                    self._session.header_pending = event.pending
                    self._session.header_contacts = event.contacts
                    self._conn_event.set()
                else:
                    formatted_state: str = ChatPresenter.format_session_state(
                        self._session.active_connections,
                        [],
                        self._session.header_contacts,
                        self._session.focused_alias,
                        is_header_mode=False,
                    )
                    self._renderer.print_message(
                        formatted_state,
                        msg_type=ChatMessageType.SYSTEM,
                    )

            elif isinstance(event, SwitchSuccessEvent):
                self._switch_focus(event.alias)

        except Exception:
            pass

    def _switch_focus(self, alias: Optional[str], hide_message: bool = False) -> None:
        """
        Helper to safely change the active UI focus and fetch missing drops.

        Args:
            alias (Optional[str]): The target alias.
            hide_message (bool): Flag to skip printing the focus message.

        Returns:
            None
        """
        old_alias: Optional[str] = self._session.focused_alias

        if old_alias == alias:
            if alias:
                text, severity = Translator.get(TransCode.ALREADY_FOCUSED)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=alias)
            else:
                text, severity = Translator.get(TransCode.NO_ACTIVE_FOCUS)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type)
            return

        self._session.focused_alias = alias
        is_live: bool = alias in self._session.active_connections if alias else False

        self._renderer.set_focus(alias, is_live)

        if not hide_message:
            if alias:
                text, severity = Translator.get(TransCode.FOCUS_SWITCHED)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=alias)
                self._ipc.send_command(MarkReadCommand(target=alias))
            elif old_alias:
                text, severity = Translator.get(TransCode.FOCUS_REMOVED)
                msg_type = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
                self._renderer.print_message(text, msg_type=msg_type, alias=old_alias)
