"""Bounded saved-contact selection and explicit partial-outcome batch removal."""

import threading
from typing import TYPE_CHECKING

from metor.client import MetorRequestRejectedError
from metor.core.api import (
    ContactEntry,
    ContactRemovedEvent,
    ContactDowngradedEvent,
    ContactRemovedDowngradedEvent,
    ContactsDataEvent,
    GetContactsListCommand,
    RemoveContactCommand,
    IpcEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from ..controller import GuiController


class ContactBook:
    """Owns only finite selection/page state; Core owns saved identity and demotion."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an empty selection and no background operation.

        Args:
            controller: Public SDK and current profile presentation owner.
        Returns:
            None
        """
        self.controller = controller
        self.page = 0
        self.selecting = False
        self.selected: set[str] = set()
        self.pending = False
        self.unknown = False
        self.revision = 0
        self._serial = 0
        self._check_needed = False
        self._confirmed: set[str] = set()
        self._cancel = threading.Event()

    def rows(self) -> list[ContactEntry]:
        """Filters current canonical saved entries without retaining another address book.

        Args:
            None
        Returns:
            list[ContactEntry]: Ordered public entry references for local paging.
        """
        snapshot = self.controller.state.snapshot
        if self.controller.state.covered or snapshot is None:
            return []
        query = self.controller.contacts.query.casefold()
        return sorted(
            (
                item
                for item in snapshot.contacts
                if item.saved
                and (query in item.alias.casefold() or query in item.onion)
            ),
            key=lambda item: (item.alias.casefold(), item.onion),
        )

    def toggle(self, peer: str) -> bool:
        """Changes one explicit saved identity; incoming entries never join automatically.

        Args:
            peer: Original canonical peer selected by the user.
        Returns:
            bool: Whether selection changed.
        """
        if self.pending or self.unknown or self.controller.state.covered:
            return False
        if peer in self.selected:
            self.selected.remove(peer)
        elif any(item.onion == peer for item in self.rows()):
            if len(self.selected) >= GuiLimits.CONTACT_SELECTION_ITEMS:
                self.controller.state.status = (
                    'Selection is full. Remove or deselect contacts first.'
                )
                return False
            self.selected.add(peer)
        else:
            return False
        self.selecting = True
        self.revision += 1
        return True

    def cancel_selection(self) -> None:
        """Clears only local selection; pending work stops before its next request.

        Args:
            None
        Returns:
            None
        """
        self._cancel.set()
        self.selected.clear()
        self.selecting = False
        self.revision += 1

    def stop(self) -> None:
        """Stops a pending batch before its next request while keeping uncertainty explicit.

        Args:
            None
        Returns:
            None
        """
        self._cancel.set()

    def remove(self, peers: tuple[str, ...]) -> bool:
        """Admits one explicitly confirmed captured batch using exact Core identity guards.

        Args:
            peers: Original selected identities, unaffected by later arrivals or selection changes.
        Returns:
            bool: Whether one bounded batch was admitted.
        """
        controller, client = self.controller, self.controller.client
        snapshot = controller.state.snapshot
        if (
            controller.simulator
            or controller.state.covered
            or client is None
            or snapshot is None
            or self.pending
            or self.unknown
            or not peers
            or len(set(peers)) != len(peers)
            or len(peers) > GuiLimits.CONTACT_SELECTION_ITEMS
            or 'contact_identity_guard' not in controller.state.capabilities
        ):
            return False
        aliases = {item.onion: item.alias for item in snapshot.contacts if item.saved}
        if any(peer not in aliases for peer in peers):
            controller.state.status = (
                'The selection changed. Review current saved contacts.'
            )
            controller.refresh_state()
            return False
        targets = tuple((peer, aliases[peer]) for peer in peers)
        if (
            sum(
                len(peer.encode('utf-8')) + len(alias.encode('utf-8'))
                for peer, alias in targets
            )
            > GuiLimits.CONTACT_SELECTION_BYTES
        ):
            controller.state.status = 'Selection is too large. Select fewer contacts.'
            return False
        cancel = threading.Event()
        confirmed: set[str] = set()

        def run() -> IpcEvent | None:
            """Stops at uncertainty without replaying a mutation or moving to a replacement alias.

            Args:
                None
            Returns:
                IpcEvent | None: Last actual result; confirmed identities are separately retained.
            """
            result: IpcEvent | None = None
            for peer, alias in targets:
                if cancel.is_set():
                    break
                try:
                    result = client.request(RemoveContactCommand(alias, peer), IpcEvent)
                except MetorRequestRejectedError as exc:
                    return exc.event
                if (
                    not isinstance(
                        result,
                        (
                            ContactRemovedEvent,
                            ContactDowngradedEvent,
                            ContactRemovedDowngradedEvent,
                        ),
                    )
                    or result.onion != peer
                ):
                    return result
                confirmed.add(peer)
            return result

        operation = 'contact-batch:remove:' + str(self._serial + 1)
        if not controller.submit(operation, run):
            return False
        self._serial += 1
        self._cancel, self._confirmed = cancel, confirmed
        self.pending = True
        self.revision += 1
        return True

    def check(self) -> bool:
        """Reads saved metadata after unknown/partial removal without repeating any mutation.

        Args:
            None
        Returns:
            bool: Whether one explicit read was admitted.
        """
        controller, client = self.controller, self.controller.client
        if (
            client is None
            or controller.state.covered
            or controller.simulator
            or self.pending
        ):
            return False
        if not controller.submit(
            'contact-batch:check:' + str(self._serial),
            lambda: client.request(GetContactsListCommand(), ContactsDataEvent),
        ):
            return False
        self.pending = True
        return True

    def install(self, update: Update) -> bool:
        """Reconciles current saved identities before allowing another batch.

        Args:
            update: Generation-validated public completion.
        Returns:
            bool: Whether this batch owner handled the result.
        """
        if not update.operation.startswith('contact-batch:'):
            return False
        if not update.operation.endswith(':' + str(self._serial)):
            return True
        self.pending = False
        state = self.controller.state
        if update.operation.startswith('contact-batch:remove:'):
            self.selected.difference_update(self._confirmed)
            self._confirmed.clear()
            self.unknown = True
            self._check_needed = True
            if not state.covered:
                state.status = (
                    'Refreshing saved contacts; active communication continues'
                )
        elif isinstance(update.event, ContactsDataEvent) and not state.covered:
            saved = {item.onion for item in update.event.saved}
            self.selected.intersection_update(saved)
            self.unknown = False
            state.status = (
                'Saved contacts refreshed. Review remaining selection.'
                if self.selected
                else 'Contacts removed; active communication continues'
            )
        else:
            self.unknown = True
            if not state.covered:
                state.status = 'Contact changes are unconfirmed. Check saved contacts before trying again.'
        self.controller.refresh_state()
        self.revision += 1
        return True

    def poll(self) -> None:
        """Cancels further mutation on cover and coalesces one post-batch metadata read.

        Args:
            None
        Returns:
            None
        """
        if self.controller.state.covered:
            self._cancel.set()
        if self._check_needed and self.check():
            self._check_needed = False
