"""Thin composition root for application-layer message routing."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional, cast

from metor.core.api import AutoFallbackQueuedEvent, IpcEvent
from metor.data import ContactManager, HistoryManager, MessageManager

# Local Package Imports
from ..state import StateTracker
from ...notify import NotificationPayload
from .drop import DropMessageRouting
from .fallback import FallbackRouting
from .live import LiveMessageRouting

if TYPE_CHECKING:
    from metor.data.profile import Config


class MessageRouter(FallbackRouting, LiveMessageRouting, DropMessageRouting):
    """Composes routing policies while keeping integration ownership explicit."""

    def __init__(
        self,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        state: StateTracker,
        broadcast_callback: Callable[[IpcEvent], None],
        has_clients_callback: Callable[[], bool],
        has_live_consumers_callback: Callable[[], bool],
        notify_callback: Callable[[NotificationPayload], None],
        config: 'Config',
    ) -> None:
        """Initializes the composed message-routing subsystem.

        Args:
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Message persistence manager.
            state (StateTracker): Connection and delivery state tracker.
            broadcast_callback (Callable[[IpcEvent], None]): IPC event broadcaster.
            has_clients_callback (Callable[[], bool]): Connected-client check.
            has_live_consumers_callback (Callable[[], bool]): Live-consumer check.
            notify_callback (Callable[[NotificationPayload], None]): Detached notifier.
            config (Config): Profile configuration.

        Returns:
            None
        """
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._state: StateTracker = state
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._has_clients_callback: Callable[[], bool] = has_clients_callback
        self._has_live_consumers_callback: Callable[[], bool] = (
            has_live_consumers_callback
        )
        self._notify_callback: Callable[[NotificationPayload], None] = notify_callback
        self._config: 'Config' = config

    def _remember_message_request_id(
        self, msg_id: str, request_id: Optional[str]
    ) -> None:
        """Stores optional request correlation in shared state.

        Args:
            msg_id (str): The logical message identifier.
            request_id (Optional[str]): The originating IPC request identifier.

        Returns:
            None
        """
        remember = getattr(self._state, 'remember_message_request_id', None)
        if callable(remember):
            remember(msg_id, request_id)

    def _pop_message_request_id(self, msg_id: str) -> Optional[str]:
        """Retrieves and removes optional request correlation from shared state.

        Args:
            msg_id (str): The logical message identifier.

        Returns:
            Optional[str]: The originating request identifier, if present.
        """
        pop = getattr(self._state, 'pop_message_request_id', None)
        return cast(Optional[str], pop(msg_id)) if callable(pop) else None

    def _notify_inbox(self, alias: str, onion: Optional[str]) -> None:
        """Emits one detached inbox notification without IPC clients.

        Args:
            alias (str): The peer alias.
            onion (Optional[str]): The peer onion identity.

        Returns:
            None
        """
        self._notify_callback(
            NotificationPayload(
                kind='inbox_notification',
                peer_alias=alias,
                peer_onion=onion,
                count=1,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )

    @staticmethod
    def _auto_fallback_event(
        alias: str, onion: str, msg_id: str, request_id: Optional[str]
    ) -> AutoFallbackQueuedEvent:
        """Builds the IPC event for automatic live-to-drop fallback.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            msg_id (str): The stable logical message identifier.
            request_id (Optional[str]): The originating IPC request identifier.

        Returns:
            AutoFallbackQueuedEvent: The fallback notification event.
        """
        return AutoFallbackQueuedEvent(
            alias=alias, onion=onion, msg_id=msg_id, request_id=request_id
        )
