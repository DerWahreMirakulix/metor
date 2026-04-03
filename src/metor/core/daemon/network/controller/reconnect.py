"""Reconnect-worker logic for the modular connection controller package."""

import socket
import secrets
import time
from typing import TYPE_CHECKING, Optional

from metor.core.api import (
    ConnectionActor,
    ConnectionAutoAcceptedEvent,
    ConnectionOrigin,
)
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.network.controller.support import (
    ConnectionControllerSupportMixin,
)
from metor.core.daemon.network.state.types import PendingConnectionReason


class ConnectionControllerReconnectMixin(ConnectionControllerSupportMixin):
    """Implements deferred auto-accept and failure-only live reconnect flows."""

    if TYPE_CHECKING:

        def accept(
            self,
            target: str,
            origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
        ) -> None: ...

        def connect_to(
            self,
            target: str,
            origin: ConnectionOrigin = ConnectionOrigin.MANUAL,
        ) -> None: ...

        def disconnect(
            self,
            target: str,
            initiated_by_self: bool = True,
            is_fallback: bool = False,
            socket_to_close: Optional[socket.socket] = None,
            suppress_events: bool = False,
            origin: Optional[ConnectionOrigin] = None,
        ) -> None: ...

    def _enqueue_live_reconnect(self, onion: str) -> bool:
        """
        Adds one peer to the reconnect queue once without duplicating queue entries.

        Args:
            onion (str): The target onion identity.

        Returns:
            bool: True if the peer was added to the queue.
        """
        with self._live_reconnect_lock:
            if onion in self._live_reconnect_queue:
                return False
            self._live_reconnect_queue.append(onion)
            return True

    def on_live_consumer_available(self) -> None:
        """
        Re-evaluates internally deferred inbound live sockets when a consumer appears.

        Args:
            None

        Returns:
            None
        """
        for onion in self._state.get_pending_connections_with_reason(
            PendingConnectionReason.CONSUMER_ABSENT
        ):
            alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)
            if not alias:
                continue

            auto_accept_origin: ConnectionOrigin = (
                self._state.get_pending_connection_origin(onion)
                or ConnectionOrigin.INCOMING
            )

            self._broadcast(
                ConnectionAutoAcceptedEvent(
                    alias=alias,
                    onion=onion,
                    origin=auto_accept_origin,
                    actor=ConnectionActor.SYSTEM,
                )
            )
            self.accept(onion, origin=auto_accept_origin)

    def _live_reconnect_worker(self) -> None:
        """
        Background thread handling failure-only reconnect attempts with randomized backoff.
        Enforces Thread-Safety by catching unexpected states to prevent silent worker crashes.

        Args:
            None

        Returns:
            None
        """
        while not self._stop_flag.is_set():
            time.sleep(Constants.WORKER_SLEEP_SLOW_SEC)
            try:
                onion: Optional[str] = None

                with self._live_reconnect_lock:
                    if self._live_reconnect_queue:
                        onion = self._live_reconnect_queue.pop(0)

                if onion:
                    if not self._state.has_scheduled_auto_reconnect(onion):
                        continue

                    if self._state.get_connection(onion):
                        self._state.clear_scheduled_auto_reconnect(onion)
                        continue

                    pending_reason: Optional[PendingConnectionReason] = (
                        self._state.get_pending_connection_reason(onion)
                    )

                    if pending_reason is PendingConnectionReason.CONSUMER_ABSENT:
                        self._enqueue_live_reconnect(onion)
                        continue

                    if pending_reason is PendingConnectionReason.USER_ACCEPT:
                        self._state.clear_scheduled_auto_reconnect(onion)
                        continue

                    reconnect_delay_sec: float = self._get_live_reconnect_delay()
                    if reconnect_delay_sec <= 0:
                        self._state.clear_scheduled_auto_reconnect(onion)
                        continue

                    if not self._can_auto_accept_live():
                        self._enqueue_live_reconnect(onion)
                        continue

                    backoff: float = reconnect_delay_sec + (
                        secrets.randbelow(Constants.LIVE_RECONNECT_JITTER_MAX_MS)
                        / Constants.LIVE_RECONNECT_JITTER_DIVISOR
                    )

                    self._sleep_live_reconnect_delay(backoff)
                    if not self._state.has_scheduled_auto_reconnect(onion):
                        continue

                    if self._state.get_connection(onion):
                        self._state.clear_scheduled_auto_reconnect(onion)
                        continue

                    pending_reason = self._state.get_pending_connection_reason(onion)
                    if pending_reason is PendingConnectionReason.CONSUMER_ABSENT:
                        self._enqueue_live_reconnect(onion)
                        continue

                    if pending_reason is PendingConnectionReason.USER_ACCEPT:
                        self._state.clear_scheduled_auto_reconnect(onion)
                        continue

                    if (
                        not self._state.is_connected_or_pending(onion)
                        and not self._stop_flag.is_set()
                    ):
                        self.connect_to(
                            onion,
                            origin=ConnectionOrigin.AUTO_RECONNECT,
                        )
            except Exception:
                pass

    def disconnect_all(self) -> None:
        """
        Forcefully disconnects all active and pending peers safely upon daemon shutdown.

        Args:
            None

        Returns:
            None
        """
        for onion in self._state.get_active_onions():
            self.disconnect(onion, initiated_by_self=True)
