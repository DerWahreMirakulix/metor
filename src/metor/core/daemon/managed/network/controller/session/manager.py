"""Session lifecycle facade for the modular connection controller package."""

import socket
from typing import TYPE_CHECKING, Optional

from metor.core.api import (
    ConnectionOrigin,
    ConnectionReasonCode,
    ConnectionActor,
    DisconnectedEvent,
)
from metor.core.daemon.managed.models import RejectIntent

# Local Package Imports
from metor.core.daemon.managed.network.controller.session.accept import accept
from metor.core.daemon.managed.network.controller.session.connect import connect_to
from metor.core.daemon.managed.network.controller.session.terminate import (
    disconnect,
    reject,
)
from metor.core.daemon.managed.network.controller.support import (
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

        def _enqueue_live_reconnect(self, onion: str) -> bool:
            """
            Adds one peer to the delayed reconnect queue without duplicating entries.

            Args:
                onion (str): The peer onion identity.

            Returns:
                bool: True if the peer was queued.
            """
            ...

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
        *,
        expected_pending: Optional[socket.socket] = None,
    ) -> None:
        """
        Delegates pending-connection approval to the focused accept helper.

        Args:
            target (str): The target alias or onion.
            origin (ConnectionOrigin): The machine-readable source of the accepted live flow.

        Returns:
            None
        """
        accept(self, target, origin=origin, expected_pending=expected_pending)

    def reject(
        self,
        target: str,
        initiated_by_self: bool = True,
        socket_to_close: Optional[socket.socket] = None,
        origin: ConnectionOrigin = ConnectionOrigin.INCOMING,
        reject_intent: Optional[RejectIntent] = None,
        *,
        expected_pending: Optional[socket.socket] = None,
    ) -> None:
        """
        Delegates connection rejection to the focused termination helper.

        Args:
            target (str): The target alias or onion.
            initiated_by_self (bool): Whether the local user initiated the rejection.
            socket_to_close (Optional[socket.socket]): Specific duplicate socket to terminate safely.
            origin (ConnectionOrigin): The machine-readable source of the rejected live flow.
            reject_intent (Optional[RejectIntent]): Optional semantic reject intent received from the peer.

        Returns:
            None
        """
        reject(
            self,
            target,
            initiated_by_self=initiated_by_self,
            socket_to_close=socket_to_close,
            origin=origin,
            reject_intent=reject_intent,
            expected_pending=expected_pending,
        )

    def disconnect(
        self,
        target: str,
        initiated_by_self: bool = True,
        is_fallback: bool = False,
        socket_to_close: Optional[socket.socket] = None,
        suppress_events: bool = False,
        origin: Optional[ConnectionOrigin] = None,
        system_reason: Optional[ConnectionReasonCode] = None,
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
            system_reason (Optional[ConnectionReasonCode]): Local system-policy reason.

        Returns:
            None
        """
        with self._operation_lock, self._state.snapshot_barrier():
            disconnect(
                self,
                target,
                initiated_by_self=initiated_by_self,
                is_fallback=is_fallback,
                socket_to_close=socket_to_close,
                suppress_events=suppress_events,
                origin=origin,
                system_reason=system_reason,
            )

    def disconnect_qualified(
        self, target: str, context_generation: Optional[int], attempt_id: Optional[str]
    ) -> bool:
        """Checks an exact displayed identity under the existing lifecycle mutation lock.

        Args:
            target: Canonical peer or explicit alias to resolve once.
            context_generation: Active/recovering logical context for End Live.
            attempt_id: Current outbound calling attempt for Cancel.
        Returns:
            bool: Whether the assertion still matched and termination was admitted.
        """
        with self._operation_lock, self._state.snapshot_barrier():
            resolved = self._cm.resolve_target(target)
            if resolved is None:
                return False
            alias, onion = resolved
            if attempt_id is not None:
                if (
                    context_generation is not None
                    or self._state.get_outbound_attempt_id(onion) != attempt_id
                ):
                    return False
            elif (
                context_generation is None
                or self._state.get_live_media_generation(onion) != context_generation
            ):
                return False
            outbound = (
                self._state.pop_outbound_socket(onion)
                if attempt_id is not None
                else None
            )
            try:
                disconnect(
                    self,
                    onion,
                    initiated_by_self=True,
                    origin=ConnectionOrigin.MANUAL,
                    suppress_events=attempt_id is not None,
                )
            finally:
                if outbound is not None:
                    self._state.retire_connection(outbound)
            if attempt_id is not None:
                self._broadcast(
                    DisconnectedEvent(
                        alias,
                        onion=onion,
                        actor=ConnectionActor.LOCAL,
                        origin=ConnectionOrigin.MANUAL,
                    )
                )
            return True
