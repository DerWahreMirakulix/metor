"""Explicit cursor navigation of retained metadata without downloading or consuming Voice."""

from typing import TYPE_CHECKING

from metor.core.api import ListRetainedMessagesCommand, RetainedMessagesEvent
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from ..controller import GuiController


class InventoryPages:
    """Retains one current peer/projection page; cursors never escape their route."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an empty content-free page owner.

        Args:
            controller: Public-service GUI coordinator.
        Returns:
            None
        """
        self.controller = controller
        self.page: RetainedMessagesEvent | None = None
        self.cursor: str | None = None
        self.needed = False
        self._serial = 0
        self._operation: str | None = None

    def reset(self) -> None:
        """Invalidates a departed route's pending result and starts at the current first page.

        Args:
            None
        Returns:
            None
        """
        self._serial += 1
        self._operation = None
        self.page = None
        self.cursor = None
        self.needed = True

    def more(self) -> None:
        """Selects a public continuation only after explicit user activation.

        Args:
            None
        Returns:
            None
        """
        if (
            self.page is not None
            and self.page.next_cursor
            and not self.controller.state.busy
        ):
            self.cursor = self.page.next_cursor
            self.needed = True

    def poll(self) -> None:
        """Loads one bounded inventory page for the exact foreground peer and delivery.

        Args:
            None
        Returns:
            None
        """
        controller = self.controller
        state, client = controller.state, controller.client
        route = state.route
        if (
            not self.needed
            or state.covered
            or client is None
            or route.peer is None
            or route.view not in {'V08', 'V09'}
        ):
            return
        serial = self._serial + 1
        operation = 'inventory-page:' + str(serial)
        command = ListRetainedMessagesCommand(
            target=route.peer,
            delivery=route.delivery,
            cursor=self.cursor,
            limit=GuiLimits.PAGE_ITEMS,
            owner_token=controller.voice_owner.token,
        )
        if controller.submit(
            operation, lambda: client.request(command, RetainedMessagesEvent)
        ):
            self._serial, self._operation = serial, operation
            self.needed = False

    def install(self, update: Update) -> bool:
        """Rejects stale routes and exposes invalidated cursors as explicit refresh state.

        Args:
            update: Current-activation worker response.
        Returns:
            bool: Whether the result belongs to inventory navigation.
        """
        if not update.operation.startswith('inventory-page:'):
            return False
        if update.operation != self._operation or self.controller.state.covered:
            return True
        if isinstance(update.event, RetainedMessagesEvent):
            self.page = update.event
            self.controller.transcript.install(update.event)
        else:
            self.controller.state.status = (
                'Retained items changed. Refresh to show current items.'
            )
        return True
