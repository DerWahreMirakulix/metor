"""Intent-preserving contact forms and immutable-identity management through public IPC."""

from dataclasses import dataclass, replace
import json
from typing import TYPE_CHECKING, Literal

from metor.client import validate_contact_qr
from metor.core.api import (
    AddContactCommand,
    AliasInUseEvent,
    AliasRenamedEvent,
    ClearContactsCommand,
    ContactAddedEvent,
    ContactDowngradedEvent,
    ContactRemovedEvent,
    ContactRemovedDowngradedEvent,
    ContactsClearedEvent,
    ContactsDataEvent,
    ConnectCommand,
    ConnectionConnectingEvent,
    Delivery,
    GetContactsListCommand,
    IpcCommand,
    IpcEvent,
    RemoveContactCommand,
    RenameContactCommand,
    RenameSuccessEvent,
)
from metor.shared import clean_onion
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from .book import ContactBook

if TYPE_CHECKING:
    from ..controller import GuiController


ContactIntent = Literal['save', 'drop', 'live', 'rename']


@dataclass
class ContactForm:
    """One bounded nonsecret form and its exact caller intent."""

    serial: int
    intent: ContactIntent
    peer: str | None = None
    raw: str = ''
    alias: str = ''
    error: str = ''
    unknown: bool = False
    fixed: bool = False


