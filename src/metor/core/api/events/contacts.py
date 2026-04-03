"""Contact and alias-management IPC event DTOs."""

from dataclasses import dataclass, field
from typing import Optional

# Local Package Imports
from metor.core.api.base import IpcEvent
from metor.core.api.codes import EventType
from metor.core.api.registry import register_event


@register_event(EventType.RENAME_SUCCESS)
@dataclass
class RenameSuccessEvent(IpcEvent):
    """Synchronizes a peer alias rename across UIs."""

    old_alias: str
    new_alias: str
    onion: Optional[str] = None
    is_demotion: bool = False
    was_saved: bool = True
    event_type: EventType = field(default=EventType.RENAME_SUCCESS, init=False)


@register_event(EventType.CONTACT_REMOVED)
@dataclass
class ContactRemovedEvent(IpcEvent):
    """Announces that a contact or peer was removed from the profile."""

    alias: str
    onion: Optional[str] = None
    profile: Optional[str] = None
    event_type: EventType = field(default=EventType.CONTACT_REMOVED, init=False)


@register_event(EventType.CONTACT_ADDED)
@dataclass
class ContactAddedEvent(IpcEvent):
    """Signals that a contact was added to the address book."""

    alias: str
    profile: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.CONTACT_ADDED, init=False)


@register_event(EventType.PEER_NOT_FOUND)
@dataclass
class PeerNotFoundEvent(IpcEvent):
    """Signals that a user-supplied peer could not be resolved."""

    target: str
    event_type: EventType = field(default=EventType.PEER_NOT_FOUND, init=False)


@register_event(EventType.DISCOVERED_PEER_NOT_FOUND)
@dataclass
class DiscoveredPeerNotFoundEvent(IpcEvent):
    """Signals that no discovered peer matched a requested promotion target."""

    target: str
    event_type: EventType = field(
        default=EventType.DISCOVERED_PEER_NOT_FOUND,
        init=False,
    )


@register_event(EventType.CONTACT_ALREADY_SAVED)
@dataclass
class ContactAlreadySavedEvent(IpcEvent):
    """Signals that a discovered peer was already saved."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(
        default=EventType.CONTACT_ALREADY_SAVED,
        init=False,
    )


@register_event(EventType.PEER_PROMOTED)
@dataclass
class PeerPromotedEvent(IpcEvent):
    """Signals that a discovered peer was promoted to a contact."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.PEER_PROMOTED, init=False)


@register_event(EventType.ALIAS_IN_USE)
@dataclass
class AliasInUseEvent(IpcEvent):
    """Signals that an alias is already in use."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.ALIAS_IN_USE, init=False)


@register_event(EventType.ONION_IN_USE)
@dataclass
class OnionInUseEvent(IpcEvent):
    """Signals that an onion is already bound to a saved contact."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.ONION_IN_USE, init=False)


@register_event(EventType.ALIAS_SAME)
@dataclass
class AliasSameEvent(IpcEvent):
    """Signals that a rename reused the same alias."""

    event_type: EventType = field(default=EventType.ALIAS_SAME, init=False)


@register_event(EventType.ALIAS_NOT_FOUND)
@dataclass
class AliasNotFoundEvent(IpcEvent):
    """Signals that the requested alias does not exist."""

    alias: str
    event_type: EventType = field(default=EventType.ALIAS_NOT_FOUND, init=False)


@register_event(EventType.ALIAS_RENAMED)
@dataclass
class AliasRenamedEvent(IpcEvent):
    """Signals that an alias was renamed successfully."""

    old_alias: str
    new_alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.ALIAS_RENAMED, init=False)


@register_event(EventType.PEER_CANT_DELETE_ACTIVE)
@dataclass
class PeerCantDeleteActiveEvent(IpcEvent):
    """Signals that an active peer cannot be deleted."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(
        default=EventType.PEER_CANT_DELETE_ACTIVE,
        init=False,
    )


@register_event(EventType.CONTACT_DOWNGRADED)
@dataclass
class ContactDowngradedEvent(IpcEvent):
    """Signals that a saved contact was downgraded to unsaved."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.CONTACT_DOWNGRADED, init=False)


@register_event(EventType.CONTACT_REMOVED_DOWNGRADED)
@dataclass
class ContactRemovedDowngradedEvent(IpcEvent):
    """Signals that a removed contact was downgraded to a session peer."""

    alias: str
    new_alias: str
    onion: Optional[str] = None
    event_type: EventType = field(
        default=EventType.CONTACT_REMOVED_DOWNGRADED,
        init=False,
    )


@register_event(EventType.PEER_ANONYMIZED)
@dataclass
class PeerAnonymizedEvent(IpcEvent):
    """Signals that a discovered peer was anonymized."""

    alias: str
    new_alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.PEER_ANONYMIZED, init=False)


@register_event(EventType.PEER_REMOVED)
@dataclass
class PeerRemovedEvent(IpcEvent):
    """Signals that a discovered peer was removed."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.PEER_REMOVED, init=False)
