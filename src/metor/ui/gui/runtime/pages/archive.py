"""Single-page DROP archive navigation through the public bounded request contract."""

from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    GetMessagesCommand,
    MessageDirectionCode,
    MessagesDataEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from ..controller import GuiController


class ArchivePages:
    """Keeps one archive page and exact request identity; never consumes content."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an inert page owner for this activation.

        Args:
            controller: Public-service GUI coordinator.
        Returns:
            None
        """
        self.controller = controller
        self.before: tuple[MessageDirectionCode, str] | None = None
        self.needed = False
        self._serial = 0
        self._operation: str | None = None

    def reset(self) -> None:
        """Invalidates old route results and requests the current projection's newest page.

        Args:
            None
        Returns:
            None
        """
        self._serial += 1
        self._operation = None
        self.before = None
        self.controller.messages = None
        self.needed = True

    def older(self) -> bool:
        """Requests rows before the exact oldest currently displayed archive identity.

        Args:
            None
        Returns:
            bool: Whether an older page was selected.
        """
        page = self.controller.messages
        if (
            self.controller.state.busy
            or page is None
            or not page.has_older
            or not page.messages
        ):
            return False
        first = page.messages[0]
        if not first.msg_id:
            return False
        self.before = first.direction, first.msg_id
        self.needed = True
        return True

    def load(self) -> bool:
        """Admits one route-qualified bounded request independently of text handoff.

        Args:
            None
        Returns:
            bool: Whether a request was admitted.
        """
        controller = self.controller
        client, state = controller.client, controller.state
        route = state.route
        if (
            state.covered
            or client is None
            or route.peer is None
            or route.delivery is not Delivery.DROP
        ):
            return False
        bounded = 'bounded_archive_pages' in state.capabilities
        if not bounded and self.before is not None:
            return False
        serial = self._serial + 1
        operation = 'archive:' + str(serial) + ':' + route.peer
        before = self.before
        command = GetMessagesCommand(
            route.peer,
            GuiLimits.PAGE_ITEMS,
            before[1] if before else None,
            before[0] if before else None,
            GuiLimits.ARCHIVE_PAGE_BYTES if bounded else None,
        )
        if not controller.submit(
            operation, lambda: client.request(command, MessagesDataEvent)
        ):
            return False
        self._serial, self._operation = serial, operation
        self.needed = False
        return True

    def install(self, update: Update) -> bool:
        """Installs only the exact current request and preserves a page on unknown results.

        Args:
            update: Current-activation worker result.
        Returns:
            bool: Whether this was an archive request.
        """
        if not update.operation.startswith('archive:'):
            return False
        if update.operation != self._operation:
            return True
        event, state = update.event, self.controller.state
        if state.covered or state.route.delivery is not Delivery.DROP:
            return True
        if isinstance(event, MessagesDataEvent) and event.onion == state.route.peer:
            if event.page_available:
                self.controller.messages = event
            else:
                state.status = 'This history page is unavailable. Return to latest messages to refresh.'
        else:
            state.status = 'History could not be loaded. Retry from latest messages.'
        return True

    def poll(self) -> None:
        """Retries deferred admission without automatically stepping through the archive.

        Args:
            None
        Returns:
            None
        """
        if self.needed:
            self.load()
