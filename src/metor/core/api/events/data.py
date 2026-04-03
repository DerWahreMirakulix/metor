"""Data-returning IPC event DTOs."""

from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional

# Local Package Imports
from metor.core.api.base import IpcEvent
from metor.core.api.codes import EventType
from metor.core.api.events.entries import (
    ContactEntry,
    MessageEntry,
    ProfileEntry,
    UnreadMessageEntry,
)
from metor.core.api.registry import register_event
from metor.core.api.events.shared import NestedEntryCastingMixin


@register_event(EventType.INBOX_NOTIFICATION)
@dataclass
class InboxNotificationEvent(IpcEvent):
    """Signals new unread offline messages for a peer."""

    alias: str
    onion: Optional[str] = None
    count: int = 1
    event_type: EventType = field(default=EventType.INBOX_NOTIFICATION, init=False)


@register_event(EventType.INBOX_DATA)
@dataclass
class InboxDataEvent(NestedEntryCastingMixin, IpcEvent):
    """Carries buffered or unread offline messages."""

    alias: str
    onion: Optional[str] = None
    messages: List[UnreadMessageEntry] = field(default_factory=list)
    inbox_counts: Dict[str, int] = field(default_factory=dict)
    is_live_flush: bool = False
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'messages': UnreadMessageEntry,
    }
    event_type: EventType = field(default=EventType.INBOX_DATA, init=False)


@register_event(EventType.CONTACTS_DATA)
@dataclass
class ContactsDataEvent(NestedEntryCastingMixin, IpcEvent):
    """Returns the structured address book."""

    saved: List[ContactEntry]
    discovered: List[ContactEntry]
    profile: str
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'saved': ContactEntry,
        'discovered': ContactEntry,
    }
    event_type: EventType = field(default=EventType.CONTACTS_DATA, init=False)


@register_event(EventType.MESSAGES_DATA)
@dataclass
class MessagesDataEvent(NestedEntryCastingMixin, IpcEvent):
    """Returns stored chat messages for a peer."""

    messages: List[MessageEntry]
    alias: str
    onion: Optional[str] = None
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'messages': MessageEntry,
    }
    event_type: EventType = field(default=EventType.MESSAGES_DATA, init=False)


@register_event(EventType.INBOX_COUNTS)
@dataclass
class InboxCountsEvent(IpcEvent):
    """Returns unread-message counts grouped by peer."""

    inbox: Dict[str, int]
    event_type: EventType = field(default=EventType.INBOX_COUNTS, init=False)


@register_event(EventType.UNREAD_MESSAGES)
@dataclass
class UnreadMessagesEvent(NestedEntryCastingMixin, IpcEvent):
    """Returns unread messages consumed explicitly for a peer."""

    messages: List[UnreadMessageEntry]
    alias: str
    onion: Optional[str] = None
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'messages': UnreadMessageEntry,
    }
    event_type: EventType = field(default=EventType.UNREAD_MESSAGES, init=False)


@register_event(EventType.ADDRESS_CURRENT)
@dataclass
class AddressCurrentEvent(IpcEvent):
    """Returns the current onion address."""

    profile: str
    onion: str
    event_type: EventType = field(default=EventType.ADDRESS_CURRENT, init=False)


@register_event(EventType.ADDRESS_GENERATED)
@dataclass
class AddressGeneratedEvent(IpcEvent):
    """Returns a newly generated onion address."""

    profile: str
    onion: str
    event_type: EventType = field(default=EventType.ADDRESS_GENERATED, init=False)


@register_event(EventType.ADDRESS_CANT_GENERATE_RUNNING)
@dataclass
class AddressCantGenerateRunningEvent(IpcEvent):
    """Signals that address generation is blocked by a running daemon."""

    profile: str
    event_type: EventType = field(
        default=EventType.ADDRESS_CANT_GENERATE_RUNNING,
        init=False,
    )


@register_event(EventType.ADDRESS_NOT_GENERATED)
@dataclass
class AddressNotGeneratedEvent(IpcEvent):
    """Signals that a profile has no generated onion address yet."""

    profile: str
    event_type: EventType = field(
        default=EventType.ADDRESS_NOT_GENERATED,
        init=False,
    )


@register_event(EventType.PROFILES_DATA)
@dataclass
class ProfilesDataEvent(NestedEntryCastingMixin, IpcEvent):
    """Returns the list of available profiles."""

    profiles: List[ProfileEntry]
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'profiles': ProfileEntry,
    }
    event_type: EventType = field(default=EventType.PROFILES_DATA, init=False)
