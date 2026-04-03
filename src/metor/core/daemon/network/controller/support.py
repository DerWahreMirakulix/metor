"""Shared support logic for the modular connection controller package."""

import socket
import threading
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from metor.core import TorManager
from metor.core.api import (
    ConnectionActor,
    ConnectionOrigin,
    EventType,
    IpcEvent,
    JsonValue,
    create_event,
)
from metor.core.daemon.crypto import Crypto
from metor.data import (
    ContactManager,
    HistoryActor,
    HistoryManager,
    MessageManager,
    SettingKey,
)
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.network.router import MessageRouter
from metor.core.daemon.network.state import StateTracker

if TYPE_CHECKING:
    from metor.core.daemon.network.receiver import StreamReceiver
    from metor.data.profile.config import Config


class ConnectionControllerSupportMixin:
    """Provides shared attributes and helper methods for controller mixins."""

    _tm: TorManager
    _cm: ContactManager
    _hm: HistoryManager
    _mm: MessageManager
    _crypto: Crypto
    _state: StateTracker
    _router: MessageRouter
    _broadcast: Callable[[IpcEvent], None]
    _has_live_consumers: Callable[[], bool]
    _stop_flag: threading.Event
    _config: 'Config'
    _receiver: Optional['StreamReceiver']
    _live_reconnect_queue: List[str]
    _live_reconnect_lock: threading.Lock

    def _is_inflight_outbound_socket(self, onion: str, sock: socket.socket) -> bool:
        """
        Checks whether a callback socket belongs to the current outbound attempt.

        Args:
            onion (str): The peer onion identity.
            sock (socket.socket): The callback socket instance.

        Returns:
            bool: True if the socket is the current in-flight outbound attempt.
        """
        return self._state.is_current_outbound_socket(onion, sock)

    def _broadcast_retunnel_failure(
        self,
        alias: str,
        onion: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Clears retunnel state and emits the failure lifecycle for one peer.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            error (Optional[str]): Optional failure detail.

        Returns:
            None
        """
        self._state.clear_retunnel_flow(onion)
        self._broadcast(
            create_event(
                EventType.DISCONNECTED,
                {
                    'alias': alias,
                    'onion': onion,
                    'actor': ConnectionActor.SYSTEM,
                    'origin': ConnectionOrigin.RETUNNEL,
                },
            )
        )
        params: Dict[str, JsonValue] = {'alias': alias, 'onion': onion}
        if error:
            params['error'] = error
        self._broadcast(create_event(EventType.RETUNNEL_FAILED, params))

    def _discard_outbound_attempt_if_idle(self, onion: str) -> None:
        """
        Clears outbound-attempt state only when no newer connection flow is active.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        if self._state.is_connected_or_pending(onion):
            return
        if self._state.has_outbound_attempt(onion):
            return
        self._state.discard_outbound_attempt(onion)

    def _get_live_reconnect_delay(self) -> float:
        """
        Returns the configured base delay for automatic live reconnect attempts.

        Args:
            None

        Returns:
            float: Delay in seconds, where 0 disables automatic reconnects.
        """
        reconnect_delay_sec: int = self._config.get_int(SettingKey.LIVE_RECONNECT_DELAY)
        return float(max(0, reconnect_delay_sec))

    def _allows_headless_live_backlog(self) -> bool:
        """
        Determines whether unread live backlog may exist without an interactive consumer.

        Args:
            None

        Returns:
            bool: True if headless live backlog is allowed.
        """
        return self._config.get_int(SettingKey.MAX_UNSEEN_LIVE_MSGS) != 0

    def _can_auto_accept_live(self) -> bool:
        """
        Determines whether a live session may be auto-accepted immediately.

        Args:
            None

        Returns:
            bool: True if a live session may become connected immediately.
        """
        return self._has_live_consumers() or self._allows_headless_live_backlog()

    def _mark_live_reconnect_grace(self, onion: str) -> None:
        """
        Marks an incoming reconnect grace window using the profile configuration.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        grace_timeout_sec: int = self._config.get_int(
            SettingKey.LIVE_RECONNECT_GRACE_TIMEOUT
        )
        self._state.mark_live_reconnect_grace(onion, float(grace_timeout_sec))

    @staticmethod
    def _get_local_history_actor(origin: ConnectionOrigin) -> HistoryActor:
        """
        Resolves whether one local flow should be attributed to the user or the daemon.

        Args:
            origin (ConnectionOrigin): The connection lifecycle origin.

        Returns:
            HistoryActor: The normalized local actor classification.
        """
        if origin in {
            ConnectionOrigin.AUTO_RECONNECT,
            ConnectionOrigin.GRACE_RECONNECT,
            ConnectionOrigin.MUTUAL_CONNECT,
            ConnectionOrigin.AUTO_ACCEPT_CONTACT,
        }:
            return HistoryActor.SYSTEM
        return HistoryActor.LOCAL

    @staticmethod
    def _get_local_connection_actor(origin: ConnectionOrigin) -> ConnectionActor:
        """
        Resolves the IPC-facing actor for one locally initiated lifecycle step.

        Args:
            origin (ConnectionOrigin): The connection lifecycle origin.

        Returns:
            ConnectionActor: The normalized IPC actor classification.
        """
        if origin in {
            ConnectionOrigin.AUTO_RECONNECT,
            ConnectionOrigin.GRACE_RECONNECT,
            ConnectionOrigin.MUTUAL_CONNECT,
            ConnectionOrigin.AUTO_ACCEPT_CONTACT,
        }:
            return ConnectionActor.SYSTEM
        return ConnectionActor.LOCAL

    def _sleep_connect_retry_backoff(self) -> None:
        """
        Sleeps between connect retries while remaining responsive to daemon shutdown.

        Args:
            None

        Returns:
            None
        """
        remaining_sec: float = Constants.CONNECT_RETRY_BACKOFF_SEC
        while remaining_sec > 0:
            if self._stop_flag.is_set():
                break

            sleep_sec: float = min(Constants.WORKER_SLEEP_SEC, remaining_sec)
            time.sleep(sleep_sec)
            remaining_sec -= sleep_sec

    def _get_retunnel_reconnect_delay(self) -> float:
        """
        Returns the configured reconnect delay between retunnel teardown and retry.

        Args:
            None

        Returns:
            float: The configured delay in seconds.
        """
        return self._config.get_float(SettingKey.RETUNNEL_RECONNECT_DELAY)

    def _get_retunnel_recovery_retries(self) -> int:
        """
        Returns the configured delayed recovery retry budget for retunnel.

        Args:
            None

        Returns:
            int: The configured retry count.
        """
        return self._config.get_int(SettingKey.RETUNNEL_RECOVERY_RETRIES)

    def _sleep_retunnel_reconnect_delay(self) -> None:
        """
        Waits briefly before reconnecting a live retunnel to let the old session
        teardown propagate to the remote peer.

        Args:
            None

        Returns:
            None
        """
        remaining_sec: float = self._get_retunnel_reconnect_delay()
        while remaining_sec > 0:
            if self._stop_flag.is_set():
                break

            sleep_sec: float = min(Constants.WORKER_SLEEP_SEC, remaining_sec)
            time.sleep(sleep_sec)
            remaining_sec -= sleep_sec

    def _sleep_live_reconnect_delay(self, delay_sec: float) -> None:
        """
        Sleeps before an automatic live reconnect while remaining responsive to shutdown.

        Args:
            delay_sec (float): Total delay in seconds before the reconnect attempt.

        Returns:
            None
        """
        remaining_sec: float = delay_sec
        while remaining_sec > 0:
            if self._stop_flag.is_set():
                break

            sleep_sec: float = min(Constants.WORKER_SLEEP_SEC, remaining_sec)
            time.sleep(sleep_sec)
            remaining_sec -= sleep_sec
