"""
Module providing the handler for incoming Daemon IPC events.
Updates Session state and triggers Renderer UI updates via the central Translator and Presenter.
Maps generic UISeverity types to domain-specific ChatMessageTypes using a DRY architecture.
"""

import threading
import dataclasses
from typing import List, Optional, Dict, Any

from metor.core.api import (
    IpcEvent,
    DomainCode,
    SystemCode,
    NetworkCode,
    UiCode,
    MarkReadCommand,
    InitEvent,
    RemoteMsgEvent,
    AckEvent,
    DropFailedEvent,
    ConnectedEvent,
    DisconnectedEvent,
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
    TiebreakerRejectedEvent,
    AutoReconnectAttemptEvent,
    ContactsDataEvent,
    HistoryDataEvent,
    MessagesDataEvent,
    InboxCountsEvent,
    UnreadMessagesEvent,
    ProfilesDataEvent,
    ActionSuccessEvent,
    ActionErrorEvent,
    ContactActionSuccessEvent,
    ContactRenamedEvent,
    ProfileActionSuccessEvent,
    TargetActionSuccessEvent,
    SettingUpdatedEvent,
    FallbackSuccessEvent,
    MaxConnectionsReachedEvent,
    PeerNotFoundEvent,
    RetunnelInitiatedEvent,
    RetunnelSuccessEvent,
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
    UISeverity.ERROR: ChatMessageType.ERROR,
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

    def _print_translated(
        self,
        code: DomainCode,
        params: Optional[Dict[str, Any]] = None,
        alias: Optional[str] = None,
    ) -> None:
        """
        Resolves a translation code and renders it directly to the UI, applying the correct severity routing.

        Args:
            code (DomainCode): The strict domain code for translation.
            params (Optional[Dict[str, Any]]): Dynamic parameters to inject.
            alias (Optional[str]): The associated remote alias to attach to the UI line.

        Returns:
            None
        """
        text, severity = Translator.get(code, params)
        msg_type: ChatMessageType = _SEVERITY_MAP.get(severity, ChatMessageType.SYSTEM)
        self._renderer.print_message(text, msg_type=msg_type, alias=alias)

    def handle(self, event: IpcEvent) -> None:
        """
        Routes a single IPC event DTO to the appropriate state-change or rendering logic.

        Args:
            event (IpcEvent): The strongly-typed event received from the Daemon.

        Returns:
            None
        """
        try:
            # 1. State Initializers
            if isinstance(event, InitEvent):
                self._session.my_onion = event.onion or 'unknown'
                self._init_event.set()

            # 2. Query Data Responses (DTOs)
            elif isinstance(
                event,
                (
                    ContactsDataEvent,
                    HistoryDataEvent,
                    MessagesDataEvent,
                    InboxCountsEvent,
                    UnreadMessagesEvent,
                    ProfilesDataEvent,
                ),
            ):
                text_fmt: str = UIPresenter.format_response(event, chat_mode=True)
                target_alias: Optional[str] = getattr(event, 'target', None) or getattr(
                    event, 'alias', None
                )
                self._renderer.print_message(
                    text_fmt,
                    msg_type=ChatMessageType.SYSTEM,
                    alias=target_alias,
                )

            # 3. Synchronous/Asynchronous Status DTOs
            elif isinstance(event, FallbackSuccessEvent):
                self._renderer.apply_fallback_to_drop(event.msg_ids)
                params: Dict[str, Any] = dataclasses.asdict(event)
                self._print_translated(event.code, params, event.alias)

            elif isinstance(
                event,
                (
                    ActionSuccessEvent,
                    ActionErrorEvent,
                    ContactActionSuccessEvent,
                    ContactRenamedEvent,
                    ProfileActionSuccessEvent,
                    TargetActionSuccessEvent,
                    SettingUpdatedEvent,
                    MaxConnectionsReachedEvent,
                    PeerNotFoundEvent,
                    RetunnelInitiatedEvent,
                    RetunnelSuccessEvent,
                ),
            ):
                params = dataclasses.asdict(event)
                target_alias = params.get('alias') or params.get('target')
                self._print_translated(
                    getattr(event, 'code', SystemCode.COMMAND_SUCCESS),
                    params,
                    target_alias,
                )

            # 4. Message & Network Primitives
            elif isinstance(event, RemoteMsgEvent):
                self._renderer.print_message(
                    event.text,
                    msg_type=ChatMessageType.REMOTE,
                    alias=event.alias,
                    is_drop=False,
                )

            elif isinstance(event, AckEvent):
                self._renderer.mark_acked(msg_id=event.msg_id, text=event.text)

            elif isinstance(event, DropFailedEvent):
                self._renderer.mark_failed(msg_id=event.msg_id)

            elif isinstance(event, IncomingConnectionEvent):
                self._print_translated(
                    NetworkCode.INCOMING_CONNECTION, alias=event.alias
                )

            elif isinstance(event, ConnectionPendingEvent):
                self._print_translated(
                    NetworkCode.CONNECTION_PENDING, alias=event.alias
                )

            elif isinstance(event, ConnectionAutoAcceptedEvent):
                self._print_translated(
                    NetworkCode.CONNECTION_AUTO_ACCEPTED, alias=event.alias
                )

            elif isinstance(event, ConnectionRetryEvent):
                self._print_translated(
                    NetworkCode.CONNECTION_RETRY,
                    {'attempt': event.attempt, 'max_retries': event.max_retries},
                    alias=event.alias,
                )

            elif isinstance(event, ConnectionFailedEvent):
                self._print_translated(NetworkCode.CONNECTION_FAILED, alias=event.alias)

            elif isinstance(event, ConnectionRejectedEvent):
                self._print_translated(
                    NetworkCode.CONNECTION_REJECTED, alias=event.alias
                )

            elif isinstance(event, TiebreakerRejectedEvent):
                # UI Usability: The collision event is muted because it functions transparently as a Mutual Connection / Silent Accept for the user in the live chat.
                pass

            elif isinstance(event, AutoReconnectAttemptEvent):
                self._print_translated(
                    NetworkCode.AUTO_RECONNECT_ATTEMPT, alias=event.alias
                )

            elif isinstance(event, ConnectedEvent):
                if event.alias not in self._session.active_connections:
                    self._session.active_connections.append(event.alias)

                self._print_translated(NetworkCode.CONNECTED, alias=event.alias)

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=True)

                if self._session.pending_focus_target and (
                    self._session.pending_focus_target == event.alias
                    or clean_onion(self._session.pending_focus_target)
                    == clean_onion(event.onion or '')
                ):
                    self._switch_focus(event.alias)
                    self._session.pending_focus_target = None

            elif isinstance(event, DisconnectedEvent):
                self._print_translated(NetworkCode.DISCONNECTED, alias=event.alias)

                if event.alias in self._session.active_connections:
                    self._session.active_connections.remove(event.alias)

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=False)

            elif isinstance(event, InboxNotificationEvent):
                if event.alias and event.alias == self._session.focused_alias:
                    self._ipc.send_command(MarkReadCommand(target=event.alias))
                else:
                    self._print_translated(
                        NetworkCode.INBOX_NOTIFICATION,
                        {'count': event.count},
                        alias=event.alias,
                    )

            elif isinstance(event, InboxDataEvent):
                if event.alias and event.messages:
                    messages_data: List[Dict[str, Any]] = [
                        {'timestamp': m.timestamp, 'payload': m.payload}
                        for m in event.messages
                    ]
                    self._renderer.print_messages_batch(
                        messages_data, event.alias, event.is_live_flush
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
                self._print_translated(UiCode.ALREADY_FOCUSED, alias=alias)
            else:
                self._print_translated(UiCode.NO_ACTIVE_FOCUS)
            return

        self._session.focused_alias = alias
        is_live: bool = alias in self._session.active_connections if alias else False

        self._renderer.set_focus(alias, is_live)

        if not hide_message:
            if alias:
                self._print_translated(UiCode.FOCUS_SWITCHED, alias=alias)
                self._ipc.send_command(MarkReadCommand(target=alias))
            elif old_alias:
                self._print_translated(UiCode.FOCUS_REMOVED, alias=old_alias)
