"""Clear-result and maintenance IPC event DTOs."""

from dataclasses import dataclass, field
from typing import Optional

# Local Package Imports
from metor.core.api.base import IpcEvent
from metor.core.api.codes import EventType
from metor.core.api.registry import register_event


@register_event(EventType.CONTACTS_CLEARED)
@dataclass
class ContactsClearedEvent(IpcEvent):
    """Signals that the address book was cleared."""

    profile: str
    preserved_peers: int = 0
    event_type: EventType = field(default=EventType.CONTACTS_CLEARED, init=False)


@register_event(EventType.CONTACTS_CLEAR_FAILED)
@dataclass
class ContactsClearFailedEvent(IpcEvent):
    """Signals that clearing the address book failed."""

    event_type: EventType = field(
        default=EventType.CONTACTS_CLEAR_FAILED,
        init=False,
    )


@register_event(EventType.HISTORY_CLEARED)
@dataclass
class HistoryClearedEvent(IpcEvent):
    """Signals that a peer-specific history was cleared."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.HISTORY_CLEARED, init=False)


@register_event(EventType.HISTORY_CLEARED_ALL)
@dataclass
class HistoryClearedAllEvent(IpcEvent):
    """Signals that profile history was cleared."""

    profile: str
    event_type: EventType = field(default=EventType.HISTORY_CLEARED_ALL, init=False)


@register_event(EventType.HISTORY_CLEAR_FAILED)
@dataclass
class HistoryClearFailedEvent(IpcEvent):
    """Signals that clearing history failed."""

    event_type: EventType = field(default=EventType.HISTORY_CLEAR_FAILED, init=False)


@register_event(EventType.MESSAGES_CLEARED)
@dataclass
class MessagesClearedEvent(IpcEvent):
    """Signals that peer-specific messages were cleared."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.MESSAGES_CLEARED, init=False)


@register_event(EventType.MESSAGES_CLEARED_NON_CONTACTS)
@dataclass
class MessagesClearedNonContactsEvent(IpcEvent):
    """Signals that non-contact messages for a peer were cleared."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(
        default=EventType.MESSAGES_CLEARED_NON_CONTACTS,
        init=False,
    )


@register_event(EventType.MESSAGES_CLEARED_NON_CONTACTS_ALL)
@dataclass
class MessagesClearedNonContactsAllEvent(IpcEvent):
    """Signals that non-contact messages for a profile were cleared."""

    profile: str
    event_type: EventType = field(
        default=EventType.MESSAGES_CLEARED_NON_CONTACTS_ALL,
        init=False,
    )


@register_event(EventType.MESSAGES_CLEARED_ALL)
@dataclass
class MessagesClearedAllEvent(IpcEvent):
    """Signals that all profile messages were cleared."""

    profile: str
    event_type: EventType = field(default=EventType.MESSAGES_CLEARED_ALL, init=False)


@register_event(EventType.MESSAGES_CLEAR_FAILED)
@dataclass
class MessagesClearFailedEvent(IpcEvent):
    """Signals that clearing messages failed."""

    event_type: EventType = field(default=EventType.MESSAGES_CLEAR_FAILED, init=False)


@register_event(EventType.DB_CLEARED)
@dataclass
class DatabaseClearedEvent(IpcEvent):
    """Signals that a profile database was cleared."""

    profile: str
    preserved_peers: int = 0
    event_type: EventType = field(default=EventType.DB_CLEARED, init=False)


@register_event(EventType.DB_CLEAR_FAILED)
@dataclass
class DatabaseClearFailedEvent(IpcEvent):
    """Signals that clearing the profile database failed."""

    event_type: EventType = field(default=EventType.DB_CLEAR_FAILED, init=False)
