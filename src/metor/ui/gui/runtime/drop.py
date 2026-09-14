"""Explicit local DROP mutation outcomes and exact presentation-copy cleanup."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metor.core.api import (
    ClearMessagesCommand,
    DeleteMessageCommand,
    Delivery,
    IpcEvent,
    MessageDeletedEvent,
    MessageDeleteRejectedEvent,
    MessageDirectionCode,
    MessagesClearedEvent,
    MessagesClearedAllEvent,
    MessageOperationReason,
)
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from .receipts import ReceiptTarget

if TYPE_CHECKING:
    from .controller import GuiController


@dataclass(frozen=True)
class DropMutation:
    """Exact user-confirmed local scope, independent of later navigation or alias changes."""

    operation: str
    peer: str | None
    msg_id: str | None = None
    direction: MessageDirectionCode | None = None
    retained: tuple[ReceiptTarget, ...] = ()


class DropActions:
    """Allows one local mutation at a time and never treats unknown completion as success."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates a generation-owned mutation coordinator without persistence access.

        Args:
            controller: Current public-service GUI owner.
        Returns:
            None
        """
        self.controller = controller
        self.pending: DropMutation | None = None
        self._serial = 0
        self._uncertain_snapshot: int | None = None

    def clear(self, peer: str | None) -> bool:
        """Requests an explicitly confirmed DROP-only clear; Core preserves pending delivery.

        Args:
            peer: Exact canonical peer, or None for explicitly confirmed all-DROP cleanup.
        Returns:
            bool: Whether this exact operation was admitted.
        """
        return self._request(peer, None, None)

    def delete(self, peer: str, msg_id: str, direction: MessageDirectionCode) -> bool:
        """Requests deletion using the complete displayed local message identity.

        Args:
            peer: Canonical peer identity.
            msg_id: Exact displayed message ID.
            direction: Exact inbound/outbound identity qualifier.
        Returns:
            bool: Whether the request was admitted.
        """
        return self._request(peer, msg_id, direction)

    def _request(
        self,
        peer: str | None,
        msg_id: str | None,
        direction: MessageDirectionCode | None,
    ) -> bool:
        """Captures one confirmed scope without taking ownership of live transport or reviews.

        Args:
            peer: Explicit local cleanup peer scope.
            msg_id: Optional single-message identity.
            direction: Required direction for a single-message action.
        Returns:
            bool: Whether the same-client request was admitted.
        """
        controller = self.controller
        client = controller.client
        if (
            controller.state.covered
            or client is None
            or self.pending is not None
            or controller.receipts.busy
        ):
            return False
        self._serial += 1
        mutation = DropMutation(
            'drop:' + str(self._serial),
            peer,
            msg_id,
            direction,
            controller.receipts.capture(Delivery.DROP, peer, msg_id, direction),
        )
        command = (
            DeleteMessageCommand(peer, msg_id, direction)
            if peer is not None and msg_id is not None
            else ClearMessagesCommand(peer)
        )
        if not controller.submit(
            mutation.operation, lambda: client.request(command, IpcEvent)
        ):
            return False
        self.pending = mutation
        return True

    def install(self, update: Update) -> bool:
        """Applies only a positive exact outcome and retains copies after rejection or uncertainty.

        Args:
            update: Current-generation correlated public result.
        Returns:
            bool: Whether this coordinator owns the completion.
        """
        mutation = self.pending
        if mutation is None or update.operation != mutation.operation:
            return False
        controller, event = self.controller, update.event
        if event is None:
            controller.receipts.start(mutation.retained)
            controller.preferences.refresh_needed = True
            self._uncertain_snapshot = id(controller.state.snapshot)
            controller.refresh_state()
            if not controller.state.covered:
                controller.state.status = 'Could not confirm deletion. Refreshing current state; no automatic retry.'
            return True
        success = (
            isinstance(event, MessageDeletedEvent)
            and mutation.msg_id is not None
            and event.msg_id == mutation.msg_id
            and event.onion == mutation.peer
            or isinstance(event, MessagesClearedEvent)
            and mutation.msg_id is None
            and mutation.peer is not None
            and event.onion == mutation.peer
            or isinstance(event, MessagesClearedAllEvent)
            and mutation.peer is None
        )
        self.pending = None
        if success:
            self._discard(mutation)
            controller.preferences.refresh_needed = True
            controller.refresh_state()
            if not controller.state.covered:
                controller.state.status = (
                    'Drop deleted locally'
                    if mutation.msg_id
                    else 'Local Drops cleared. Pending delivery is preserved.'
                )
        elif not controller.state.covered:
            controller.state.status = (
                'Pending delivery is preserved'
                if isinstance(event, MessageDeleteRejectedEvent)
                and event.reason is MessageOperationReason.PENDING_DELIVERY
                else 'Item no longer available'
                if isinstance(event, MessageDeleteRejectedEvent)
                and event.reason is MessageOperationReason.NOT_FOUND
                else 'Could not delete local Drops'
            )
        return True

    def _discard(self, mutation: DropMutation) -> None:
        """Releases only the acknowledged DROP presentation scope, retaining LIVE and reviews.

        Args:
            mutation: Positively completed exact local scope.
        Returns:
            None
        """
        controller = self.controller
        playback = controller.playback
        playback.forget(
            mutation.peer, Delivery.DROP, mutation.msg_id, mutation.direction
        )
        controller.transcript.discard(
            mutation.peer, Delivery.DROP, mutation.msg_id, mutation.direction
        )
        route = controller.state.route
        if route.delivery is Delivery.DROP and (
            mutation.peer is None or route.peer == mutation.peer
        ):
            controller.archive.reset()
            controller.inventory.reset()

    def poll(self) -> None:
        """Allows a fresh explicitly confirmed scope only after an uncertain result is resnapshotted.

        Args:
            None
        Returns:
            None
        """
        snapshot = self.controller.state.snapshot
        if (
            self._uncertain_snapshot is not None
            and snapshot is not None
            and id(snapshot) != self._uncertain_snapshot
        ):
            self.pending = None
            self._uncertain_snapshot = None
