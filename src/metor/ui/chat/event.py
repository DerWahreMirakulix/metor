"""
Module providing the handler for incoming Daemon IPC events.
Updates Session state and triggers Renderer UI updates via the central Translator and Presenter.
Separates generic status tones from chat-specific render roles.
"""

import dataclasses
import threading
from typing import Callable, Dict, List, Optional

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
    NoPendingConnectionEvent,
    PeerNotFoundEvent,
    MaxConnectionsReachedEvent,
    ContactsDataEvent,
    HistoryDataEvent,
    MessagesDataEvent,
    InboxCountsEvent,
    UnreadMessagesEvent,
    ProfilesDataEvent,
    FallbackSuccessEvent,
)
from metor.ui import AliasPolicy, Translator, UIPresenter, StatusTone
from metor.utils import clean_onion

# Local Package Imports
from metor.ui.chat.presenter import ChatPresenter
from metor.ui.chat.renderer import Renderer
from metor.ui.chat.ipc import IpcClient
from metor.ui.chat.session import Session
from metor.ui.chat.models import ChatMessageType


@dataclasses.dataclass
class BufferedInboxNotification:
    """Stores one aggregated pending inbox notification for delayed UI rendering."""

    alias: str
    onion: Optional[str]
    count: int
    timer: threading.Timer


