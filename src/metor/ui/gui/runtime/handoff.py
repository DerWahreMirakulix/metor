"""Reserved, bounded foreground text handoff that survives route and cover changes."""

from typing import TYPE_CHECKING

from metor.core.api import (
    MarkReadCommand,
    MessageDirectionCode,
    MessageStatusCode,
    TextContent,
    UnreadMessagesEvent,
)
from metor.shared import Constants
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from .transcript import TranscriptItem

if TYPE_CHECKING:
    from .controller import GuiController


class TextHandoff:
    """Reserves payload capacity before a public operation can consume unread text."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an idle handoff owner scoped to the current GUI activation.

        Args:
            controller: Public-service GUI coordinator.
        Returns:
            None
        """
        self.controller = controller
        self.needed = False
        self._pending: tuple[str, Route] | None = None
        self._serial = 0

    def poll(self) -> None:
        """Admits only the foreground projection after reserving bounded result storage.

        Args:
            None
        Returns:
            None
        """
        controller, state = self.controller, self.controller.state
        client, route = controller.client, state.route
        if (
            not self.needed
            or self._pending is not None
            or state.covered
            or state.busy
            or client is None
            or route.peer is None
            or route.view not in {'V08', 'V09'}
            or 'bounded_text_handoff' not in state.capabilities
        ):
            return
        transcript = controller.transcript
        free_items, free_bytes = transcript.capacity()
        count = min(GuiLimits.PAGE_ITEMS, free_items)
        metadata = count * GuiLimits.TEXT_HANDOFF_ITEM_BYTES
        payload = min(Constants.TEXT_HANDOFF_MAX_BYTES, free_bytes - metadata)
        if count <= 0 or payload <= 0:
            state.status = (
                'Conversation view is full. Unread text remains in the service.'
            )
            self.needed = False
            return
        self._serial += 1
        operation = 'text-handoff:' + str(self._serial)
        transcript.reserved_items = count
        transcript.reserved_bytes = payload + metadata
        if controller.submit(
            operation,
            lambda: client.request(
                MarkReadCommand(route.peer or '', route.delivery, count, payload),
                UnreadMessagesEvent,
            ),
        ):
            self._pending = operation, route
            self.needed = False
        else:
            transcript.reserved_items = transcript.reserved_bytes = 0

    def install(self, update: Update) -> bool:
        """Protects every returned item from blanket revision or foreground-route discard.

        Args:
            update: Generation-validated completion from the exact admitted handoff.
        Returns:
            bool: Whether this result belongs to protected foreground text handoff.
        """
        if self._pending is None or update.operation != self._pending[0]:
            return False
        _, route = self._pending
        self._pending = None
        controller = self.controller
        transcript = controller.transcript
        transcript.reserved_items = transcript.reserved_bytes = 0
        event = update.event
        if not isinstance(event, UnreadMessagesEvent) or event.onion != route.peer:
            if not controller.state.covered:
                controller.state.status = 'Text handoff could not be confirmed'
            return True
        for entry in event.messages:
            if (
                entry.delivery is not route.delivery
                or not entry.msg_id
                or not isinstance(entry.content, TextContent)
            ):
                controller.state.status = 'Text handoff returned an invalid source'
                continue
            admitted = transcript.admit(
                TranscriptItem(
                    route.peer or '',
                    route.delivery,
                    MessageDirectionCode.IN,
                    entry.msg_id,
                    entry.content.text,
                    entry.timestamp,
                    MessageStatusCode.READ,
                    finalized=True,
                )
            )
            if not admitted:
                raise RuntimeError('Reserved foreground handoff exceeded its budget')
        self.needed = (
            bool(event.messages)
            and controller.state.route == route
            and not controller.state.covered
        )
        return True

    def clear(self) -> None:
        """Drops the departed activation's reservation and pending route identity.

        Args:
            None
        Returns:
            None
        """
        self.needed = False
        self._pending = None
        self.controller.transcript.reserved_items = 0
        self.controller.transcript.reserved_bytes = 0
