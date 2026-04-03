"""Retunnel lifecycle logic for the modular connection controller package."""

import socket
import threading
from typing import TYPE_CHECKING, Optional, Tuple

from metor.core.api import (
    ConnectionActor,
    ConnectionOrigin,
    ConnectionRetryEvent,
    EventType,
    PeerNotFoundEvent,
    RetunnelInitiatedEvent,
    create_event,
)
from metor.data import HistoryActor, HistoryEvent

# Local Package Imports
from metor.core.daemon.network.controller.support import (
    ConnectionControllerSupportMixin,
)


class ConnectionControllerRetunnelMixin(ConnectionControllerSupportMixin):
    """Implements retunnel retries and explicit retunnel requests."""

    if TYPE_CHECKING:

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

    def _retunnel_reconnect_retry_worker(self, onion: str) -> None:
        """
        Waits briefly and retries one retunnel reconnect attempt if the flow is still unresolved.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        try:
            self._sleep_retunnel_reconnect_delay()
            if self._stop_flag.is_set():
                return

            if not self._state.is_retunneling(onion):
                return

            if self._state.is_connected_or_pending(onion):
                return

            self.connect_to(onion, origin=ConnectionOrigin.RETUNNEL)
        finally:
            self._state.finish_retunnel_recovery_retry(onion)

    def _schedule_retunnel_recovery_retry(
        self,
        alias: str,
        onion: str,
        error: str,
    ) -> bool:
        """
        Schedules one bounded delayed retunnel recovery attempt before declaring the flow failed.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            error (str): The failure detail for the eventual fatal failure path.

        Returns:
            bool: True if the flow remains recoverable or one retry was scheduled.
        """
        retry_limit: int = self._get_retunnel_recovery_retries()

        self._state.clear_scheduled_auto_reconnect(onion)
        self._mark_live_reconnect_grace(onion)

        if self._state.has_retunnel_recovery_retry_pending(onion):
            return True

        attempt: Optional[int] = self._state.reserve_retunnel_recovery_retry(
            onion,
            retry_limit,
        )
        if attempt is None:
            self._broadcast_retunnel_failure(alias, onion, error)
            return False

        self._broadcast(
            ConnectionRetryEvent(
                alias=alias,
                onion=onion,
                attempt=attempt,
                max_retries=retry_limit,
                origin=ConnectionOrigin.RETUNNEL,
                actor=ConnectionActor.SYSTEM,
            )
        )
        threading.Thread(
            target=self._retunnel_reconnect_retry_worker,
            args=(onion,),
            daemon=True,
        ).start()
        return True

    def retunnel(self, target: str) -> None:
        """
        Forces a Tor circuit rotation and reconnects to the target.

        Args:
            target (str): The target alias or onion address.

        Returns:
            None
        """
        resolved: Optional[Tuple[str, str]] = self._cm.resolve_target(target)
        if not resolved:
            self._broadcast(PeerNotFoundEvent(target=target))
            return
        alias, onion = resolved

        if not self._state.is_connected_or_pending(onion):
            self._broadcast(
                create_event(
                    EventType.RETUNNEL_FAILED,
                    {
                        'alias': alias,
                        'onion': onion,
                        'error': 'No active connection to retunnel',
                    },
                )
            )
            return

        self._broadcast(RetunnelInitiatedEvent(alias=alias, onion=onion))
        self._hm.log_event(
            HistoryEvent.LIVE_RETUNNEL_INITIATED,
            onion,
            actor=HistoryActor.LOCAL,
        )

        success, event_type, params = self._tm.rotate_circuits()
        if not success:
            params['alias'] = alias
            params['onion'] = onion
            self._broadcast(
                create_event(event_type or EventType.RETUNNEL_FAILED, params)
            )
            return

        self._state.mark_retunnel_started(onion)
        self.disconnect(
            onion,
            initiated_by_self=True,
            suppress_events=True,
            origin=ConnectionOrigin.RETUNNEL,
        )
        self._mark_live_reconnect_grace(onion)
        self._sleep_retunnel_reconnect_delay()

        self._state.mark_retunnel_reconnect(onion)
        self.connect_to(onion, origin=ConnectionOrigin.RETUNNEL)
