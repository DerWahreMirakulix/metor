"""Lifecycle facade for asynchronous drop delivery."""

import threading
import time
from typing import TYPE_CHECKING, Callable, Dict, Optional

from metor.core.api import (
    EventType,
    IpcEvent,
    JsonValue,
    RetunnelInitiatedEvent,
    RetunnelSuccessEvent,
    create_event,
    get_current_request_id,
)
from metor.core.tor import TorManager
from metor.data import HistoryManager, MessageManager
from metor.data.blob import BlobStore
from metor.utils import Constants

# Local Package Imports
from ..crypto import Crypto
from ..network import StateTracker
from .delivery import DropDelivery
from .tunnel import DropTunnelManager

if TYPE_CHECKING:
    from metor.data.profile import Config


class OutboxWorker:
    """Runs drop delivery and exposes outbox lifecycle operations."""

    def __init__(
        self,
        tm: TorManager,
        mm: MessageManager,
        hm: HistoryManager,
        crypto: Crypto,
        broadcast_callback: Callable[[IpcEvent], None],
        stop_flag: threading.Event,
        config: 'Config',
        state: StateTracker,
        error_callback: Optional[Callable[[str], None]] = None,
        blob_store: Optional[BlobStore] = None,
        operation_lock: Optional[threading.RLock] = None,
    ) -> None:
        """Composes the outbox worker, delivery, and tunnel components.

        Args:
            tm (TorManager): Tor network manager for outbound connections.
            mm (MessageManager): Pending-message persistence manager.
            hm (HistoryManager): Delivery history manager.
            crypto (Crypto): Peer handshake signing service.
            broadcast_callback (Callable[[IpcEvent], None]): IPC event broadcaster.
            stop_flag (threading.Event): Worker shutdown signal.
            config (Config): Profile configuration.
            state (StateTracker): Shared transport and request-correlation state.
            error_callback (Optional[Callable[[str], None]]): Optional callback for
                unexpected worker-loop failures.
            blob_store (Optional[BlobStore]): Profile object store for Voice drops.
            operation_lock (Optional[threading.RLock]): State publication barrier.

        Returns:
            None
        """
        self._tm: TorManager = tm
        self._broadcast: Callable[[IpcEvent], None] = broadcast_callback
        self._stop_flag: threading.Event = stop_flag
        self._state: StateTracker = state
        self._error_callback: Optional[Callable[[str], None]] = error_callback
        self._tunnels: DropTunnelManager = DropTunnelManager(
            tm=tm,
            hm=hm,
            crypto=crypto,
            state=state,
            config=config,
        )
        self._delivery: DropDelivery = DropDelivery(
            mm=mm,
            hm=hm,
            state=state,
            tunnels=self._tunnels,
            broadcast_callback=broadcast_callback,
            stop_flag=stop_flag,
            config=config,
            blob_store=blob_store,
            operation_lock=operation_lock,
        )
        self._worker_thread: Optional[threading.Thread] = None

    def remember_message_request_id(
        self, msg_id: str, request_id: Optional[str]
    ) -> None:
        """Stores request correlation for one queued drop message.

        Args:
            msg_id (str): The logical message identifier.
            request_id (Optional[str]): The originating IPC request identifier.

        Returns:
            None
        """
        self._state.remember_message_request_id(msg_id, request_id)

    def start(self) -> None:
        """Starts the worker loop in a background thread.

        Args:
            None

        Returns:
            None
        """
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_thread = threading.Thread(target=self._loop, daemon=True)
        self._worker_thread.start()

    def stop(self) -> None:
        """Stops the worker loop and closes all cached tunnels.

        Args:
            None

        Returns:
            None
        """
        self._stop_flag.set()
        self._tunnels.close_all()
        if (
            self._worker_thread
            and self._worker_thread.is_alive()
            and threading.current_thread() is not self._worker_thread
        ):
            self._worker_thread.join(
                timeout=(
                    Constants.WORKER_SLEEP_SLOW_SEC + Constants.THREAD_POLL_TIMEOUT
                )
            )

    def reset_tunnel(self, onion: str) -> None:
        """Closes a cached tunnel so the next send establishes a fresh route.

        Args:
            onion (str): The target onion identity.

        Returns:
            None
        """
        self._tunnels.close(onion)

    def retunnel(self, onion: str, alias: str) -> None:
        """Rotates circuits and discards the peer's cached drop tunnel.

        Args:
            onion (str): The target onion identity.
            alias (str): The strict alias for UI feedback.

        Returns:
            None
        """
        request_id: Optional[str] = get_current_request_id()
        self._broadcast(
            RetunnelInitiatedEvent(
                alias=alias,
                onion=onion,
                request_id=request_id,
            )
        )
        self._tunnels.close(onion)
        success, event_type, params = self._tm.rotate_circuits()
        if not success:
            failure_params: Dict[str, JsonValue] = {'alias': alias, 'onion': onion}
            failure_params.update(params)
            self._broadcast(
                create_event(event_type or EventType.RETUNNEL_FAILED, failure_params)
            )
            return
        self._broadcast(
            RetunnelSuccessEvent(
                alias=alias,
                onion=onion,
                request_id=request_id,
            )
        )

    def _loop(self) -> None:
        """Processes pending drops and tunnel cleanup until shutdown.

        Args:
            None

        Returns:
            None
        """
        while not self._stop_flag.is_set():
            time.sleep(Constants.WORKER_SLEEP_SLOW_SEC)
            try:
                self._delivery.process_pending()
                self._tunnels.cleanup(self._delivery.is_drop_standby_allowed())
            except Exception:
                self._report_internal_error(
                    'Outbox worker loop recovered from an unexpected runtime error.'
                )
        self._tunnels.close_all()

    def _report_internal_error(self, message: str) -> None:
        """Emits one best-effort runtime error callback.

        Args:
            message (str): The console-safe runtime error message.

        Returns:
            None
        """
        if self._error_callback is None:
            return
        try:
            self._error_callback(message)
        except Exception:
            pass
