"""Immediate contact presentation derived exclusively from confirmed public Core facts."""

from dataclasses import replace

from metor.core.api import (
    AliasRenamedEvent,
    ContactAddedEvent,
    ContactDowngradedEvent,
    ContactEntry,
    ContactRemovedDowngradedEvent,
    ContactRemovedEvent,
    ContactsDataEvent,
    IpcEvent,
    PeerPromotedEvent,
    RenameSuccessEvent,
)
from metor.ui.gui.state import GuiState


def project_contact(state: GuiState, event: IpcEvent | None) -> bool:
    """Updates permitted labels and saved facts before returning to a contact's caller.

    Args:
        state: Current-generation GUI presentation, never an authorization source.
        event: Confirmed typed Core result or broadcast; absent/rejected results do nothing.
    Returns:
        bool: Whether this event supplies contact presentation facts.
    """
    snapshot = state.snapshot
    if state.covered or snapshot is None:
        return False
    if event is not None and (
        (
            event.epoch is not None
            and snapshot.epoch is not None
            and event.epoch != snapshot.epoch
        )
        or (
            event.revision is not None
            and snapshot.revision is not None
            and event.revision < snapshot.revision
        )
    ):
        return False
    if isinstance(event, ContactsDataEvent):
        if event.profile != snapshot.profile:
            return False
        contacts = [replace(item, saved=True) for item in event.saved] + [
            replace(item, saved=False) for item in event.discovered
        ]
        aliases = {item.onion: item.alias for item in contacts}
        saved = {item.onion: item.saved for item in contacts}
    else:
        peer: str | None
        status: bool | None = None
        if isinstance(event, (ContactAddedEvent, PeerPromotedEvent)):
            if (
                isinstance(event, ContactAddedEvent)
                and event.profile != snapshot.profile
            ):
                return False
            peer, alias, status = event.onion, event.alias, True
        elif isinstance(event, (AliasRenamedEvent, RenameSuccessEvent)):
            peer, alias = event.onion, event.new_alias
            if isinstance(event, RenameSuccessEvent) and event.is_demotion:
                status = False
        elif isinstance(event, ContactRemovedDowngradedEvent):
            peer, alias, status = event.onion, event.new_alias, False
        elif isinstance(event, ContactDowngradedEvent):
            peer, alias, status = event.onion, event.alias, False
        elif isinstance(event, ContactRemovedEvent) and event.onion:
            state.snapshot = replace(
                snapshot,
                contacts=[
                    item for item in snapshot.contacts if item.onion != event.onion
                ],
            )
            return True
        else:
            return False
        if not peer:
            return False
        aliases = {peer: alias}
        saved = {} if status is None else {peer: status}
        contacts = [
            replace(item, alias=alias, saved=item.saved if status is None else status)
            if item.onion == peer
            else item
            for item in snapshot.contacts
        ]
        if status is not None and not any(item.onion == peer for item in contacts):
            contacts.append(ContactEntry(alias, peer, status))
    state.snapshot = replace(
        snapshot,
        contacts=contacts,
        conversations=[
            replace(item, alias=aliases.get(item.onion, item.alias))
            for item in snapshot.conversations
        ],
        live_contexts=[
            replace(
                item,
                alias=aliases.get(item.onion, item.alias),
                saved=saved.get(item.onion, item.saved),
            )
            for item in snapshot.live_contexts
        ],
        pending=[
            replace(item, alias=aliases.get(item.onion or '', item.alias))
            for item in snapshot.pending
        ],
    )
    return True
