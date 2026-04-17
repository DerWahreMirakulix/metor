"""Thread-safe network state tracking facade and coordinator."""

import socket
import threading
from typing import Dict, List, Set, Tuple

from metor.core.api import ConnectionOrigin
from metor.core.daemon.managed.models import DropTunnelState
from metor.core.daemon.managed.network.state.connections import (
    StateTrackerConnectionsMixin,
)
from metor.core.daemon.managed.network.state.messages import StateTrackerMessagesMixin
from metor.core.daemon.managed.network.state.retunnel import StateTrackerRetunnelMixin
from metor.core.daemon.managed.network.state.transport import StateTrackerTransportMixin
from metor.core.daemon.managed.network.state.types import PendingConnectionReason


class StateTracker(
    StateTrackerConnectionsMixin,
    StateTrackerMessagesMixin,
    StateTrackerTransportMixin,
    StateTrackerRetunnelMixin,
):
    """Tracks active sockets, pending connections, queues, and UI focus states safely."""

    def __init__(self) -> None:
        """
        Initializes the thread-safe dictionaries and lock-backed state containers.

        Args:
            None

        Returns:
            None
        """
        self._lock: threading.Lock = threading.Lock()
        self._connections: Dict[str, socket.socket] = {}
        self._pending_connections: Dict[str, socket.socket] = {}
        self._pending_connection_reasons: Dict[str, PendingConnectionReason] = {}
        self._pending_connection_origins: Dict[str, ConnectionOrigin] = {}
        self._unauthenticated_connections: Set[socket.socket] = set()
        self._outbound_attempts: Set[str] = set()
        self._outbound_attempt_origins: Dict[str, ConnectionOrigin] = {}
        self._outbound_sockets: Dict[str, socket.socket] = {}
        self._outbound_connected_origin_overrides: Dict[str, ConnectionOrigin] = {}
        self._recent_outbound_attempts: Dict[str, float] = {}
        self._initial_buffers: Dict[str, bytes] = {}
        self._expired_pending_connections: Dict[str, float] = {}
        self._scheduled_auto_reconnects: Set[str] = set()
        self._unacked_messages: Dict[str, Dict[str, Tuple[str, str]]] = {}
        self._message_request_ids: Dict[str, str] = {}
        self._recent_live_msg_ids: Dict[str, List[str]] = {}
        self._drop_tunnels: Dict[str, DropTunnelState] = {}
        self._live_reconnect_grace: Dict[str, float] = {}
        self._retunnel_reconnects: Set[str] = set()
        self._retunnel_in_progress: Set[str] = set()
        self._retunnel_recovery_retry_counts: Dict[str, int] = {}
        self._retunnel_recovery_retry_pending: Set[str] = set()
        self._ui_focus_counts: Dict[str, int] = {}


__all__ = ['PendingConnectionReason', 'StateTracker']
