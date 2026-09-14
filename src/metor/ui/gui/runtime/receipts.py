"""Bounded exact-identity readback after uncertain local cleanup or LIVE fallback."""

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    GetMessageOutcomeCommand,
    MessageDirectionCode,
    MessageOutcomeEvent,
    MessageStatusCode,
)
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.constants import GuiLimits

if TYPE_CHECKING:
    from .controller import GuiController


@dataclass(frozen=True)
class ReceiptTarget:
    """Exact original display identity; readback cannot include later arrivals."""

    peer: str
    delivery: Delivery
    direction: MessageDirectionCode
    msg_id: str


class ReceiptReconciliation:
    """Reads one captured bounded batch without consuming content or repeating mutations."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an empty activation-owned metadata read queue.

        Args:
            controller: Current public SDK and presentation owner.
        Returns:
            None
        """
        self.controller = controller
        self.queue: deque[ReceiptTarget] = deque()
        self.current: ReceiptTarget | None = None
        self._serial = 0
        self._operation = ''

    @property
    def busy(self) -> bool:
        """Reports whether a previous uncertain mutation still has captured receipts to inspect.

        Args:
            None
        Returns:
            bool: Whether one bounded batch is active.
        """
        return bool(self.queue) or self.current is not None

    def capture(
        self,
        delivery: Delivery,
        peer: str | None,
        msg_id: str | None = None,
        direction: MessageDirectionCode | None = None,
    ) -> tuple[ReceiptTarget, ...]:
        """Captures only current bounded local sources within the user's exact mutation scope.

        Args:
            delivery: Explicit projection selected by the user.
            peer: Exact peer or confirmed all-DROP scope.
            msg_id: Optional single-message qualifier.
            direction: Optional single-message direction qualifier.
        Returns:
            tuple[ReceiptTarget, ...]: Deduplicated finite identities, with no body/Voice copies.
        """
        controller = self.controller
        targets = {ReceiptTarget(*key) for key in controller.transcript.items}
        targets.update(
            ReceiptTarget(item.peer, item.delivery, item.direction, item.msg_id)
            for item in controller.playback.cache.targets()
            if item.owner_token is None
        )
        targets.update(
            ReceiptTarget(
                turn.binding.peer,
                turn.actual_delivery,
                MessageDirectionCode.OUT,
                turn.binding.msg_id,
            )
            for turn in controller.voice.live_turns.values()
        )
        page = controller.messages
        if page is not None and page.onion:
            targets.update(
                ReceiptTarget(page.onion, Delivery.DROP, item.direction, item.msg_id)
                for item in page.messages
                if item.msg_id
            )
        return tuple(
            item
            for item in targets
            if item.delivery is delivery
            and (peer is None or item.peer == peer)
            and (msg_id is None or item.msg_id == msg_id)
            and (direction is None or item.direction is direction)
        )

    def start(self, targets: tuple[ReceiptTarget, ...]) -> None:
        """Admits only a batch captured from bounded owners before one uncertain mutation.

        Args:
            targets: Original affected display identities.
        Returns:
            None
        """
        if not self.busy and len(targets) <= GuiLimits.RECEIPT_TARGETS:
            self.queue.extend(targets)

    def poll(self) -> None:
        """Schedules one exact non-consuming read, yielding to foreground operations.

        Args:
            None
        Returns:
            None
        """
        controller, client = self.controller, self.controller.client
        if (
            self.current is not None
            or not self.queue
            or client is None
            or controller.state.covered
            or controller.simulator
        ):
            return
        target = self.queue[0]
        capability = (
            'message_archive_state'
            if target.delivery is Delivery.DROP
            else 'message_outcome'
        )
        if capability not in controller.state.capabilities:
            self.queue.clear()
            return
        operation = 'receipt:' + str(self._serial + 1)
        if controller.submit(
            operation,
            lambda: client.request(
                GetMessageOutcomeCommand(target.peer, target.msg_id, target.direction),
                MessageOutcomeEvent,
            ),
            background=True,
        ):
            self.current = self.queue.popleft()
            self._serial += 1
            self._operation = operation

    def install(self, update: Update) -> bool:
        """Discards only positively absent archive copies or positively converted LIVE identities.

        Args:
            update: Generation-validated exact read result.
        Returns:
            bool: Whether the update belongs to receipt reconciliation.
        """
        if not update.operation.startswith('receipt:'):
            return False
        target = self.current
        if update.operation != self._operation or target is None:
            return True
        self.current = None
        if self.controller.state.covered:
            self.queue.appendleft(target)
            return True
        event = update.event
        if not isinstance(event, MessageOutcomeEvent) or (
            event.onion != target.peer
            or event.msg_id != target.msg_id
            or event.direction is not target.direction
        ):
            return True
        if target.delivery is Delivery.DROP:
            if event.delivery is Delivery.DROP and event.archive_available is False:
                self.controller.playback.forget(
                    target.peer, Delivery.DROP, target.msg_id, target.direction
                )
                self.controller.transcript.discard(
                    target.peer, Delivery.DROP, target.msg_id, target.direction
                )
                self.controller.archive.reset()
                self.controller.inventory.reset()
        elif event.delivery is Delivery.DROP and event.status in {
            MessageStatusCode.PENDING,
            MessageStatusCode.DELIVERED,
            MessageStatusCode.READ,
        }:
            self.controller.live.confirm_fallback(target.peer, target.msg_id)
        return True
