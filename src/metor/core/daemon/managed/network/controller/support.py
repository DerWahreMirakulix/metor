"""Shared support logic for the modular connection controller package."""

import socket
import threading
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from metor.core import TorManager
from metor.core.api import (
    AutoReconnectScheduledEvent,
    ConnectionActor,
    ConnectionOrigin,
    EventType,
    FallbackSuccessEvent,
    IpcEvent,
    JsonValue,
    RuntimeErrorCode,
    create_event,
    get_current_request_id,
)
from metor.core.daemon.managed.crypto import Crypto
from metor.data import (
    ContactManager,
    HistoryActor,
    HistoryEvent,
    HistoryManager,
    HistoryReasonCode,
    MessageManager,
    MessageDirection,
    MessageStatus,
    MessageType,
    SettingKey,
)
from metor.utils import Constants

# Local Package Imports
from metor.core.daemon.managed.network.router import MessageRouter
from metor.core.daemon.managed.network.state import StateTracker

if TYPE_CHECKING:
    from metor.core.daemon.managed.network.receiver import StreamReceiver
    from metor.data.profile import Config


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
        params['error_code'] = RuntimeErrorCode.RETUNNEL_RECONNECT_FAILED
        if error:
            params['error_detail'] = error
        self._broadcast(create_event(EventType.RETUNNEL_FAILED, params))

        self._mark_live_reconnect_grace(onion)

        if self._get_live_reconnect_delay() > 0:
            self._state.mark_scheduled_auto_reconnect(onion)
            was_scheduled: bool = self._enqueue_live_reconnect(onion)
            if was_scheduled:
                self._hm.log_event(
                    HistoryEvent.AUTO_RECONNECT_SCHEDULED,
                    onion,
                    actor=HistoryActor.SYSTEM,
                    trigger=ConnectionOrigin.AUTO_RECONNECT,
                )
                self._broadcast(
                    AutoReconnectScheduledEvent(
                        alias=alias,
                        onion=onion,
                        origin=ConnectionOrigin.AUTO_RECONNECT,
                        actor=ConnectionActor.SYSTEM,
                    )
                )
            return

        self._convert_unacked_live_to_drops(alias, onion)

    def _broadcast_retunnel_preserved_failure(
        self,
        alias: str,
        onion: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Clears retunnel state and emits failure while keeping the old live session.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            error (Optional[str]): Optional failure detail.

        Returns:
            None
        """
        self._state.mark_live_reconnect_grace(onion, 0.0)
        self._state.clear_retunnel_flow(onion)
        params: Dict[str, JsonValue] = {'alias': alias, 'onion': onion}
        params['error_code'] = RuntimeErrorCode.RETUNNEL_RECONNECT_FAILED
        if error:
            params['error_detail'] = error
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

    def _enqueue_live_reconnect(self, onion: str) -> bool:
        """
        Adds one peer to the reconnect queue without duplicating entries.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if the peer was newly queued.
        """
        raise NotImplementedError

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

    def _convert_unacked_live_to_drops(
        self,
        alias: str,
        onion: str,
        emit_event: bool = True,
    ) -> bool:
        """
        Converts retained unacknowledged live messages into pending drops.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            emit_event (bool): Whether to emit a fallback-success event.

        Returns:
            bool: True if at least one unacknowledged live message was converted.
        """
        unacked = self._state.pop_unacked_messages(onion)
        if not unacked:
            return False

        for msg_id, pending_msg in unacked.items():
            content, timestamp = pending_msg
            self._mm.queue_message(
                contact_onion=onion,
                direction=MessageDirection.OUT,
                msg_type=MessageType.DROP_TEXT,
                payload=content,
                status=MessageStatus.PENDING,
                msg_id=msg_id,
                timestamp=timestamp,
            )
            self._hm.log_event(
                HistoryEvent.QUEUED,
                onion,
                actor=HistoryActor.SYSTEM,
                detail_code=HistoryReasonCode.UNACKED_LIVE_CONVERTED_TO_DROP,
            )

        if emit_event:
            self._broadcast(
                FallbackSuccessEvent(
                    alias=alias,
                    onion=onion,
                    count=len(unacked),
                    msg_ids=list(unacked.keys()),
                    request_id=get_current_request_id(),
                )
            )

        return True

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
        remaining_sec: float = self._config.get_float(
            SettingKey.CONNECT_RETRY_BACKOFF_DELAY
        )
        while remaining_sec > 0:
            if self._stop_flag.is_set():
                break

            sleep_sec: float = min(Constants.WORKER_SLEEP_SEC, remaining_sec)
            time.sleep(sleep_sec)
            remaining_sec -= sleep_sec

    def _get_retunnel_reconnect_delay(self) -> float:
        """
        Returns the configured delay between delayed retunnel recovery attempts.

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
        Waits briefly before a delayed retunnel recovery retry.

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
