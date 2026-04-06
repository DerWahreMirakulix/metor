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
    ) -> None: ...

    def _cancel_buffered_notification(
        self,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> None: ...

    def _queue_buffered_notification(
        self,
        alias: str,
        onion: Optional[str],
        count: int,
    ) -> None: ...

    def _print_translated(
        self,
        code: EventType,
        params: Optional[Dict[str, JsonValue]] = None,
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> None: ...

    def _matches_focus_target(
        self,
        target: Optional[str],
        alias: Optional[str] = None,
        onion: Optional[str] = None,
    ) -> bool: ...

    def _switch_focus(
        self,
        alias: Optional[str],
        hide_message: bool = False,
        sync_daemon: bool = False,
    ) -> None: ...
