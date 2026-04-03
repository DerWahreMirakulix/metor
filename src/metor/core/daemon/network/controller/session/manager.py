"""Session lifecycle facade for the modular connection controller package."""

import socket
from typing import TYPE_CHECKING, Optional

from metor.core.api import ConnectionOrigin

# Local Package Imports
from metor.core.daemon.network.controller.session.accept import accept
from metor.core.daemon.network.controller.session.connect import connect_to
from metor.core.daemon.network.controller.session.terminate import (
    disconnect,
    reject,
)
from metor.core.daemon.network.controller.support import (
    ConnectionControllerSupportMixin,
)

if TYPE_CHECKING:
    pass


class ConnectionControllerSessionMixin(ConnectionControllerSupportMixin):
    """Implements connect, accept, reject, and disconnect lifecycle flows."""

    if TYPE_CHECKING:

        def _schedule_retunnel_recovery_retry(
            self,
            alias: str,
            onion: str,
            error: str,
        ) -> bool: ...

        def _enqueue_live_reconnect(self, onion: str) -> bool: ...

    def connect_to(
        self,
        target: str,
        origin: ConnectionOrigin = ConnectionOrigin.MANUAL,
    ) -> None:
        """
        Delegates outbound connection setup to the focused connect helper.

        Args:
            target (str): The alias or onion address to connect to.
            origin (ConnectionOrigin): The machine-readable source of the connection attempt.

        Returns:
            None
        """
        connect_to(self, target, origin=origin)

    def accept(
        self,
        target: str,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        """
        Delegates pending-connection approval to the focused accept helper.

        Args:
            target (str): The target alias or onion.
            origin (ConnectionOrigin): The machine-readable source of the accepted live flow.

        Returns:
            None
        """
        accept(self, target, origin=origin)

    def reject(
        self,
        target: str,
        initiated_by_self: bool = True,
        socket_to_close: Optional[socket.socket] = None,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
    ) -> None:
        """
        Delegates connection rejection to the focused termination helper.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the rejection.
            socket_to_close (Optional[socket.socket]): Specific duplicate socket to terminate safely.
            origin (ConnectionOrigin): The machine-readable source of the rejected live flow.

        Returns:
            None
        """
        reject(
            self,
            target,
            initiated_by_self=initiated_by_self,
            socket_to_close=socket_to_close,
            origin=origin,
        )

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
        Delegates disconnect handling to the focused termination helper.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the disconnect.
            is_fallback (bool): Whether this is an unexpected network drop.
            socket_to_close (Optional[socket.socket]): Specific duplicate socket to safely terminate.
            suppress_events (bool): Whether transport lifecycle status events should be suppressed.
            origin (Optional[ConnectionOrigin]): The machine-readable source of the disconnected live flow.

        Returns:
            None
        """
        disconnect(
            self,
            target,
            initiated_by_self=initiated_by_self,
            is_fallback=is_fallback,
            socket_to_close=socket_to_close,
            suppress_events=suppress_events,
            origin=origin,
        )
