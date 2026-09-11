"""Data-returning IPC event DTOs."""

from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional

# Local Package Imports
from metor.core.api.base import IpcEvent
from metor.core.api.codes import EventType
from metor.core.api.events.entries import (
    ContactEntry,
    DropConversationSummaryEntry,
    LiveContextEntry,
    MessageEntry,
    PendingConnectionEntry,
    RetainedMessageEntry,
    ProfileEntry,
    SettingSnapshotEntry,
    UnreadInboxSummaryEntry,
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


@register_event(EventType.RETAINED_MESSAGES)
@dataclass
class RetainedMessagesEvent(NestedEntryCastingMixin, IpcEvent):
    """Returns one stable page of non-consuming retained-item descriptors."""

    messages: List[RetainedMessageEntry] = field(default_factory=list)
    next_cursor: Optional[str] = None
    inventory_version: str = '0'
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'messages': RetainedMessageEntry,
    }
    event_type: EventType = field(default=EventType.RETAINED_MESSAGES, init=False)


@register_event(EventType.RETAINED_MESSAGES_UNAVAILABLE)
@dataclass
class RetainedMessagesUnavailableEvent(IpcEvent):
    """Rejects an invalid or no-longer-consistent inventory cursor."""

    reason: str
    retryable: bool = True
    event_type: EventType = field(
        default=EventType.RETAINED_MESSAGES_UNAVAILABLE,
        init=False,
    )


@register_event(EventType.INBOX_COUNTS)
@dataclass
class InboxCountsEvent(IpcEvent):
    """Returns unread-message counts grouped by peer."""

    inbox: Dict[str, int]
    event_type: EventType = field(default=EventType.INBOX_COUNTS, init=False)


@register_event(EventType.CHAT_STARTUP_STATE)
@dataclass
class ChatStartupStateEvent(NestedEntryCastingMixin, IpcEvent):
    """Returns the first-attach chat snapshot with sessions and unread summaries."""

    active: List[str]
    contacts: List[str]
    pending: List[PendingConnectionEntry] = field(default_factory=list)
    unread: List[UnreadInboxSummaryEntry] = field(default_factory=list)
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'pending': PendingConnectionEntry,
        'unread': UnreadInboxSummaryEntry,
    }
    event_type: EventType = field(default=EventType.CHAT_STARTUP_STATE, init=False)


@register_event(EventType.RUNTIME_SNAPSHOT)
@dataclass
class RuntimeSnapshotEvent(NestedEntryCastingMixin, IpcEvent):
    """Returns one aggregate, content-free runtime projection for rich clients."""

    profile: str
    onion: str
    contacts: List[ContactEntry] = field(default_factory=list)
    conversations: List[DropConversationSummaryEntry] = field(default_factory=list)
    live_contexts: List[LiveContextEntry] = field(default_factory=list)
    pending: List[PendingConnectionEntry] = field(default_factory=list)
    settings_version: str = '1'
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'contacts': ContactEntry,
        'conversations': DropConversationSummaryEntry,
        'live_contexts': LiveContextEntry,
        'pending': PendingConnectionEntry,
    }
    event_type: EventType = field(default=EventType.RUNTIME_SNAPSHOT, init=False)


@register_event(EventType.RUNTIME_SNAPSHOT_UNAVAILABLE)
@dataclass
class RuntimeSnapshotUnavailableEvent(IpcEvent):
    """Signals that sustained mutation prevented an authoritative snapshot."""

    retryable: bool = True
    event_type: EventType = field(
        default=EventType.RUNTIME_SNAPSHOT_UNAVAILABLE,
        init=False,
    )


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
    """
    Returns the list of available profiles.

    Attributes:
        profiles (List[ProfileEntry]): Structured profile rows.
        event_type (EventType): The stable IPC routing code.
    """

    profiles: List[ProfileEntry]
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'profiles': ProfileEntry,
    }
    event_type: EventType = field(default=EventType.PROFILES_DATA, init=False)


@register_event(EventType.SETTINGS_LIST_DATA)
@dataclass
class SettingsListDataEvent(NestedEntryCastingMixin, IpcEvent):
    """
    Returns a structured global settings snapshot.

    Attributes:
        scope (str): The snapshot scope such as `ui` or `daemon`.
        entries (List[SettingSnapshotEntry]): The ordered snapshot rows.
        event_type (EventType): The stable IPC routing code.
    """

    scope: str
    entries: List[SettingSnapshotEntry] = field(default_factory=list)
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'entries': SettingSnapshotEntry,
    }
    event_type: EventType = field(default=EventType.SETTINGS_LIST_DATA, init=False)


@register_event(EventType.CONFIG_LIST_DATA)
@dataclass
class ConfigListDataEvent(NestedEntryCastingMixin, IpcEvent):
    """
    Returns a structured effective profile-config snapshot.

    Attributes:
        scope (str): The snapshot scope such as `ui`, `profile`, or `daemon`.
        profile (str): The active profile name.
        entries (List[SettingSnapshotEntry]): The ordered snapshot rows.
        event_type (EventType): The stable IPC routing code.
    """

    scope: str
    profile: str
    entries: List[SettingSnapshotEntry] = field(default_factory=list)
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'entries': SettingSnapshotEntry,
    }
    event_type: EventType = field(default=EventType.CONFIG_LIST_DATA, init=False)
