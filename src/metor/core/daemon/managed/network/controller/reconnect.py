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
from metor.data import SettingKey

# Local Package Imports
from metor.core.daemon.managed.network.controller.support import (
    ConnectionControllerSupportMixin,
)
from metor.core.daemon.managed.network.state.types import PendingConnectionReason


class ConnectionControllerReconnectMixin(ConnectionControllerSupportMixin):
    """Implements deferred auto-accept and failure-only live reconnect flows."""

    if TYPE_CHECKING:

        def accept(
            self,
            target: str,
            origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
            *,
            expected_pending: Optional[socket.socket] = None,
        ) -> None:
            """
            Accepts one pending live connection through the session facade.

            Args:
                target (str): The alias or onion to accept.
                origin (ConnectionOrigin): The semantic origin of the accepted flow.

            Returns:
                None
            """
            ...

        def connect_to(
            self,
            target: str,
            origin: ConnectionOrigin = ConnectionOrigin.MANUAL,
            *,
            expected_context_generation: Optional[int] = None,
        ) -> None:
            """
            Starts one outbound live connection attempt through the session facade.

            Args:
                target (str): The alias or onion to connect to.
                origin (ConnectionOrigin): The semantic origin of the connection attempt.

            Returns:
                None
            """
            ...

        def disconnect(
            self,
            target: str,
            initiated_by_self: bool = True,
            is_fallback: bool = False,
            socket_to_close: Optional[socket.socket] = None,
            suppress_events: bool = False,
            origin: Optional[ConnectionOrigin] = None,
        ) -> None:
            """
            Tears down one live connection flow through the session facade.

            Args:
                target (str): The alias or onion to disconnect.
                initiated_by_self (bool): Whether the local side initiated the disconnect.
                is_fallback (bool): Whether the disconnect is handling a transport failure.
                socket_to_close (Optional[socket.socket]): Optional duplicate socket to close.
                suppress_events (bool): Whether outward-facing lifecycle events should be suppressed.
                origin (Optional[ConnectionOrigin]): The semantic origin of the disconnected flow.

            Returns:
                None
            """
            ...

    def _enqueue_live_reconnect(self, onion: str) -> bool:
        """
        Adds one peer to the reconnect queue once without duplicating queue entries.

        Args:
            onion (str): The target onion identity.

        Returns:
            bool: True if the peer was added to the queue.
        """
        generation = self._state.accepted_live_context_generation(onion)
        entry = (onion, generation)
        with self._live_reconnect_lock:
            if entry in self._live_reconnect_queue:
                return False
            self._live_reconnect_queue.append(entry)
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
            with self._operation_lock, self._state.snapshot_barrier():
                pending = self._state.pending_identity(onion)
                if (
                    self._stop_flag.is_set()
                    or pending is None
                    or self._state.get_pending_connection_reason(onion)
                    is not PendingConnectionReason.CONSUMER_ABSENT
                ):
                    continue
                expected_pending = pending[0]
                auto_accept_origin = (
                    self._state.get_pending_connection_origin(onion)
                    or ConnectionOrigin.INCOMING
                )
                accepted_generation = self._state.accepted_live_context_generation(
                    onion
                )

            alias: Optional[str] = self._cm.ensure_alias_for_onion(onion)
            if not alias:
                continue

            with self._operation_lock, self._state.snapshot_barrier():
                current_pending = self._state.pending_identity(onion)
                if (
                    self._stop_flag.is_set()
                    or current_pending is None
                    or current_pending[0] is not expected_pending
                    or self._state.get_pending_connection_reason(onion)
                    is not PendingConnectionReason.CONSUMER_ABSENT
                    or (
                        self._state.get_pending_connection_origin(onion)
                        or ConnectionOrigin.INCOMING
                    )
                    is not auto_accept_origin
                    or self._state.accepted_live_context_generation(onion)
                    != accepted_generation
                    or (
                        auto_accept_origin
                        in {
                            ConnectionOrigin.AUTO_RECONNECT,
                            ConnectionOrigin.GRACE_RECONNECT,
                            ConnectionOrigin.RETUNNEL,
                        }
                        and accepted_generation is None
                    )
                ):
                    continue
                self._broadcast(
                    ConnectionAutoAcceptedEvent(
                        alias=alias,
                        onion=onion,
                        origin=auto_accept_origin,
                        actor=ConnectionActor.SYSTEM,
                    )
                )
                self.accept(
                    onion,
                    origin=auto_accept_origin,
                    expected_pending=expected_pending,
                )

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
                generation: Optional[int] = None

                with self._live_reconnect_lock:
                    if self._live_reconnect_queue:
                        onion, generation = self._live_reconnect_queue.pop(0)

                if onion:
                    if (
                        generation is not None
                        and self._state.accepted_live_context_generation(onion)
                        != generation
                    ):
                        continue
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
                    recovery_deadline = self._state.accepted_live_recovery_deadline(
                        onion
                    )
                    if recovery_deadline is not None:
                        remaining = recovery_deadline - time.monotonic()
                        handshake_budget = self._config.get_float(
                            SettingKey.TOR_TIMEOUT
                        )
                        backoff = min(backoff, max(0.0, remaining - handshake_budget))

                    self._sleep_live_reconnect_delay(backoff)
                    if (
                        generation is not None
                        and self._state.accepted_live_context_generation(onion)
                        != generation
                    ):
                        continue
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
                            expected_context_generation=generation,
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
        onions = set(self._state.get_active_onions()) | {
            onion
            for onion in self._state.get_relevant_live_onions()
            if self._state.has_unrevoked_live_context(onion)
        }
        for onion in onions:
            with self._operation_lock, self._state.snapshot_barrier():
                outbound = self._state.pop_outbound_socket(onion)
                try:
                    self.disconnect(onion, initiated_by_self=True)
                finally:
                    self._state.revoke_accepted_live_context(onion)
                    if outbound is not None:
                        self._state.retire_connection(outbound)
