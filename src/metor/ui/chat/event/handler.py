"""Central event handler for incoming daemon IPC events in chat mode."""

import threading
from typing import Callable, Dict, Optional, Type

from metor.core.api import (
    EventType,
    IpcEvent,
    JsonValue,
    MarkReadCommand,
    SwitchCommand,
)
from metor.ui import AliasPolicy, StatusTone, Translator
from metor.utils import clean_onion

# Local Package Imports
from metor.ui.chat.event.content import handle_content_event
from metor.ui.chat.event.models import BufferedInboxNotification
from metor.ui.chat.event.state import handle_state_event
from metor.ui.chat.event.transport import handle_transport_event
from metor.ui.chat.ipc import IpcClient
from metor.ui.chat.models import ChatMessageType
from metor.ui.chat.renderer import Renderer
from metor.ui.chat.session import Session


class EventHandler:
    """Processes incoming strictly-typed IPC events from the daemon."""

    _mark_read_command_type: Type[MarkReadCommand] = MarkReadCommand

    def __init__(
        self,
        ipc: IpcClient,
        session: Session,
        renderer: Renderer,
        init_event: threading.Event,
        conn_event: threading.Event,
        get_notification_buffer_seconds: Callable[[], float],
        has_auto_reconnect: Callable[[], bool],
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
            has_auto_reconnect (Callable[[], bool]): Lazy accessor for whether automatic reconnect is enabled locally.

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
        self._has_auto_reconnect: Callable[[], bool] = has_auto_reconnect
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
            pending.onion,
            pending.alias,
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

    def _handle_generic_event(self, event: IpcEvent) -> None:
        """
        Handles generic event rendering not covered by focused helper modules.

        Args:
            event (IpcEvent): The strongly-typed event received from the Daemon.

        Returns:
            None
        """
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

        params_raw = event.__dict__.copy()
        params = {
            key: value
            for key, value in params_raw.items()
            if isinstance(value, (str, int, float, bool, type(None), list, dict))
        }
        target_alias = str(params.get('alias') or params.get('target') or '')
        event_onion = params.get('onion')
        self._print_translated(
            event.event_type,
            params,
            target_alias if target_alias else None,
            event_onion if isinstance(event_onion, str) else None,
        )

    def handle(self, event: IpcEvent) -> None:
        """
        Routes a single IPC event DTO to the appropriate focused helper path.

        Args:
            event (IpcEvent): The strongly-typed event received from the Daemon.

        Returns:
            None
        """
        if handle_content_event(self, event):
            return
        if handle_transport_event(self, event):
            return
        if handle_state_event(self, event):
            return
        self._handle_generic_event(event)

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
        self._renderer.set_focus(alias, self._session.get_transport_state(alias))

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
