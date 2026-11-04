"""Single-page DROP archive navigation through the public bounded request contract."""

from dataclasses import replace
from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    GetMessagesCommand,
    MessageDirectionCode,
    MessageStatusCode,
    MessagesDataEvent,
    TextContent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state.mailbox import Update

from ..receipts import ReceiptTarget
from ..transcript import advanced_status

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
        self._visible_request = False
        self._checks: set[ReceiptTarget] = set()
        self.error = ''

    @property
    def loading(self) -> bool:
        """Reports a deferred or admitted read for the visible DROP conversation."""
        state = self.controller.state
        return (
            not state.covered
            and state.route.peer is not None
            and state.route.delivery is Delivery.DROP
            and (self.needed or self._operation is not None)
        )

    def reset(self, *, preserve_latest: bool = False) -> None:
        """Requests the newest page, optionally retaining the same conversation's known rows.

        Args:
            preserve_latest: Whether a same-peer projection switch may retain its
                already-authorized newest page while obtaining fresh Core facts.
        Returns:
            None
        """
        state, page = self.controller.state, self.controller.messages
        retain = (
            preserve_latest
            and not state.covered
            and state.route.peer is not None
            and self.before is None
            and page is not None
            and page.page_available
            and page.onion == state.route.peer
        )
        self._serial += 1
        self._operation = None
        self.before = None
        if not retain:
            self.controller.messages = None
        self.needed = True
        self._visible_request = True
        self.error = ''

    def retry(self) -> bool:
        """Retries the selected read without changing delivery or replaying a mutation."""
        state = self.controller.state
        if (
            state.covered
            or state.route.peer is None
            or state.route.delivery is not Delivery.DROP
            or self._operation is not None
        ):
            return False
        self.error = ''
        self.needed = True
        self._visible_request = True
        self.load()
        return True

    def changed(self, peer: str | None) -> None:
        """Rechecks known archive copies after Core reports changed DROP contents.

        The event may describe another client's deletion or a DROP promotion.
        Hidden eligible rows therefore require a fresh archive read before reuse.
        Positive pending work, unsent reviews, LIVE content, and canonical Core
        data remain owned by their existing services.

        Args:
            peer: Changed canonical peer, or all peers for an unqualified event.
        """
        controller, state = self.controller, self.controller.state
        visible_peer = (
            state.route.peer
            if not state.covered
            and state.route.view == 'V08'
            and state.route.delivery is Delivery.DROP
            else None
        )
        statuses: dict[ReceiptTarget, MessageStatusCode] = {}
        page = controller.messages
        if page is not None and page.onion:
            statuses.update(
                (
                    ReceiptTarget(
                        page.onion, Delivery.DROP, item.direction, item.msg_id
                    ),
                    item.status,
                )
                for item in page.messages
                if item.msg_id
            )
        inventory = controller.inventory.page
        if inventory is not None:
            for item in inventory.messages:
                target = ReceiptTarget(
                    item.onion, item.delivery, item.direction, item.msg_id
                )
                statuses[target] = advanced_status(
                    statuses.get(target, item.status), item.status
                )
        for key, cached in controller.transcript.items.items():
            target = ReceiptTarget(*key)
            if target in statuses:
                statuses[target] = advanced_status(statuses[target], cached.status)
        for turn in controller.voice.live_turns.values():
            target = ReceiptTarget(
                turn.binding.peer,
                turn.actual_delivery,
                MessageDirectionCode.OUT,
                turn.binding.msg_id,
            )
            if target in statuses:
                statuses[target] = advanced_status(statuses[target], turn.status)
        affected = {
            target
            for target, status in statuses.items()
            if target.delivery is Delivery.DROP
            and (peer is None or target.peer == peer)
            and status not in {MessageStatusCode.PENDING, MessageStatusCode.DRAFT}
        }
        if affected and self._operation is not None:
            self._serial += 1
            self._operation = None
            self.needed = True
        for target in affected:
            if target.peer != visible_peer:
                controller.transcript.discard(
                    target.peer, Delivery.DROP, target.msg_id, target.direction
                )
        retained = set(controller.receipts.capture(Delivery.DROP, None))
        self._checks = (self._checks | affected) & retained
        if inventory is not None:
            controller.inventory.page = replace(
                inventory,
                messages=[
                    item
                    for item in inventory.messages
                    if item.onion == visible_peer
                    or ReceiptTarget(
                        item.onion, item.delivery, item.direction, item.msg_id
                    )
                    not in affected
                ],
            )
        if (
            page is not None
            and page.onion != visible_peer
            and (peer is None or page.onion == peer)
        ):
            pending = [
                item
                for item in page.messages
                if ReceiptTarget(
                    page.onion or '', Delivery.DROP, item.direction, item.msg_id or ''
                )
                not in affected
            ]
            self.reset()
            if pending:
                controller.messages = replace(page, messages=pending, has_older=False)

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
        self._serial += 1
        self._operation = None
        self.before = first.direction, first.msg_id
        self.needed = True
        self._visible_request = True
        self.error = ''
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
            or self._operation is not None
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
            operation,
            lambda: client.request(command, MessagesDataEvent),
            background=True,
        ):
            return False
        self._serial, self._operation = serial, operation
        self.needed = False
        self._visible_request = False
        self.error = ''
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
        self._operation = None
        if not self.controller.read_is_current(update):
            self.needed = True
            if self.controller.messages is None:
                self._visible_request = True
            return True
        event, state = update.event, self.controller.state
        if state.covered or state.route.delivery is not Delivery.DROP:
            return True
        if isinstance(event, MessagesDataEvent) and event.onion == state.route.peer:
            if event.page_available:
                self.controller.messages = self._release_confirmed_text(event)
                self.error = ''
            else:
                self.error = (
                    'This history page is unavailable. Return to latest messages.'
                )
        else:
            self.error = 'Messages could not be loaded. Try again.'
        return True

    def _release_confirmed_text(self, event: MessagesDataEvent) -> MessagesDataEvent:
        """Hands exact published outgoing text presentation back to its Core archive.

        Args:
            event: Current available page for the already verified exact peer.
        Returns:
            MessagesDataEvent: Archive rows retaining any newer positive receipt evidence.
        """
        transcript = self.controller.transcript
        previous = self.controller.messages
        known_status = (
            {
                (entry.direction, entry.msg_id): entry.status
                for entry in previous.messages
                if entry.msg_id and entry.delivery is Delivery.DROP
            }
            if previous is not None and previous.onion == event.onion
            else {}
        )
        entries = []
        for entry in event.messages:
            prior_status = (
                known_status.get((entry.direction, entry.msg_id))
                if entry.msg_id
                else None
            )
            if entry.delivery is Delivery.DROP and prior_status is not None:
                entry = replace(
                    entry, status=advanced_status(prior_status, entry.status)
                )
            if (
                event.onion is not None
                and entry.msg_id
                and entry.delivery is Delivery.DROP
                and entry.direction is MessageDirectionCode.OUT
                and entry.status is not MessageStatusCode.DRAFT
                and isinstance(entry.content, TextContent)
            ):
                key = (
                    event.onion,
                    Delivery.DROP,
                    MessageDirectionCode.OUT,
                    entry.msg_id,
                )
                cached = transcript.items.get(key)
                if (
                    cached is not None
                    and cached.text is not None
                    and cached.status is not MessageStatusCode.DRAFT
                ):
                    entry = replace(
                        entry, status=advanced_status(cached.status, entry.status)
                    )
                    transcript.discard(
                        event.onion,
                        Delivery.DROP,
                        entry.msg_id,
                        MessageDirectionCode.OUT,
                    )
            entries.append(entry)
        return replace(event, messages=entries)

    def poll(self) -> None:
        """Retries deferred admission without automatically stepping through the archive.

        Args:
            None
        Returns:
            None
        """
        if self.needed:
            self.load()
        if self._checks and not self.controller.receipts.busy:
            self.controller.receipts.start(tuple(self._checks))
            self._checks.clear()

    def poll_visible(self) -> None:
        """Gives one explicit navigation read the next free bounded read turn.

        Exact action reconciliation runs first. Once admitted, subsequent
        refreshes use ordinary fair scheduling, so an open chat cannot starve
        snapshot, preferences, or other background readers.
        """
        if self._visible_request:
            self.poll()
