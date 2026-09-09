"""Protocol definitions for the modular chat event helpers."""

import threading
from typing import Callable, Dict, List, Optional, Protocol, Type

from metor.core.api import EventType, JsonValue, MarkReadCommand
from metor.ui.terminal.chat.ipc import IpcClient
from metor.ui.terminal.chat.renderer import ChatRenderer
from metor.ui.terminal.chat.session import Session


class EventHandlerProtocol(Protocol):
    """Structural type for the chat event helper functions."""

    _ipc: IpcClient
    _session: Session
    _renderer: ChatRenderer
    _init_event: threading.Event
    _conn_event: threading.Event
    _mark_read_command_type: Type[MarkReadCommand]
    _has_auto_reconnect: Callable[[], bool]

    def _remember_peer(
        self,
        alias: Optional[str],
        onion: Optional[str],
    ) -> None:
        """Caches peer alias/onion in the session so later events can resolve them."""
        ...

    def _cancel_buffered_notification(
        self,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> None:
        """Cancels any pending buffered unread notification for the given peer."""
        ...

    def _queue_buffered_notification(
        self,
        alias: str,
        onion: Optional[str],
        count: int,
    ) -> None:
        """Enqueues a delayed unread notification for a backgrounded peer."""
        ...

    def _print_translated(
        self,
        code: EventType,
        params: Optional[Dict[str, JsonValue]] = None,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> None:
        """Translates one event code to a localized string and writes it to the renderer."""
        ...

    def _matches_focus_target(
        self,
        target: Optional[str],
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> bool:
        """Returns True when the peer identified by alias/onion matches the current focus target."""
        ...

    def _switch_focus(
        self,
        alias: Optional[str],
        hide_message: bool = False,
        sync_daemon: bool = False,
    ) -> None:
        """Switches the active chat focus to the given peer alias."""
        ...

    def _was_pushed_live_msg_id(self, msg_id: str) -> bool:
        """Returns True when the live message id was already pushed to the UI."""
        ...

    def _consume_pushed_live_msg_ids(self, msg_ids: List[str]) -> None:
        """Consumes the given live-pushed message ids from the tracking set."""
        ...

    def _remember_pushed_live_msg_id(self, msg_id: str) -> None:
        """Tracks one live-pushed message id to deduplicate inbox rendering."""
        ...
