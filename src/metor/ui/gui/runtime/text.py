"""Stable-ID text admission and positive-only reconciliation of unknown outcomes."""

import secrets
import json
import time
from dataclasses import asdict, replace
from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    EventType,
    AckEvent,
    ReadReceiptEvent,
    DropQueuedEvent,
    GetMessageOutcomeCommand,
    MessageDirectionCode,
    MessageOutcomeEvent,
    MessageStatusCode,
    SendMessageCommand,
    TextAcceptedEvent,
    TextRejectedEvent,
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
        self._check_at: dict[str, float] = {}
        self._feedback_revisions: dict[str, int] = {}
        self._errors: dict[tuple[str, Delivery], str] = {}
        self.reservations: dict[str, tuple[TranscriptItem, int]] = {}

    def error(self, peer: str, delivery: Delivery) -> str:
        """Returns persistent actionable feedback for the exact visible composer."""
        return (
            ''
            if self.controller.state.covered
            else self._errors.get((peer, delivery), '')
        )

    def clear_error(self, peer: str, delivery: Delivery) -> None:
        """Clears a previous draft error after editing or confirmed acceptance."""
        self._errors.pop((peer, delivery), None)

    def report_error(self, peer: str, delivery: Delivery, message: str) -> int | None:
        """Keeps failures beside the draft and notifies only a departed conversation.

        Returns:
            int | None: The owned transient-feedback revision, when one was published.
        """
        key = peer, delivery
        if self._errors.get(key) == message:
            return None
        if key not in self._errors and len(self._errors) >= GuiLimits.TEXT_CONTEXTS:
            self._errors.pop(next(iter(self._errors)))
        self._errors[key] = message
        state = self.controller.state
        if not state.covered and not (
            state.route.view in {'V08', 'V09'}
            and state.route.peer == peer
            and state.route.delivery is delivery
        ):
            state.status = (
                self.controller.contacts.alias(peer)
                + ' · '
                + delivery.value.upper()
                + ': '
                + message
            )
            return state.feedback.revision
        return None

    def pending(self, peer: str, delivery: Delivery) -> bool:
        """Reports only this composer's admitted or unresolved send intent.

        Args:
            peer: Exact canonical composer peer.
            delivery: Composer's DROP or LIVE projection.
        Returns:
            bool: Whether sending this draft again would duplicate an intent.
        """
        return any(p == peer and d is delivery for p, d, _ in self.operations.values())

    def pending_status(self, peer: str, delivery: Delivery) -> str:
        """Provides persistent draft-local feedback for its exact pending operation.

        Args:
            peer: Exact canonical composer peer.
            delivery: Composer's DROP or LIVE projection.
        Returns:
            str: Sending or reconciliation label, or empty when no send is pending.
        """
        for action, (target, mode, _text) in self.operations.items():
            if target == peer and mode is delivery:
                return (
                    'Checking send result…'
                    if action in self.controller._unknown_actions
                    else 'Sending…'
                )
        return ''

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
            self.report_error(
                peer, delivery, 'Finish recording before typing a message'
            )
            return
        value = controller.state.drafts.get((peer, delivery), '')
        if not value.strip():
            return
        if self.pending(peer, delivery):
            return
        self.clear_error(peer, delivery)
        if (
            delivery is Delivery.LIVE
            and 'local_text_acceptance' not in controller.state.capabilities
        ):
            self.report_error(
                peer, delivery, 'This service cannot confirm Live text sends'
            )
            return
        if len(self.operations) >= GuiLimits.TEXT_CONTEXTS or (
            sum(len(item[2].encode('utf-8')) for item in self.operations.values())
            + len(value.encode('utf-8'))
            > GuiLimits.TEXT_BYTES
        ):
            self.report_error(
                peer, delivery, 'Finish pending text actions before sending more'
            )
            return
        identity = secrets.token_hex(GuiLimits.MESSAGE_ID_BYTES)
        action = 'A11:' + identity
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
            self.report_error(
                peer,
                delivery,
                'Conversation view is full. This draft has not been sent.',
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
        else:
            self.reservations.pop(action, None)
            if not controller.state.covered:
                self.report_error(
                    peer,
                    delivery,
                    'This message has not been sent. Try again when the current action finishes.',
                )

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
        rejected = (
            not reconciled
            and event is not None
            and (
                (
                    isinstance(event, TextRejectedEvent)
                    and event.onion == peer
                    and event.msg_id == action.removeprefix('A11:')
                )
                or event.event_type
                in {
                    EventType.INVALID_TARGET,
                    EventType.PEER_NOT_FOUND,
                    EventType.DROPS_DISABLED,
                    EventType.CANNOT_DROP_SELF,
                    EventType.CLIENT_ACCESS_RESTRICTED,
                }
            )
        )
        if accepted:
            accepted_status = (
                event.status
                if isinstance(event, MessageOutcomeEvent) and event.status
                else MessageStatusCode.PENDING
            )
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
            item = replace(item, status=advanced_status(item.status, accepted_status))
            if not self.controller.transcript.admit(item):
                if reservation is not None:
                    self.reservations[action] = reservation
                self._checks.add(action)
                self.controller._unknown_actions.add(action)
                revision = self.report_error(
                    peer, delivery, 'Message accepted. Conversation view is full.'
                )
                if revision is not None:
                    self._feedback_revisions[action] = revision
                return True
            if state.drafts.get((peer, delivery)) == text:
                state.drafts.pop((peer, delivery), None)
            del self.operations[action]
            self.reservations.pop(action, None)
            self._checks.discard(action)
            self._check_at.pop(action, None)
            self.controller._unknown_actions.discard(action)
            self.clear_error(peer, delivery)
            feedback_revision = self._feedback_revisions.pop(action, None)
            if feedback_revision == state.feedback.revision:
                state.status = ''
            if (
                delivery is Delivery.DROP
                and not state.covered
                and state.route.view == 'V08'
                and state.route.peer == peer
                and state.route.delivery is Delivery.DROP
                and self.controller.archive.before is not None
            ):
                self.controller.archive.reset()
            self.controller.refresh_state()
        elif rejected:
            del self.operations[action]
            self.reservations.pop(action, None)
            self._checks.discard(action)
            self._check_at.pop(action, None)
            self._feedback_revisions.pop(action, None)
            self.controller._unknown_actions.discard(action)
            self.report_error(
                peer,
                delivery,
                'Drops are disabled. Your draft is still here.'
                if event is not None and event.event_type is EventType.DROPS_DISABLED
                else 'Message was rejected. Your draft is still here.',
            )
        else:
            self.controller._unknown_actions.add(action)
            revision = self.report_error(
                peer,
                delivery,
                'Checking send result… Your draft is kept until the result is known.',
            )
            if revision is not None:
                self._feedback_revisions[action] = revision
            self._checks.add(action)
            self._check_at[action] = (
                time.monotonic() + GuiLimits.TEXT_OUTCOME_SECONDS if reconciled else 0.0
            )
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
        now = time.monotonic()
        action = next(
            (key for key in self._checks if self._check_at.get(key, 0.0) <= now),
            None,
        )
        if action is None:
            return
        peer, _delivery, _text = self.operations[action]
        if controller.submit(
            'text-check:' + action,
            lambda: client.request(
                GetMessageOutcomeCommand(peer, action.removeprefix('A11:')),
                MessageOutcomeEvent,
            ),
            background=True,
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
        self._check_at.clear()
        self._feedback_revisions.clear()
        self._errors.clear()
