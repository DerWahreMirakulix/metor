"""Protocol definitions for the modular connection-session helpers."""

import socket
import threading
from typing import TYPE_CHECKING, Callable, Optional, Protocol

from metor.core import TorManager
from metor.core.api import ConnectionActor, ConnectionOrigin, IpcEvent
from metor.core.daemon.managed.crypto import Crypto
from metor.core.daemon.managed.network.state import StateTracker
from metor.data import ContactManager, HistoryActor, HistoryManager, MessageManager

if TYPE_CHECKING:
    from metor.core.daemon.managed.network.receiver import StreamReceiver
    from metor.data.profile import Config


class _SessionControllerBaseProtocol(Protocol):
    """Shared surface used by all connection-session helper modules."""

    _tm: TorManager
    _cm: ContactManager
    _hm: HistoryManager
    _mm: MessageManager
    _crypto: Crypto
    _state: StateTracker
    _broadcast: Callable[[IpcEvent], None]
    _stop_flag: threading.Event
    _config: 'Config'
    _receiver: Optional['StreamReceiver']

    def _get_local_connection_actor(
        self,
        origin: ConnectionOrigin,
    ) -> ConnectionActor:
        """
        Resolves the connection actor to expose for one local transport action.

        Args:
            origin (ConnectionOrigin): The semantic origin of the transport action.

        Returns:
            ConnectionActor: The actor value for IPC transport events.
        """
        ...

    def _get_local_history_actor(
        self,
        origin: ConnectionOrigin,
    ) -> HistoryActor:
        """
        Resolves the history actor to record for one local transport action.

        Args:
            origin (ConnectionOrigin): The semantic origin of the transport action.

        Returns:
            HistoryActor: The actor value for raw history logging.
        """
        ...


class ConnectControllerProtocol(_SessionControllerBaseProtocol, Protocol):
    """Surface required by the outbound connect helper."""

    def _broadcast_retunnel_preserved_failure(
        self,
        alias: str,
        onion: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Broadcasts one retunnel failure while preserving the current live session.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            error (Optional[str]): Optional failure detail.

        Returns:
            None
        """
        ...

    def accept(
        self,
        target: str,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        """
        Accepts one pending live connection.

        Args:
            target (str): The alias or onion to accept.
            origin (ConnectionOrigin): The semantic origin of the accepted flow.

        Returns:
            None
        """
        ...

    def _sleep_connect_retry_backoff(self) -> None:
        """
        Waits for the configured retry backoff between live connect attempts.

        Args:
            None

        Returns:
            None
        """
        ...


class AcceptControllerProtocol(_SessionControllerBaseProtocol, Protocol):
    """Surface required by the pending-accept helper."""

    def _broadcast_retunnel_preserved_failure(
        self,
        alias: str,
        onion: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Broadcasts one retunnel failure while preserving the current live session.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            error (Optional[str]): Optional failure detail.

        Returns:
            None
        """
        ...

    def _broadcast_retunnel_failure(
        self,
        alias: str,
        onion: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Broadcasts one retunnel failure and clears the related flow state.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            error (Optional[str]): Optional failure detail.

        Returns:
            None
        """
        ...


class TerminateControllerProtocol(_SessionControllerBaseProtocol, Protocol):
    """Surface required by the reject and disconnect helpers."""

    def _broadcast_retunnel_preserved_failure(
        self,
        alias: str,
        onion: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Broadcasts one retunnel failure while preserving the current live session.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            error (Optional[str]): Optional failure detail.

        Returns:
            None
        """
        ...

    def _discard_outbound_attempt_if_idle(self, onion: str) -> None:
        """
        Clears outbound-attempt bookkeeping only when no newer flow is active.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        ...

    def _is_inflight_outbound_socket(self, onion: str, sock: socket.socket) -> bool:
        """
        Checks whether a callback socket belongs to the current outbound attempt.

        Args:
            onion (str): The peer onion identity.
            sock (socket.socket): The callback socket to inspect.

        Returns:
            bool: True if the socket is the current outbound attempt.
        """
        ...

    def _mark_live_reconnect_grace(self, onion: str) -> None:
        """
        Marks a peer for a short reconnect-grace auto-accept window.

        Args:
            onion (str): The peer onion identity.

        Returns:
            None
        """
        ...

    def _schedule_retunnel_recovery_retry(
        self,
        alias: str,
        onion: str,
        error: str,
    ) -> bool:
        """
        Schedules a delayed retunnel recovery retry when the flow is still recoverable.

        Args:
            alias (str): The peer alias.
            onion (str): The peer onion identity.
            error (str): The error that should be reported if recovery fails.

        Returns:
            bool: True if the flow remains recoverable.
        """
        ...

    def _get_live_reconnect_delay(self) -> float:
        """
        Returns the configured delay for automatic live reconnect attempts.

        Args:
            None

        Returns:
            float: The reconnect delay in seconds.
        """
        ...

    def _enqueue_live_reconnect(self, onion: str) -> bool:
        """
        Adds one peer to the delayed reconnect queue without duplicating entries.

        Args:
            onion (str): The peer onion identity.

        Returns:
            bool: True if the peer was queued.
        """
        ...