class EventHandler:
    """Processes incoming strictly-typed IPC events from the daemon."""

    def __init__(
        self,
        ipc: IpcClient,
        session: Session,
        renderer: Renderer,
        init_event: threading.Event,
        conn_event: threading.Event,
        get_notification_buffer_seconds: Callable[[], float],
    ) -> None:
        """
        Initializes the EventHandler with dependencies.

        Args:
            ipc (IpcClient): The IPC client.
            session (Session): The current chat session state.
            renderer (Renderer): The terminal UI renderer.
            init_event (threading.Event): Event to signal successful initialization.
            conn_event (threading.Event): Event to signal connection state updates.
            get_notification_buffer_seconds (Callable[[], float]): Lazy accessor for the local inbox-notification buffer window.

        Returns:
            None
        """
        self._ipc: IpcClient = ipc
        self._session: Session = session
        self._renderer: Renderer = renderer
        self._init_event: threading.Event = init_event
        self._conn_event: threading.Event = conn_event
        self._get_notification_buffer_seconds: Callable[[], float] = (
            get_notification_buffer_seconds
        )
        self._notification_lock: threading.Lock = threading.Lock()
        self._buffered_inbox_notifications: Dict[str, BufferedInboxNotification] = {}

    @staticmethod
    def _notification_key(alias: Optional[str], onion: Optional[str]) -> Optional[str]:
        """
        Builds one stable key for buffered notification aggregation.

        Args:
            alias (Optional[str]): The current peer alias.
            onion (Optional[str]): The stable peer onion identity.

        Returns:
            Optional[str]: The notification aggregation key.
        """
        if onion:
            return clean_onion(onion)
        if alias:
            return f'alias:{alias}'
        return None

    def _cancel_buffered_notification(
        self,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> None:
        """
        Cancels one pending buffered notification if it exists.

        Args:
            alias (Optional[str]): The current peer alias.
            onion (Optional[str]): The stable peer onion identity.

        Returns:
            None
        """
        key: Optional[str] = self._notification_key(alias, onion)
        if not key:
            return

        pending: Optional[BufferedInboxNotification] = None
        with self._notification_lock:
            pending = self._buffered_inbox_notifications.pop(key, None)

        if pending:
            pending.timer.cancel()

    def _flush_buffered_notification(self, key: str) -> None:
        """
        Emits one aggregated buffered notification after the local debounce window.

        Args:
            key (str): The buffered notification key.

        Returns:
            None
        """
        with self._notification_lock:
            pending: Optional[BufferedInboxNotification] = (
                self._buffered_inbox_notifications.pop(key, None)
            )

        if not pending:
            return

        alias: Optional[str] = self._session.get_peer_alias(
            pending.onion, pending.alias
        )
        if alias and alias == self._session.focused_alias:
            self._ipc.send_command(MarkReadCommand(target=alias))
            return

        self._print_translated(
            EventType.INBOX_NOTIFICATION,
            {'count': pending.count},
            alias=alias,
            onion=pending.onion,
        )

    def _queue_buffered_notification(
        self,
        alias: str,
        onion: Optional[str],
        count: int,
    ) -> None:
        """
        Buffers one notification burst locally so multiple unread events collapse into one UI line.

        Args:
            alias (str): The current peer alias.
            onion (Optional[str]): The stable peer onion identity.
            count (int): The unread increment to aggregate.

        Returns:
            None
        """
        buffer_seconds: float = self._get_notification_buffer_seconds()
        if buffer_seconds <= 0:
            self._print_translated(
                EventType.INBOX_NOTIFICATION,
                {'count': count},
                alias=alias,
                onion=onion,
            )
            return

        key: Optional[str] = self._notification_key(alias, onion)
        if not key:
            self._print_translated(
                EventType.INBOX_NOTIFICATION,
                {'count': count},
                alias=alias,
                onion=onion,
            )
            return

        with self._notification_lock:
            existing: Optional[BufferedInboxNotification] = (
                self._buffered_inbox_notifications.pop(key, None)
            )
            total_count: int = count + (existing.count if existing else 0)
            if existing:
                existing.timer.cancel()

            timer: threading.Timer = threading.Timer(
                buffer_seconds,
                self._flush_buffered_notification,
                args=(key,),
            )
            timer.daemon = True
            self._buffered_inbox_notifications[key] = BufferedInboxNotification(
                alias=alias,
                onion=onion,
                count=total_count,
                timer=timer,
            )
            timer.start()

    @staticmethod
    def _matches_focus_target(
        target: Optional[str],
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> bool:
        """
        Checks whether a pending focus target matches an alias or onion identity.

        Args:
            target (Optional[str]): The stored pending focus target.
            alias (Optional[str]): The concrete alias to compare.
            onion (Optional[str]): The concrete onion to compare.

        Returns:
            bool: True if the target matches either identifier.
        """
        if not target:
            return False
        if alias and target == alias:
            return True
        if onion and clean_onion(target) == clean_onion(onion):
            return True
        return False

    def _print_translated(
        self,
        code: EventType,
        params: Optional[Dict[str, JsonValue]] = None,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
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
        alias_policy = Translator.get_alias_policy(code)
        line_alias: Optional[str] = alias if alias and '{alias}' in text else None
        self._renderer.print_message(
            text,
            msg_type=ChatMessageType.STATUS,
            tone=tone,
            alias=line_alias,
            peer_onion=onion,
            alias_policy=alias_policy,
        )

    def _print_peer_status(
        self,
        text: str,
        tone: StatusTone,
        alias: str,
        onion: Optional[str] = None,
    ) -> None:
        """
        Renders one peer-bound status line with the correct alias redraw policy.

        Args:
            text (str): The status message template.
            tone (StatusTone): The line tone.
            alias (str): The current alias to bind.
            onion (Optional[str]): The stable peer onion identity.

        Returns:
            None
        """
        alias_policy: AliasPolicy = AliasPolicy.DYNAMIC if onion else AliasPolicy.STATIC
        line_alias: Optional[str] = alias if '{alias}' in text else None
        self._renderer.print_message(
            text,
            msg_type=ChatMessageType.STATUS,
            tone=tone,
            alias=line_alias,
            peer_onion=onion,
            alias_policy=alias_policy,
        )

    def _remember_peer(self, alias: Optional[str], onion: Optional[str]) -> None:
        """
        Stores one current peer alias binding when both identifiers are known.

        Args:
            alias (Optional[str]): The current peer alias.
            onion (Optional[str]): The stable peer onion identity.

        Returns:
            None
        """
        self._session.remember_peer(alias, onion)

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
                if isinstance(event, ContactsDataEvent):
                    for contact_entry in event.saved:
                        self._remember_peer(contact_entry.alias, contact_entry.onion)
                    for discovered_entry in event.discovered:
                        self._remember_peer(
                            discovered_entry.alias,
                            discovered_entry.onion,
                        )
                elif isinstance(event, HistoryDataEvent):
                    for history_entry in event.history:
                        self._remember_peer(
                            history_entry.alias,
                            history_entry.onion,
                        )
                elif isinstance(event, MessagesDataEvent):
                    self._remember_peer(event.alias, event.onion)

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
                self._cancel_buffered_notification(event.alias, event.onion)
                if event.messages:
                    self._remember_peer(event.alias, event.onion)
                    messages_data: List[Dict[str, JsonValue]] = [
                        {
                            'id': '',
                            'payload': m.payload,
                            'timestamp': m.timestamp,
                            'is_drop': m.is_drop,
                        }
                        for m in event.messages
                    ]
                    self._renderer.print_messages_batch(
                        messages_data,
                        event.alias,
                        peer_onion=event.onion,
                        is_live_flush=False,
                    )

            # 3. Synchronous/Asynchronous Status DTOs
            elif isinstance(event, FallbackSuccessEvent):
                self._remember_peer(event.alias, event.onion)
                self._renderer.apply_fallback_to_drop(event.msg_ids)
                params_raw = dataclasses.asdict(event)
                params: Dict[str, JsonValue] = {
                    k: v
                    for k, v in params_raw.items()
                    if isinstance(v, (str, int, float, bool, type(None), list, dict))
                }
                self._print_translated(
                    event.event_type,
                    params,
                    event.alias,
                    event.onion,
                )

            # 4. Message & Network Primitives
            elif isinstance(event, RemoteMsgEvent):
                self._remember_peer(event.alias, event.onion)
                self._renderer.print_message(
                    event.text,
                    msg_type=ChatMessageType.REMOTE,
                    alias=event.alias,
                    peer_onion=event.onion,
                    alias_policy=(
                        AliasPolicy.DYNAMIC if event.onion else AliasPolicy.STATIC
                    ),
                    timestamp=event.timestamp,
                    is_drop=False,
                )

            elif isinstance(event, AckEvent):
                self._renderer.mark_acked(
                    msg_id=event.msg_id,
                    text=event.text,
                    timestamp=event.timestamp,
                )

            elif isinstance(event, DropFailedEvent):
                self._renderer.mark_failed(msg_id=event.msg_id)

            elif isinstance(event, DropQueuedEvent):
                # Chat already renders the local drop line optimistically. The
                # structured success event stays useful for other UIs.
                pass

            elif isinstance(event, IncomingConnectionEvent):
                self._remember_peer(event.alias, event.onion)
                if event.alias not in self._session.pending_connections:
                    self._session.pending_connections.append(event.alias)
                self._print_translated(
                    event.event_type,
                    alias=event.alias,
                    onion=event.onion,
                )

            elif isinstance(event, ConnectionPendingEvent):
                self._remember_peer(event.alias, event.onion)
                if event.alias not in self._session.pending_connections:
                    self._session.pending_connections.append(event.alias)
                self._print_translated(
                    event.event_type,
                    alias=event.alias,
                    onion=event.onion,
                )

            elif isinstance(event, ConnectionConnectingEvent):
                self._remember_peer(event.alias, event.onion)
                self._print_translated(
                    event.event_type,
                    alias=event.alias,
                    onion=event.onion,
                )

            elif isinstance(event, ConnectionAutoAcceptedEvent):
                self._remember_peer(event.alias, event.onion)
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)
                self._print_translated(
                    event.event_type,
                    alias=event.alias,
                    onion=event.onion,
                )

            elif isinstance(event, ConnectionRetryEvent):
                self._remember_peer(event.alias, event.onion)
                self._print_translated(
                    event.event_type,
                    {'attempt': event.attempt, 'max_retries': event.max_retries},
                    alias=event.alias,
                    onion=event.onion,
                )

            elif isinstance(event, NoPendingConnectionEvent):
                if self._matches_focus_target(
                    self._session.pending_accept_focus_target,
                    alias=event.alias,
                    onion=event.onion,
                ):
                    self._session.pending_accept_focus_target = None
                self._remember_peer(event.alias, event.onion)
                self._print_translated(
                    event.event_type,
                    alias=event.alias,
                    onion=event.onion,
                )

            elif isinstance(event, PeerNotFoundEvent):
                if self._matches_focus_target(
                    self._session.pending_focus_target,
                    alias=event.target,
                    onion=event.target,
                ):
                    self._session.pending_focus_target = None
                if self._matches_focus_target(
                    self._session.pending_accept_focus_target,
                    alias=event.target,
                    onion=event.target,
                ):
                    self._session.pending_accept_focus_target = None
                self._print_translated(event.event_type, {'target': event.target})

            elif isinstance(event, MaxConnectionsReachedEvent):
                if self._matches_focus_target(
                    self._session.pending_focus_target,
                    alias=event.target,
                    onion=event.target,
                ):
                    self._session.pending_focus_target = None
                self._print_translated(
                    event.event_type,
                    {'max_conn': event.max_conn},
                    alias=event.target,
                )

            elif isinstance(event, ConnectionFailedEvent):
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)
                if self._matches_focus_target(
                    self._session.pending_focus_target,
                    alias=event.alias,
                    onion=event.onion,
                ):
                    self._session.pending_focus_target = None
                if self._matches_focus_target(
                    self._session.pending_accept_focus_target,
                    alias=event.alias,
                    onion=event.onion,
                ):
                    self._session.pending_accept_focus_target = None
                self._remember_peer(event.alias, event.onion)
                error_params: Dict[str, JsonValue] = {}
                if event.error:
                    error_params['error'] = event.error
                self._print_translated(
                    event.event_type,
                    error_params or None,
                    alias=event.alias,
                    onion=event.onion,
                )

            elif isinstance(event, ConnectionRejectedEvent):
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)
                if self._matches_focus_target(
                    self._session.pending_focus_target,
                    alias=event.alias,
                    onion=event.onion,
                ):
                    self._session.pending_focus_target = None
                if self._matches_focus_target(
                    self._session.pending_accept_focus_target,
                    alias=event.alias,
                    onion=event.onion,
                ):
                    self._session.pending_accept_focus_target = None
                self._remember_peer(event.alias, event.onion)
                self._print_translated(
                    event.event_type,
                    alias=event.alias,
                    onion=event.onion,
                )

            elif isinstance(event, TiebreakerRejectedEvent):
                # UI Usability: The collision event is muted because it functions transparently as a Mutual Connection / Silent Accept for the user in the live chat.
                pass

            elif isinstance(event, AutoReconnectAttemptEvent):
                self._remember_peer(event.alias, event.onion)
                self._print_translated(
                    event.event_type,
                    alias=event.alias,
                    onion=event.onion,
                )

            elif isinstance(event, ConnectedEvent):
                self._remember_peer(event.alias, event.onion)
                if event.alias not in self._session.active_connections:
                    self._session.active_connections.append(event.alias)
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)

                self._print_translated(
                    event.event_type,
                    alias=event.alias,
                    onion=event.onion,
                )

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=True)

                should_auto_focus: bool = False
                if self._matches_focus_target(
                    self._session.pending_focus_target,
                    alias=event.alias,
                    onion=event.onion,
                ):
                    self._session.pending_focus_target = None
                    should_auto_focus = True

                if self._matches_focus_target(
                    self._session.pending_accept_focus_target,
                    alias=event.alias,
                    onion=event.onion,
                ):
                    self._session.pending_accept_focus_target = None
                    should_auto_focus = True

                if should_auto_focus:
                    self._switch_focus(event.alias, sync_daemon=True)

            elif isinstance(event, DisconnectedEvent):
                self._remember_peer(event.alias, event.onion)
                self._print_translated(
                    event.event_type,
                    alias=event.alias,
                    onion=event.onion,
                )

                if event.alias in self._session.active_connections:
                    self._session.active_connections.remove(event.alias)
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)

                if self._session.focused_alias == event.alias:
                    self._renderer.set_focus(event.alias, is_live=False)

            elif isinstance(event, InboxNotificationEvent):
                self._remember_peer(event.alias, event.onion)
                if event.alias and event.alias == self._session.focused_alias:
                    self._cancel_buffered_notification(event.alias, event.onion)
                    self._ipc.send_command(MarkReadCommand(target=event.alias))
                elif event.alias:
                    self._queue_buffered_notification(
                        event.alias,
                        event.onion,
                        event.count,
                    )

            elif isinstance(event, InboxDataEvent):
                if event.alias and event.messages:
                    self._remember_peer(event.alias, event.onion)
                    messages_data_dict: List[Dict[str, JsonValue]] = [
                        {
                            'id': '',
                            'timestamp': m.timestamp,
                            'payload': m.payload,
                            'is_drop': m.is_drop,
                        }
                        for m in event.messages
                    ]
                    self._renderer.print_messages_batch(
                        messages_data_dict,
                        event.alias,
                        peer_onion=event.onion,
                        is_live_flush=event.is_live_flush,
                    )

            elif isinstance(event, RenameSuccessEvent):
                rename_onion: Optional[str] = (
                    event.onion or self._session.get_peer_onion(event.old_alias)
                )
                self._remember_peer(event.new_alias, rename_onion)
                if event.old_alias in self._session.active_connections:
                    self._session.active_connections.remove(event.old_alias)
                    self._session.active_connections.append(event.new_alias)
                if event.old_alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.old_alias)
                    self._session.pending_connections.append(event.new_alias)
                if self._session.pending_focus_target == event.old_alias:
                    self._session.pending_focus_target = event.new_alias
                if self._session.pending_accept_focus_target == event.old_alias:
                    self._session.pending_accept_focus_target = event.new_alias

                self._renderer.refresh_alias_bindings()

                if self._session.focused_alias == event.old_alias:
                    self._switch_focus(event.new_alias, hide_message=True)

            elif isinstance(event, ContactRemovedEvent):
                self._cancel_buffered_notification(event.alias, event.onion)
                self._session.forget_peer(event.onion)
                if event.alias in self._session.active_connections:
                    self._session.active_connections.remove(event.alias)
                if event.alias in self._session.pending_connections:
                    self._session.pending_connections.remove(event.alias)
                if self._matches_focus_target(
                    self._session.pending_focus_target,
                    alias=event.alias,
                    onion=event.onion,
                ):
                    self._session.pending_focus_target = None
                if self._matches_focus_target(
                    self._session.pending_accept_focus_target,
                    alias=event.alias,
                    onion=event.onion,
                ):
                    self._session.pending_accept_focus_target = None
                self._renderer.refresh_alias_bindings()
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
                self._remember_peer(event.alias, event.onion)
                self._switch_focus(event.alias)

            else:
                if (
                    hasattr(event, 'alias')
                    and not hasattr(event, 'new_alias')
                    and not hasattr(event, 'old_alias')
                ):
                    alias_attr: object = getattr(event, 'alias', None)
                    onion_attr: object = getattr(event, 'onion', None)
                    if isinstance(alias_attr, str):
                        self._remember_peer(
                            alias_attr,
                            onion_attr if isinstance(onion_attr, str) else None,
                        )

                params_raw = dataclasses.asdict(event)
                params = {
                    k: v
                    for k, v in params_raw.items()
                    if isinstance(v, (str, int, float, bool, type(None), list, dict))
                }
                target_alias = str(params.get('alias') or params.get('target') or '')
                event_onion = params.get('onion')
                self._print_translated(
                    event.event_type,
                    params,
                    target_alias if target_alias else None,
                    event_onion if isinstance(event_onion, str) else None,
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
        old_onion: Optional[str] = self._session.get_peer_onion(old_alias)

        if old_alias == alias:
            return

        self._session.focused_alias = alias
        is_live: bool = self._session.is_connected(alias)

        self._renderer.set_focus(alias, is_live)

        if sync_daemon:
            self._ipc.send_command(SwitchCommand(target=alias))

        if not hide_message:
            if alias:
                alias_onion: Optional[str] = self._session.get_peer_onion(alias)
                self._cancel_buffered_notification(
                    alias,
                    alias_onion,
                )
                self._print_peer_status(
                    "Switched focus to '{alias}'.",
                    StatusTone.INFO,
                    alias,
                    alias_onion,
                )
                self._ipc.send_command(MarkReadCommand(target=alias))
            elif old_alias:
                self._print_peer_status(
                    "Removed focus from '{alias}'.",
                    StatusTone.INFO,
                    old_alias,
                    old_onion,
                )