class ContactFlow:
    """Coordinates save/rename completion before any explicitly requested navigation/call."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates empty activation-scoped form and continuation state.

        Args:
            controller: Current public-service GUI coordinator.
        Returns:
            None
        """
        self.controller = controller
        self.form: ContactForm | None = None
        self.query = ''
        self.book = ContactBook(controller)
        self._serial = 0
        self._continuation: tuple[str, ContactIntent] | None = None
        self._opening: tuple[str, Route] | None = None
        self._start_unknown: set[str] = set()

    def alias(self, peer: str) -> str:
        """Resolves current labels from Core projections without an alias cache.

        Args:
            peer: Canonical identity.
        Returns:
            str: Current permitted alias or a neutral unavailable label.
        """
        snapshot = self.controller.state.snapshot
        if snapshot:
            aliases = (
                [(entry.onion, entry.alias) for entry in snapshot.contacts]
                + [(entry.onion, entry.alias) for entry in snapshot.conversations]
                + [(entry.onion, entry.alias) for entry in snapshot.live_contexts]
                + [
                    (entry.onion, entry.alias)
                    for entry in snapshot.pending
                    if entry.onion
                ]
            )
            return next(
                (alias for onion, alias in aliases if onion == peer),
                'Contact unavailable',
            )
        return 'Contact unavailable'

    def active(self, peer: str) -> bool:
        """Checks an existing attempt/context without creating communication.

        Args:
            peer: Canonical identity.
        Returns:
            bool: Whether a current call/connection/recovery should be opened as-is.
        """
        snapshot = self.controller.state.snapshot
        return bool(
            snapshot
            and any(
                entry.onion == peer
                and (entry.session_state != 'disconnected' or entry.recovery_eligible)
                for entry in snapshot.live_contexts
            )
        )

    def begin(
        self,
        intent: ContactIntent = 'save',
        peer: str | None = None,
        *,
        scan: bool = False,
    ) -> None:
        """Opens an explicit contact form while preserving save/open/start semantics.

        Args:
            intent: Labelled caller action.
            peer: Known canonical peer for promotion or rename.
            scan: Whether the original entry requests camera/manual fallback.
        Returns:
            None
        """
        if self.controller.state.covered:
            return
        self._serial += 1
        self.form = ContactForm(
            self._serial,
            intent,
            peer,
            json.dumps({'version': 1, 'onion': peer}) if peer else '',
            self.alias(peer) if peer and intent == 'rename' else '',
            fixed=peer is not None,
        )
        self.controller.navigate(Route('V14' if scan else 'V13', peer))

    def manual(self) -> None:
        """Replaces the unavailable camera step while retaining the original caller's Back route.

        Args:
            None
        Returns:
            None
        """
        state = self.controller.state
        if not state.covered and state.route.view == 'V14' and self.form is not None:
            state.route = Route('V13', self.form.peer)

    def validate(self, raw: str) -> str | None:
        """Validates manual address or supported QR JSON using the shared public validator.

        Args:
            raw: Bounded inert contact data; a remote alias never becomes local intent.
        Returns:
            str | None: Canonical validated peer or a field-level failure.
        """
        form = self.form
        if form is None:
            return None
        if len(raw.encode('utf-8')) > GuiLimits.CONTACT_BYTES:
            form.error = 'Contact data is too long'
            return None
        raw = raw.strip()
        parsed = validate_contact_qr(
            raw if raw.startswith('{') else json.dumps({'version': 1, 'onion': raw})
        )
        if parsed.payload is None:
            form.error = 'Enter a valid contact address or supported QR data'
            return None
        peer = clean_onion(parsed.payload.onion)
        snapshot = self.controller.state.snapshot
        if snapshot and peer == clean_onion(snapshot.onion):
            form.error = 'This is your own contact identity'
            return None
        form.error = ''
        return peer

    def save(self) -> bool:
        """Admits one exact save and preserves the form on rejection or uncertainty.

        Args:
            None
        Returns:
            bool: Whether the action was admitted or an existing canonical peer opened.
        """
        form, state = self.form, self.controller.state
        if (
            form is None
            or form.unknown
            or state.covered
            or state.busy
            or self.book.pending
            or self.book.unknown
        ):
            return False
        peer = form.peer if form.fixed else self.validate(form.raw)
        if peer is None or not form.alias.strip():
            if not form.error:
                form.error = 'Enter a local alias'
            return False
        if len(form.alias.encode('utf-8')) > GuiLimits.CONTACT_BYTES:
            form.error = 'Local alias is too long'
            return False
        form.peer = peer
        if (
            form.intent != 'rename'
            and state.snapshot
            and any(
                item.onion == peer and item.saved for item in state.snapshot.contacts
            )
        ):
            self._complete(form)
            return True
        command: IpcCommand
        if form.intent == 'rename':
            if 'contact_identity_guard' not in state.capabilities:
                form.error = 'This service cannot safely rename this contact'
                return False
            command = RenameContactCommand(self.alias(peer), form.alias.strip(), peer)
        else:
            command = AddContactCommand(form.alias.strip(), peer)
        return self.controller.command(
            'contact:save:' + str(form.serial), command, IpcEvent
        )

    def recheck(self) -> bool:
        """Reads the address book after an unknown mutation without repeating it.

        Args:
            None
        Returns:
            bool: Whether read-only reconciliation was admitted.
        """
        form = self.form
        if form is None:
            return False
        return self.controller.command(
            'contact:check:' + str(form.serial),
            GetContactsListCommand(),
            ContactsDataEvent,
        )

    def select(self, peer: str, intent: ContactIntent) -> None:
        """Queues one labelled picker action for serialized admission.

        Args:
            peer: Exact saved/current peer identity.
            intent: Explicit Drop or Live action.
        Returns:
            None
        """
        if not self.controller.state.covered and self._continuation is None:
            self._continuation = peer, intent

    def remove(self, peer: str) -> bool:
        """Removes/demotes one confirmed peer with a Core identity guard.

        Args:
            peer: Immutable identity captured by the confirmation.
        Returns:
            bool: Whether removal was admitted.
        """
        if self.book.pending or self.book.unknown:
            return False
        if 'contact_identity_guard' not in self.controller.state.capabilities:
            self.controller.state.status = (
                'This service cannot safely remove this contact'
            )
            return False
        return self.controller.command(
            'contact:remove:' + peer,
            RemoveContactCommand(self.alias(peer), peer),
            IpcEvent,
        )

    def clear(self) -> bool:
        """Runs the explicit confirmed address-book clear operation.

        Args:
            None
        Returns:
            bool: Whether the action was admitted.
        """
        if self.book.pending or self.book.unknown:
            return False
        return self.controller.command(
            'contact:clear', ClearContactsCommand(), IpcEvent
        )

    def _complete(self, form: ContactForm) -> None:
        """Completes only the still-current form's original labelled intent.

        Args:
            form: Positively resolved exact form.
        Returns:
            None
        """
        controller = self.controller
        form.unknown = False
        form.error = ''
        controller.refresh_state()
        if controller.state.covered or controller.state.route.view != 'V13':
            return
        if form.intent in {'drop', 'live'} and form.peer:
            self.select(form.peer, form.intent)
        else:
            controller.back()
            controller.state.status = (
                'Contact renamed' if form.intent == 'rename' else 'Contact saved'
            )

    def install(self, update: Update) -> bool:
        """Uses positive typed outcomes and current canonical labels rather than optimistic edits.

        Args:
            update: Current-generation public response or broadcast.
        Returns:
            bool: Whether this response belongs to a contact action.
        """
        if self.book.install(update):
            return True
        if isinstance(update.event, RenameSuccessEvent) and update.event.onion:
            renamed = update.event
            state = self.controller.state
            snapshot = state.snapshot
            if snapshot is not None:
                state.snapshot = replace(
                    snapshot,
                    contacts=[
                        replace(
                            item,
                            alias=renamed.new_alias,
                            saved=False if renamed.is_demotion else item.saved,
                        )
                        if item.onion == renamed.onion
                        else item
                        for item in snapshot.contacts
                    ],
                    conversations=[
                        replace(item, alias=renamed.new_alias)
                        if item.onion == renamed.onion
                        else item
                        for item in snapshot.conversations
                    ],
                    live_contexts=[
                        replace(
                            item,
                            alias=renamed.new_alias,
                            saved=False if renamed.is_demotion else item.saved,
                        )
                        if item.onion == renamed.onion
                        else item
                        for item in snapshot.live_contexts
                    ],
                )
            if renamed.is_demotion and self.form and self.form.peer == renamed.onion:
                self.form.alias = ''
                self.form.error = 'Contact changed. Review its current details.'
            self.controller.refresh_state()
            return True
        if update.operation.startswith('contact:start:'):
            opening, self._opening = self._opening, None
            if opening is None:
                return True
            peer, caller = opening
            if isinstance(update.event, ConnectionConnectingEvent):
                if (
                    not self.controller.state.covered
                    and self.controller.state.route == caller
                ):
                    self.controller.navigate(Route('V09', peer, Delivery.LIVE))
            else:
                if update.event is None:
                    self._start_unknown.add(peer)
                self.controller.state.status = 'Live request could not be confirmed. Review current Live state before retrying.'
            self.controller.refresh_state()
            return True
        if not update.operation.startswith('contact:'):
            return False
        event, form = update.event, self.form
        if update.operation.startswith(('contact:save:', 'contact:check:')):
            if form is None or update.operation.rsplit(':', 1)[1] != str(form.serial):
                return True
            confirmed = (
                isinstance(event, (ContactAddedEvent, AliasRenamedEvent))
                and event.onion == form.peer
            )
            if isinstance(event, ContactsDataEvent):
                confirmed = any(
                    item.onion == form.peer and item.alias == form.alias.strip().lower()
                    for item in event.saved
                )
            if confirmed:
                self._complete(form)
            elif isinstance(event, AliasInUseEvent):
                form.error = 'This local alias is already in use'
            else:
                form.unknown = event is None or isinstance(event, ContactsDataEvent)
                form.error = (
                    'Result unconfirmed. Recheck before saving again.'
                    if form.unknown
                    else 'Contact was not saved. Review the address and alias.'
                )
        elif isinstance(
            event,
            (
                ContactRemovedEvent,
                ContactDowngradedEvent,
                ContactRemovedDowngradedEvent,
                ContactsClearedEvent,
            ),
        ):
            self.controller.state.status = (
                'Contact removed; active communication continues'
            )
            self.controller.refresh_state()
        else:
            self.controller.state.status = 'Contact change could not be confirmed. Refresh Contacts before trying again.'
            self.controller.refresh_state()
        return True

    def poll(self) -> None:
        """Starts an explicit continuation once, retaining existing active/recovering contexts.

        Args:
            None
        Returns:
            None
        """
        self.book.poll()
        controller, pending = self.controller, self._continuation
        if pending is None or controller.state.busy:
            return
        if controller.state.covered:
            self._continuation = None
            return
        peer, intent = pending
        active = self.active(peer)
        if intent == 'live' and not active:
            if (
                peer in self._start_unknown
                or len(self._start_unknown) >= GuiLimits.TEXT_CONTEXTS
            ):
                controller.state.status = (
                    'A prior Live request is unconfirmed. Review current Live state.'
                )
                self._continuation = None
                return
            if not controller.command(
                'contact:start:' + peer, ConnectCommand(peer), IpcEvent
            ):
                return
            self._opening = peer, controller.state.route
            self._continuation = None
            return
        self._continuation = None
        self._start_unknown.discard(peer)
        controller.navigate(
            Route(
                'V09' if intent == 'live' else 'V08',
                peer,
                Delivery.LIVE if intent == 'live' else Delivery.DROP,
            )
        )
