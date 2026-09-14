"""Stable-ID text admission and positive-only reconciliation of unknown outcomes."""

import secrets
import json
from dataclasses import asdict, replace
from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    AckEvent,
    ReadReceiptEvent,
    DropQueuedEvent,
    GetMessageOutcomeCommand,
    MessageDirectionCode,
    MessageOutcomeEvent,
    MessageStatusCode,
    SendMessageCommand,
    TextAcceptedEvent,
    TextContent,
)
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.constants import GuiLimits

# Local Package Imports
from .transcript import TranscriptItem, advanced_status

if TYPE_CHECKING:
    from .controller import GuiController


class TextController:
    """Retains exact text intent until Core confirms its local durable outcome."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates bounded operation state scoped to one GUI runtime.

        Args:
            controller: Owning public SDK coordinator.
        Returns:
            None
        """
        self.controller = controller
        self.operations: dict[str, tuple[str, Delivery, str]] = {}
        self._checks: set[str] = set()
        self.reservations: dict[str, tuple[TranscriptItem, int]] = {}

    def send(self, peer: str, delivery: Delivery) -> None:
        """Captures one message ID and text intent, rejecting duplicate activation.

        Args:
            peer: Canonical peer identity.
            delivery: Visible composer semantics.
        Returns:
            None
        """
        controller = self.controller
        if controller.voice.press.active:
            controller.state.status = 'Finish recording before typing a message'
            return
        value = controller.state.drafts.get((peer, delivery), '')
        if not value.strip() or any(
            p == peer and d == delivery for p, d, _ in self.operations.values()
        ):
            return
        if (
            delivery is Delivery.LIVE
            and 'local_text_acceptance' not in controller.state.capabilities
        ):
            controller.state.status = 'This service cannot confirm Live text sends'
            return
        if len(self.operations) >= GuiLimits.TEXT_CONTEXTS or (
            sum(len(item[2].encode('utf-8')) for item in self.operations.values())
            + len(value.encode('utf-8'))
            > GuiLimits.TEXT_BYTES
        ):
            controller.state.status = 'Finish pending text actions before sending more'
            return
        identity = secrets.token_hex(GuiLimits.MESSAGE_ID_BYTES)
        action = 'A11:' + identity
        if delivery is Delivery.LIVE:
            item = TranscriptItem(
                peer,
                delivery,
                MessageDirectionCode.OUT,
                identity,
                text=value,
                status=MessageStatusCode.PENDING,
                finalized=True,
                order=controller.transcript.next_order(),
            )
            size = (
                len(json.dumps(asdict(item)).encode('utf-8'))
                + GuiLimits.TEXT_HANDOFF_ITEM_BYTES
            )
            free_items, free_bytes = controller.transcript.capacity()
            if free_items <= 0 or size > free_bytes:
                controller.state.status = (
                    'Conversation view is full. This draft has not been sent.'
                )
                return
            self.reservations[action] = item, size
        command = SendMessageCommand(
            peer,
            delivery,
            TextContent(value),
            identity,
            local_acceptance=delivery is Delivery.LIVE,
        )
        if controller.command(
            action,
            command,
            DropQueuedEvent if delivery is Delivery.DROP else TextAcceptedEvent,
        ):
            self.operations[action] = (peer, delivery, value)
            controller.state.status = 'Queueing…'
        else:
            self.reservations.pop(action, None)

    def install(self, update: Update) -> bool:
        """Applies only correctly qualified acceptance or definite rejection.

        Args:
            update: Current generation's typed operation result.
        Returns:
            bool: Whether this update belongs to an outstanding text intent.
        """
        if isinstance(update.event, (AckEvent, ReadReceiptEvent)):
            event_receipt = update.event
            reserved_action = 'A11:' + event_receipt.msg_id
            reservation = self.reservations.get(reserved_action)
            if reservation is not None:
                item, size = reservation
                if (
                    not isinstance(event_receipt, ReadReceiptEvent)
                    or event_receipt.onion == item.peer
                ):
                    status = (
                        MessageStatusCode.READ
                        if isinstance(event_receipt, ReadReceiptEvent)
                        else MessageStatusCode.DELIVERED
                    )
                    self.reservations[reserved_action] = (
                        replace(item, status=advanced_status(item.status, status)),
                        size,
                    )
            return False
        action = update.operation.removeprefix('text-check:')
        if action not in self.operations:
            return False
        peer, delivery, text = self.operations[action]
        event = update.event
        reconciled = update.operation.startswith('text-check:')
        accepted = (
            isinstance(event, DropQueuedEvent)
            and not reconciled
            and delivery is Delivery.DROP
            and (event.onion is None or event.onion == peer)
        )
        if isinstance(event, TextAcceptedEvent):
            accepted = event.onion == peer and event.msg_id == action.removeprefix(
                'A11:'
            )
        if isinstance(event, MessageOutcomeEvent):
            accepted = (
                event.onion == peer
                and event.msg_id == action.removeprefix('A11:')
                and event.direction is MessageDirectionCode.OUT
                and event.status is not None
                and event.status is not MessageStatusCode.DRAFT
            )
        state = self.controller.state
        prior_status = state.status
        if accepted:
            accepted_status = (
                event.status
                if isinstance(event, MessageOutcomeEvent) and event.status
                else MessageStatusCode.PENDING
            )
            if delivery is Delivery.LIVE:
                reservation = self.reservations.pop(action, None)
                item = (
                    reservation[0]
                    if reservation is not None
                    else TranscriptItem(
                        peer,
                        delivery,
                        MessageDirectionCode.OUT,
                        action.removeprefix('A11:'),
                        text=text,
                        finalized=True,
                        status=MessageStatusCode.PENDING,
                    )
                )
                item = replace(
                    item, status=advanced_status(item.status, accepted_status)
                )
                if not self.controller.transcript.admit(item):
                    if reservation is not None:
                        self.reservations[action] = reservation
                    self._checks.add(action)
                    self.controller._unknown_actions.add(action)
                    state.status = 'Message accepted. Conversation view is full.'
                    return True
                accepted_status = item.status
            if state.drafts.get((peer, delivery)) == text:
                state.drafts.pop((peer, delivery), None)
            del self.operations[action]
            self.reservations.pop(action, None)
            self._checks.discard(action)
            self.controller._unknown_actions.discard(action)
            if accepted_status is MessageStatusCode.READ:
                state.status = 'Read'
            elif accepted_status is MessageStatusCode.DELIVERED:
                state.status = 'Delivered'
            else:
                state.status = (
                    'Queued'
                    if isinstance(event, DropQueuedEvent)
                    or getattr(event, 'delivery', None) is Delivery.DROP
                    else 'Pending'
                )
            self.controller._refresh_needed = True
        elif (
            event is not None
            and not reconciled
            and not isinstance(event, TextAcceptedEvent)
        ):
            del self.operations[action]
            self.reservations.pop(action, None)
            self._checks.discard(action)
            self.controller._unknown_actions.discard(action)
        else:
            self.controller._unknown_actions.add(action)
            state.status = 'Checking result… This message cannot be sent again until its result is known.'
            if not reconciled:
                self._checks.add(action)
        if state.covered and state.route.view == 'V05':
            state.status = prior_status
        return True

    def poll(self) -> None:
        """Performs bounded read-only receipt reconciliation after an unknown result.

        Args:
            None
        Returns:
            None
        """
        controller, client = self.controller, self.controller.client
        if (
            controller.state.covered
            or client is None
            or not self._checks
            or 'message_outcome' not in controller.state.capabilities
        ):
            return
        action = next(iter(self._checks))
        peer, _delivery, _text = self.operations[action]
        if controller.submit(
            'text-check:' + action,
            lambda: client.request(
                GetMessageOutcomeCommand(peer, action.removeprefix('A11:')),
                MessageOutcomeEvent,
            ),
        ):
            self._checks.remove(action)

    def clear(self) -> None:
        """Releases volatile intents without deleting any Core-owned message.

        Args:
            None
        Returns:
            None
        """
        self.operations.clear()
        self.reservations.clear()
        self._checks.clear()
