"""
Module defining the NetworkManager Facade.
Provides a clean, strictly-typed API to the Daemon Engine while abstracting
the complex interactions between the Listener, Receiver, Controller, and Router.
"""

import threading
from typing import Dict, List, Callable, Tuple

from metor.core import TorManager
from metor.core.api import IpcEvent, DomainCode, JsonValue
from metor.core.daemon.crypto import Crypto
from metor.data import HistoryManager, ContactManager, MessageManager

# Local Package Imports
from metor.core.daemon.network.state import StateTracker
from metor.core.daemon.network.router import MessageRouter
from metor.core.daemon.network.controller import ConnectionController
from metor.core.daemon.network.receiver import StreamReceiver
from metor.core.daemon.network.listener import InboundListener


class NetworkManager:
    """Facade orchestrating network states, socket lifecycles, and application routing."""

    def __init__(
        self,
        tm: TorManager,
        cm: ContactManager,
        hm: HistoryManager,
        mm: MessageManager,
        crypto: Crypto,
        broadcast_callback: Callable[[IpcEvent], None],
        has_clients_callback: Callable[[], bool],
        stop_flag: threading.Event,
    ) -> None:
        """
        Initializes the NetworkManager and its isolated sub-components.

        Args:
            tm (TorManager): Tor process manager.
            cm (ContactManager): Address book manager.
            hm (HistoryManager): Event history manager.
            mm (MessageManager): Offline messages manager.
            crypto (Crypto): Cryptographic challenge/response engine.
            broadcast_callback (Callable[[IpcEvent], None]): Callback to broadcast IPC events.
            has_clients_callback (Callable[[], bool]): Callback to check for active UI clients.
            stop_flag (threading.Event): Global daemon termination flag.

        Returns:
            None
        """
        self._cm: ContactManager = cm
        self._state: StateTracker = StateTracker()

        self._router: MessageRouter = MessageRouter(
            cm=cm,
            hm=hm,
            mm=mm,
            state=self._state,
            broadcast_callback=broadcast_callback,
            has_clients_callback=has_clients_callback,
        )

        self._controller: ConnectionController = ConnectionController(
            tm=tm,
            cm=cm,
            hm=hm,
            mm=mm,
            crypto=crypto,
            state=self._state,
            router=self._router,
            broadcast_callback=broadcast_callback,
            stop_flag=stop_flag,
        )

        self._receiver: StreamReceiver = StreamReceiver(
            cm=cm,
            hm=hm,
            state=self._state,
            router=self._router,
            broadcast_callback=broadcast_callback,
            has_clients_callback=has_clients_callback,
            disconnect_cb=self._controller.disconnect,
            reject_cb=self._controller.reject,
        )

        # Inject the instantiated receiver into the controller to resolve circular execution
        self._controller.set_receiver(self._receiver)

        self._listener: InboundListener = InboundListener(
            tm=tm,
            cm=cm,
            hm=hm,
            crypto=crypto,
            state=self._state,
            router=self._router,
            receiver=self._receiver,
            broadcast_callback=broadcast_callback,
            stop_flag=stop_flag,
        )

    # --- LIFECYCLE DELEGATION ---

    def start_listener(self) -> None:
        """
        Starts the local Tor TCP listener in a background thread.

        Args:
            None

        Returns:
            None
        """
        self._listener.start_listener()

    def connect_to(self, target: str) -> None:
        """
        Initiates an outbound Tor connection to a peer.

        Args:
            target (str): The alias or onion address.

        Returns:
            None
        """
        self._controller.connect_to(target)

    def accept(self, target: str) -> None:
        """
        Approves a pending incoming connection request.

        Args:
            target (str): The target alias or onion.

        Returns:
            None
        """
        self._controller.accept(target)

    def reject(self, target: str, initiated_by_self: bool = True) -> None:
        """
        Rejects a connection request.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the rejection.

        Returns:
            None
        """
        self._controller.reject(target, initiated_by_self)

    def disconnect(self, target: str, initiated_by_self: bool = True) -> None:
        """
        Terminates an active connection safely.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the disconnect.

        Returns:
            None
        """
        self._controller.disconnect(target, initiated_by_self)

    def disconnect_all(self) -> None:
        """
        Forcefully disconnects all active and pending peers safely upon shutdown.

        Args:
            None

        Returns:
            None
        """
        self._controller.disconnect_all()

    def retunnel(self, target: str) -> None:
        """
        Forces a Tor circuit rotation and reconnects.

        Args:
            target (str): The target alias or onion address.

        Returns:
            None
        """
        self._controller.retunnel(target)

    # --- ROUTER DELEGATION ---

    def flush_ram_buffer(self, onion: str) -> None:
        """
        Flushes the headless RAM buffer to the UI and fires pending ACKs.

        Args:
            onion (str): The target onion to flush.

        Returns:
            None
        """
        self._router.flush_ram_buffer(onion)

    def force_fallback(
        self, target: str
    ) -> Tuple[bool, DomainCode, Dict[str, JsonValue]]:
        """
        Forces all unacknowledged outgoing live messages to the drop queue.

        Args:
            target (str): The target alias or onion address.

        Returns:
            Tuple[bool, DomainCode, Dict[str, JsonValue]]: A success flag, domain code and params.
        """
        return self._router.force_fallback(target)

    def send_message(self, target: str, msg: str, msg_id: str) -> None:
        """
        Sends a live chat message and buffers it for ACK verification.

        Args:
            target (str): The target alias or onion.
            msg (str): The message content.
            msg_id (str): The unique message identifier.

        Returns:
            None
        """
        self._router.send_message(target, msg, msg_id)

    # --- STATE DELEGATION ---

    def get_active_onions(self) -> List[str]:
        """
        Returns a snapshot of all currently connected and pending onions.

        Args:
            None

        Returns:
            List[str]: Active Tor connection onions.
        """
        return self._state.get_active_onions()

    def get_active_aliases(self) -> List[str]:
        """
        Returns a snapshot of currently connected aliases.

        Args:
            None

        Returns:
            List[str]: Active connection aliases.
        """
        return [
            self._cm.get_alias_by_onion(onion) or onion
            for onion in self._state.get_active_connections_keys()
        ]

    def get_pending_aliases(self) -> List[str]:
        """
        Returns a snapshot of aliases waiting for acceptance.

        Args:
            None

        Returns:
            List[str]: Pending connection aliases.
        """
        return [
            self._cm.get_alias_by_onion(onion) or onion
            for onion in self._state.get_pending_connections_keys()
        ]
