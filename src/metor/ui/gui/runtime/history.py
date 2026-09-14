"""Bounded public history paging and single-flight, explicitly confirmed ledger clear."""

from typing import TYPE_CHECKING

from metor.core.api import (
    ClearHistoryCommand,
    EventType,
    GetHistoryCommand,
    GetRawHistoryCommand,
    HistoryDataEvent,
    HistoryRawDataEvent,
    IpcEvent,
)
from metor.shared import Constants
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from .controller import GuiController


class ActivityHistory:
    """Retains one metadata page and a finite stack of opaque Core anchors."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an inert activation-local history reader.

        Args:
            controller: Public SDK operation owner.
        Returns:
            None
        """
        self.controller = controller
        self.page: HistoryDataEvent | HistoryRawDataEvent | None = None
        self.anchors: list[int | None] = [None]
        self._requested_anchors: list[int | None] = [None]
        self.raw = False
        self.needed = True
        self.revision = 0
        self.error = ''
        self.pending = False
        self._serial = 0
        self._read = ''
        self._clear = ''
        self._unknown = False
        self._read_error = False

    def open(self, raw: bool) -> None:
        """Selects summary or technical metadata with fresh authorization readback.

        Args:
            raw: Explicit technical-history selection.
        Returns:
            None
        """
        if self.raw != raw:
            self.cover()
        self.raw = raw
        self.needed = True

    def cover(self) -> None:
        """Forgets identities and navigation anchors when private content is covered.

        Args:
            None
        Returns:
            None
        """
        self.page = None
        self.anchors = [None]
        self._requested_anchors = [None]
        self.needed = True
        self.revision += 1

    def move(self, direction: str) -> None:
        """Moves one finite page or refreshes the newest page without accumulating rows.

        Args:
            direction: Explicit older, newer or first navigation.
        Returns:
            None
        """
        if (
            self.controller.state.covered
            or self.controller.state.busy
            or (self.pending and not (self._unknown and direction == 'first'))
        ):
            return
        self._requested_anchors = list(self.anchors)
        if direction == 'older':
            if (
                not self.page
                or not self.page.has_older
                or self.page.next_before_id is None
                or len(self.anchors) >= GuiLimits.HISTORY_ANCHORS
            ):
                return
            self._requested_anchors.append(self.page.next_before_id)
        elif direction == 'newer':
            if len(self.anchors) <= 1:
                return
            self._requested_anchors.pop()
        else:
            self._requested_anchors = [None]
        self.needed = True

    def clear(self) -> bool:
        """Submits one user-confirmed all-profile history-ledger clear.

        Args:
            None
        Returns:
            bool: Whether the exact operation was admitted.
        """
        controller, client = self.controller, self.controller.client
        if (
            client is None
            or controller.state.covered
            or self.pending
            or controller.state.route.view != 'V18'
        ):
            return False
        self._serial += 1
        operation = 'history:clear:' + str(self._serial)
        if not controller.submit(
            operation, lambda: client.request(ClearHistoryCommand(), IpcEvent)
        ):
            return False
        self._clear, self.pending, self.error = operation, True, ''
        self._read_error = False
        self.revision += 1
        return True

    def install(self, update: Update) -> bool:
        """Installs exact read or mutation results; uncertainty never repeats a clear.

        Args:
            update: Activation-generation-validated SDK response.
        Returns:
            bool: Whether history owns this result.
        """
        if self._clear and update.operation == self._clear:
            self._clear = ''
            event = update.event
            self._unknown = event is None
            self.pending = self._unknown
            if event is not None and event.event_type == EventType.HISTORY_CLEARED_ALL:
                self.page = None
                self.anchors = [None]
                self.error = ''
            else:
                self.error = (
                    'Clear is unconfirmed. Current metadata will be rechecked; the clear will not be repeated.'
                    if self._unknown
                    else 'History could not be cleared. Current rows are retained.'
                )
            self.needed = True
            self._requested_anchors = [None]
            self.revision += 1
            return True
        if not self._read or update.operation != self._read:
            return False
        self._read = ''
        if self.controller.state.covered:
            self.cover()
            return True
        event = update.event
        expected = HistoryRawDataEvent if self.raw else HistoryDataEvent
        if (
            isinstance(event, (HistoryDataEvent, HistoryRawDataEvent))
            and isinstance(event, expected)
            and event.metadata_only
            and event.page_available
            and len(event.entries) <= GuiLimits.PAGE_ITEMS
            and len(event.to_json().encode('utf-8')) <= Constants.HISTORY_PAGE_MAX_BYTES
        ):
            self.page = event
            if self.anchors != self._requested_anchors:
                self.controller.state.secondary_scroll[
                    Route('V18', history_raw=self.raw)
                ] = 1.0
            self.anchors = list(self._requested_anchors)
            if self._read_error:
                self.error = (
                    'Clear remains unconfirmed. Current metadata has been rechecked.'
                    if self._unknown
                    else ''
                )
                self._read_error = False
            if self._unknown:
                self.pending, self._unknown = False, False
        else:
            self._read_error = True
            self.error = (
                'This history page is unavailable. Refresh from the newest page.'
            )
        self.revision += 1
        return True

    def poll(self) -> None:
        """Requests one finite page only on an authorized history surface.

        Args:
            None
        Returns:
            None
        """
        controller, client = self.controller, self.controller.client
        if (
            not self.needed
            or self._read
            or client is None
            or controller.state.covered
            or controller.state.route.view != 'V18'
            or 'history_metadata_pages' not in controller.state.capabilities
        ):
            return
        self._serial += 1
        operation = 'history:read:' + str(self._serial)
        command = (GetRawHistoryCommand if self.raw else GetHistoryCommand)(
            page_size=GuiLimits.PAGE_ITEMS, before_id=self._requested_anchors[-1]
        )
        if controller.submit(operation, lambda: client.request(command, IpcEvent)):
            self._read, self.needed = operation, False
