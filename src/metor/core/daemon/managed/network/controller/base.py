"""Thin facade class for the modular connection controller package."""

import threading
from typing import TYPE_CHECKING, Callable, Optional

from metor.core import TorManager
from metor.core.api import IpcEvent
from metor.core.daemon.managed.crypto import Crypto
from metor.data import ContactManager, HistoryManager, MessageManager

# Local Package Imports
from metor.core.daemon.managed.network.controller.reconnect import (
    ConnectionControllerReconnectMixin,
)
from metor.core.daemon.managed.network.controller.retunnel import (
    ConnectionControllerRetunnelMixin,
)
from metor.core.daemon.managed.network.controller.session.manager import (
    ConnectionControllerSessionMixin,
)
from metor.core.daemon.managed.network.router import MessageRouter
from metor.core.daemon.managed.network.state import StateTracker

if TYPE_CHECKING:
    from metor.core.daemon.managed.network.receiver import StreamReceiver
    from metor.data.profile import Config


class ConnectionController(
    ConnectionControllerSessionMixin,
    ConnectionControllerReconnectMixin,
    ConnectionControllerRetunnelMixin,
):
    """Orchestrates outbound connections, auto-reconnects, and retunneling."""

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        crypto: Crypto,
        state: StateTracker,
        router: MessageRouter,
        broadcast_callback: Callable[[IpcEvent], None],
        has_live_consumers_callback: Callable[[], bool],
        stop_flag: threading.Event,
        config: 'Config',
    ) -> None:
        """
        Initializes the ConnectionController.

        Args:
            tm (TorManager): Tor process manager.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Offline messages manager.
            crypto (Crypto): Cryptographic engine.
            state (StateTracker): The thread-safe state container.
            router (MessageRouter): The application-layer message router.
            broadcast_callback (Callable): IPC broadcaster.
            has_live_consumers_callback (Callable[[], bool]): Callback to check whether an interactive live consumer is attached.
            stop_flag (threading.Event): Global daemon termination flag.
            config (Config): The profile configuration instance.

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._cm: ContactManager = cm
        self._hm: HistoryManager = hm
        self._mm: MessageManager = mm
        self._crypto: Crypto = crypto
        self._state: StateTracker = state
        self._router: MessageRouter = router
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._has_live_consumers: Callable[[], bool] = has_live_consumers_callback
        self._stop_flag: threading.Event = stop_flag
        self._config: 'Config' = config

        self._receiver: Optional['StreamReceiver'] = None
        self._live_reconnect_queue: list[str] = []
        self._live_reconnect_lock: threading.Lock = threading.Lock()
        threading.Thread(target=self._live_reconnect_worker, daemon=True).start()

    def set_receiver(self, receiver: 'StreamReceiver') -> None:
        """
        Injects the StreamReceiver dependency to avoid circular imports.

        Args:
            receiver (StreamReceiver): The StreamReceiver instance.

        Returns:
            None
        """
        self._receiver = receiver
