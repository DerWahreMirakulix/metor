"""
Module providing the handler for incoming Daemon IPC events.
Updates Session state and triggers Renderer UI updates via the central Translator and Presenter.
Separates generic status tones from chat-specific render roles.
"""

import dataclasses
import threading
from typing import Dict, List, Optional

from metor.core.api import (
    IpcEvent,
    EventType,
    JsonValue,
    MarkReadCommand,
    SwitchCommand,
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
    ConnectionConnectingEvent,
    ConnectionAutoAcceptedEvent,
    ConnectionRetryEvent,
    ConnectionFailedEvent,
    IncomingConnectionEvent,
    ConnectionRejectedEvent,
    TiebreakerRejectedEvent,
    AutoReconnectAttemptEvent,
    DropQueuedEvent,
    ContactsDataEvent,
    HistoryDataEvent,
    MessagesDataEvent,
    InboxCountsEvent,
    UnreadMessagesEvent,
    ProfilesDataEvent,
    FallbackSuccessEvent,
)
from metor.ui import Translator, UIPresenter, StatusTone
from metor.utils import clean_onion

# Local Package Imports
from metor.ui.chat.presenter import ChatPresenter
from metor.ui.chat.renderer import Renderer
from metor.ui.chat.ipc import IpcClient
from metor.ui.chat.session import Session
from metor.ui.chat.models import ChatMessageType


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
        code: EventType,
        params: Optional[Dict[str, JsonValue]] = None,
        alias: Optional[str] = None,
    ) -> None:
        """
        Resolves a strict translation key and renders it directly to the UI.

        Args:
            code (EventType): The strict daemon event identifier.
            params (Optional[Dict[str, JsonValue]]): Dynamic parameters to inject.
            alias (Optional[str]): The associated remote alias to attach to the UI line.

        Returns:
            None
        """
        render_params: Dict[str, JsonValue] = params.copy() if params else {}
        if alias and not render_params.get('alias'):
            render_params['alias'] = alias

        text, tone = Translator.get(code, render_params)
        line_alias: Optional[str] = alias if tone is StatusTone.INFO else None
        self._renderer.print_message(
            text,
            msg_type=ChatMessageType.STATUS,
            tone=tone,
            alias=line_alias,
        )

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
                    ProfilesDataEvent,
                ),
            ):
                text_fmt: str = UIPresenter.format_response(event, chat_mode=True)
                target_alias: Optional[str] = getattr(event, 'target', None) or getattr(
                    event, 'alias', None
                )
                self._renderer.print_message(
                    text_fmt,
                    msg_type=ChatMessageType.STATUS,
                    tone=StatusTone.SYSTEM,
                    alias=target_alias,
                )

            elif isinstance(event, UnreadMessagesEvent):
                if event.messages:
                    messages_data: List[Dict[str, JsonValue]] = [
                        {'id': '', 'payload': m.payload, 'timestamp': m.timestamp}
                        for m in event.messages
                    ]
                    self._renderer.print_messages_batch(
                        messages_data, event.alias, is_live_flush=False
                    )

            # 3. Synchronous/Asynchronous Status DTOs
            elif isinstance(event, FallbackSuccessEvent):
                self._renderer.apply_fallback_to_drop(event.msg_ids)
                params_raw = dataclasses.asdict(event)
                params: Dict[str, JsonValue] = {
                    k: v
                    for k, v in params_raw.items()
                    if isinstance(v, (str, int, float, bool, type(None), list, dict))
                }
                self._print_translated(event.event_type, params, event.alias)

            # 4. Message & Network Primitives
            elif isinstance(event, RemoteMsgEvent):
                self._renderer.print_message(
                    event.text,
                    msg_type=ChatMessageType.REMOTE,
                    alias=event.alias,
                    timestamp=event.timestamp,
                    is_drop=False,
                )

            elif isinstance(event, AckEvent):
                self._renderer.mark_acked(msg_id=event.msg_id, text=event.text)

            elif isinstance(event, DropFailedEvent):
                self._renderer.mark_failed(msg_id=event.msg_id)

            elif isinstance(event, DropQueuedEvent):
                # Chat already renders the local drop line optimistically. The
                # structured success event stays useful for other UIs.
                pass

            elif isinstance(event, IncomingConnectionEvent):
                self._print_translated(event.event_type, alias=event.alias)

            elif isinstance(event, ConnectionPendingEvent):
                if event.alias not in self._session.pending_connections:
                    self._session.pending_connections.append(event.alias)
                self._print_translated(event.event_type, alias=event.alias)

            elif isinstance(event, ConnectionConnectingEvent):
                self._print_translated(event.event_type, alias=event.alias)

            elif isinstance(event, ConnectionAutoAcceptedEvent):
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)
                self._print_translated(event.event_type, alias=event.alias)

            elif isinstance(event, ConnectionRetryEvent):
                self._print_translated(
                    event.event_type,
                    {'attempt': event.attempt, 'max_retries': event.max_retries},
                    alias=event.alias,
                )

            elif isinstance(event, ConnectionFailedEvent):
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)
                self._print_translated(event.event_type, alias=event.alias)

            elif isinstance(event, ConnectionRejectedEvent):
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)
                self._print_translated(event.event_type, alias=event.alias)

            elif isinstance(event, TiebreakerRejectedEvent):
                # UI Usability: The collision event is muted because it functions transparently as a Mutual Connection / Silent Accept for the user in the live chat.
                pass

            elif isinstance(event, AutoReconnectAttemptEvent):
                self._print_translated(event.event_type, alias=event.alias)

            elif isinstance(event, ConnectedEvent):
                if event.alias not in self._session.active_connections:
                    self._session.active_connections.append(event.alias)
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)

                self._print_translated(event.event_type, alias=event.alias)

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=True)

                if self._session.pending_focus_target and (
                    self._session.pending_focus_target == event.alias
                    or clean_onion(self._session.pending_focus_target)
                    == clean_onion(event.onion or '')
                ):
                    self._switch_focus(event.alias, sync_daemon=True)
                    self._session.pending_focus_target = None

            elif isinstance(event, DisconnectedEvent):
                self._print_translated(event.event_type, alias=event.alias)

                if event.alias in self._session.active_connections:
                    self._session.active_connections.remove(event.alias)
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=False)

            elif isinstance(event, InboxNotificationEvent):
                if event.alias and event.alias == self._session.focused_alias:
                    self._ipc.send_command(MarkReadCommand(target=event.alias))
                else:
                    self._print_translated(
                        event.event_type,
                        {'count': event.count},
                        alias=event.alias,
                    )

            elif isinstance(event, InboxDataEvent):
                if event.alias and event.messages:
                    messages_data_dict: List[Dict[str, JsonValue]] = [
                        {'id': '', 'timestamp': m.timestamp, 'payload': m.payload}
                        for m in event.messages
                    ]
                    self._renderer.print_messages_batch(
                        messages_data_dict, event.alias, event.is_live_flush
                    )

            elif isinstance(event, RenameSuccessEvent):
                if event.old_alias in self._session.active_connections:
                    self._session.active_connections.remove(event.old_alias)
                    self._session.active_connections.append(event.new_alias)
                if event.old_alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.old_alias)
                    self._session.pending_connections.append(event.new_alias)

                self._renderer.rename_alias_in_history(event.old_alias, event.new_alias)

                if self._session.focused_alias == event.old_alias:
                    self._switch_focus(event.new_alias, hide_message=True)

            elif isinstance(event, ContactRemovedEvent):
                if event.alias in self._session.active_connections:
                    self._session.active_connections.remove(event.alias)
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)
                if self._session.focused_alias == event.alias:
                    self._switch_focus(None, hide_message=True, sync_daemon=True)

            elif isinstance(event, ConnectionsStateEvent):
                self._session.active_connections = event.active
                self._session.pending_connections = event.pending
                if event.is_header:
                    self._session.header_active = event.active
                    self._session.header_pending = event.pending
                    self._session.header_contacts = event.contacts
                    self._conn_event.set()
                else:
                    formatted_state: str = ChatPresenter.format_session_state(
                        self._session.active_connections,
                        self._session.pending_connections,
                        self._session.header_contacts,
                        self._session.focused_alias,
                        is_header_mode=False,
                    )
                    self._renderer.print_message(
                        formatted_state,
                        msg_type=ChatMessageType.STATUS,
                        tone=StatusTone.SYSTEM,
                    )

            elif isinstance(event, SwitchSuccessEvent):
                self._switch_focus(event.alias)

            else:
                params_raw = dataclasses.asdict(event)
                params = {
                    k: v
                    for k, v in params_raw.items()
                    if isinstance(v, (str, int, float, bool, type(None), list, dict))
                }
                target_alias = str(params.get('alias') or params.get('target') or '')
                self._print_translated(
                    event.event_type,
                    params,
                    target_alias if target_alias else None,
                )

        except Exception:
            pass

    def _switch_focus(
        self,
        alias: Optional[str],
        hide_message: bool = False,
        sync_daemon: bool = False,
    ) -> None:
        """
        Helper to safely change the active UI focus and fetch missing drops.

        Args:
            alias (Optional[str]): The target alias.
            hide_message (bool): Flag to skip printing the focus message.
            sync_daemon (bool): Flag to synchronize the focus change back to the daemon.

        Returns:
            None
        """
        old_alias: Optional[str] = self._session.focused_alias

        if old_alias == alias:
            return

        self._session.focused_alias = alias
        is_live: bool = self._session.is_connected(alias)

        self._renderer.set_focus(alias, is_live)

        if sync_daemon:
            self._ipc.send_command(SwitchCommand(target=alias))

        if not hide_message:
            if alias:
                self._renderer.print_message(
                    f"Switched focus to '{alias}'.",
                    msg_type=ChatMessageType.STATUS,
                    tone=StatusTone.INFO,
                    alias=alias,
                )
                self._ipc.send_command(MarkReadCommand(target=alias))
            elif old_alias:
                self._renderer.print_message(
                    "Removed focus from '{alias}'.",
                    msg_type=ChatMessageType.STATUS,
                    tone=StatusTone.INFO,
                    alias=old_alias,
                )
