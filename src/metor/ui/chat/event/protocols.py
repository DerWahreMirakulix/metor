"""Protocol definitions for the modular chat event helpers."""

import threading
from typing import Dict, Optional, Protocol, Type

from metor.core.api import EventType, JsonValue, MarkReadCommand
from metor.ui.chat.ipc import IpcClient
from metor.ui.chat.renderer import Renderer
from metor.ui.chat.session import Session


class EventHandlerProtocol(Protocol):
    """Structural type for the chat event helper functions."""

    _ipc: IpcClient
    _session: Session
    _renderer: Renderer
    _init_event: threading.Event
    _conn_event: threading.Event
    _mark_read_command_type: Type[MarkReadCommand]

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
