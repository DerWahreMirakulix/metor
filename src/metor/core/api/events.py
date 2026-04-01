"""Strict daemon-to-UI DTO definitions."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Type, TypeVar, cast

# Local Package Imports
from metor.core.api.base import IpcEvent, JsonValue
from metor.core.api.codes import EventType
from metor.core.api.registry import register_event


EntryT = TypeVar('EntryT')


def _cast_entry_list(
    values: Sequence[object], entry_type: Type[EntryT]
) -> List[EntryT]:
    """Casts JSON dictionaries in a list to their DTO entry type."""
    if values and isinstance(values[0], dict):
        return [entry_type(**cast(Dict[str, JsonValue], value)) for value in values]
    return [cast(EntryT, value) for value in values]


@dataclass
class ContactEntry:
    """Represents a structured contact entry."""

    alias: str
    onion: str


@dataclass
class HistoryEntry:
    """Represents a stored history row."""

    timestamp: str
    status: str
    onion: Optional[str]
    reason: str
    alias: Optional[str]


@dataclass
class MessageEntry:
    """Represents a stored chat message."""

    direction: str
    status: str
    payload: str
    timestamp: str


@dataclass
class UnreadMessageEntry:
    """Represents a single unread offline message."""

    timestamp: str
    payload: str


@dataclass
class ProfileEntry:
    """Represents one profile in the profile list response."""

    name: str
    is_active: bool
    is_remote: bool
    port: Optional[int]


@register_event(EventType.INIT)
@dataclass
class InitEvent(IpcEvent):
    """Initializes the UI with the local onion address."""

    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.INIT, init=False)


@register_event(EventType.TOR_KEY_ERROR)
@dataclass
class TorKeyErrorEvent(IpcEvent):
    """Signals a failure while provisioning Tor runtime keys."""

    event_type: EventType = field(default=EventType.TOR_KEY_ERROR, init=False)


@register_event(EventType.TOR_START_FAILED)
@dataclass
class TorStartFailedEvent(IpcEvent):
    """Signals that the Tor process could not be started."""

    event_type: EventType = field(default=EventType.TOR_START_FAILED, init=False)


@register_event(EventType.TOR_PROCESS_TERMINATED)
@dataclass
class TorProcessTerminatedEvent(IpcEvent):
    """Signals that Tor terminated unexpectedly during startup."""

    event_type: EventType = field(
        default=EventType.TOR_PROCESS_TERMINATED,
        init=False,
    )


@register_event(EventType.REMOTE_MSG)
@dataclass
class RemoteMsgEvent(IpcEvent):
    """Carries a live inbound message."""

    alias: str
    text: str
    timestamp: Optional[str] = None
    event_type: EventType = field(default=EventType.REMOTE_MSG, init=False)


@register_event(EventType.ACK)
@dataclass
class AckEvent(IpcEvent):
    """Confirms delivery of a live outbound message."""

    msg_id: str
    text: Optional[str] = None
    event_type: EventType = field(default=EventType.ACK, init=False)


@register_event(EventType.DROP_FAILED)
@dataclass
class DropFailedEvent(IpcEvent):
    """Marks an asynchronous drop as failed."""

    msg_id: str
    event_type: EventType = field(default=EventType.DROP_FAILED, init=False)


@register_event(EventType.CONNECTED)
@dataclass
class ConnectedEvent(IpcEvent):
    """Announces a connected peer."""

    alias: str
    onion: str
    event_type: EventType = field(default=EventType.CONNECTED, init=False)


@register_event(EventType.DISCONNECTED)
@dataclass
class DisconnectedEvent(IpcEvent):
    """Announces a disconnected peer."""

    alias: str
    event_type: EventType = field(default=EventType.DISCONNECTED, init=False)


@register_event(EventType.CONNECTION_CONNECTING)
@dataclass
class ConnectionConnectingEvent(IpcEvent):
    """Signals that an outbound connection attempt has started."""

    alias: str
    event_type: EventType = field(
        default=EventType.CONNECTION_CONNECTING,
        init=False,
    )


@register_event(EventType.RENAME_SUCCESS)
@dataclass
class RenameSuccessEvent(IpcEvent):
    """Synchronizes a peer alias rename across UIs."""

    old_alias: str
    new_alias: str
    is_demotion: bool = False
    was_saved: bool = True
    event_type: EventType = field(default=EventType.RENAME_SUCCESS, init=False)


@register_event(EventType.CONTACT_REMOVED)
@dataclass
class ContactRemovedEvent(IpcEvent):
    """Announces that a contact or peer was removed from the profile."""

    alias: str
    profile: Optional[str] = None
    event_type: EventType = field(default=EventType.CONTACT_REMOVED, init=False)


@register_event(EventType.CONNECTIONS_STATE)
@dataclass
class ConnectionsStateEvent(IpcEvent):
    """Broadcasts the current connection-state snapshot."""

    active: List[str]
    pending: List[str]
    contacts: List[str]
    is_header: bool = False
    event_type: EventType = field(default=EventType.CONNECTIONS_STATE, init=False)


@register_event(EventType.SWITCH_SUCCESS)
@dataclass
class SwitchSuccessEvent(IpcEvent):
    """Confirms a focus switch or focus clear operation."""

    alias: Optional[str] = None
    event_type: EventType = field(default=EventType.SWITCH_SUCCESS, init=False)


@register_event(EventType.CONNECTION_PENDING)
@dataclass
class ConnectionPendingEvent(IpcEvent):
    """Signals a pending outbound live connection."""

    alias: str
    event_type: EventType = field(default=EventType.CONNECTION_PENDING, init=False)


@register_event(EventType.CONNECTION_AUTO_ACCEPTED)
@dataclass
class ConnectionAutoAcceptedEvent(IpcEvent):
    """Signals that a pending connection was auto-accepted."""

    alias: str
    event_type: EventType = field(
        default=EventType.CONNECTION_AUTO_ACCEPTED,
        init=False,
    )


@register_event(EventType.CONNECTION_RETRY)
@dataclass
class ConnectionRetryEvent(IpcEvent):
    """Signals a retrying connection attempt."""

    alias: str
    attempt: int
    max_retries: int
    event_type: EventType = field(default=EventType.CONNECTION_RETRY, init=False)


@register_event(EventType.CONNECTION_FAILED)
@dataclass
class ConnectionFailedEvent(IpcEvent):
    """Signals that a connection attempt failed permanently."""

    alias: str
    event_type: EventType = field(default=EventType.CONNECTION_FAILED, init=False)


@register_event(EventType.INCOMING_CONNECTION)
@dataclass
class IncomingConnectionEvent(IpcEvent):
    """Signals an inbound live connection request."""

    alias: str
    event_type: EventType = field(default=EventType.INCOMING_CONNECTION, init=False)


@register_event(EventType.CONNECTION_REJECTED)
@dataclass
class ConnectionRejectedEvent(IpcEvent):
    """Signals that a live connection was rejected."""

    alias: str
    by_remote: bool = False
    event_type: EventType = field(default=EventType.CONNECTION_REJECTED, init=False)


@register_event(EventType.TIEBREAKER_REJECTED)
@dataclass
class TiebreakerRejectedEvent(IpcEvent):
    """Signals that a tie-breaker rejected a duplicate connection."""

    alias: str
    event_type: EventType = field(default=EventType.TIEBREAKER_REJECTED, init=False)


@register_event(EventType.AUTO_RECONNECT_ATTEMPT)
@dataclass
class AutoReconnectAttemptEvent(IpcEvent):
    """Signals an automatic reconnect attempt."""

    alias: str
    event_type: EventType = field(
        default=EventType.AUTO_RECONNECT_ATTEMPT,
        init=False,
    )


@register_event(EventType.INBOX_NOTIFICATION)
@dataclass
class InboxNotificationEvent(IpcEvent):
    """Signals new unread offline messages for a peer."""

    alias: str
    count: int = 1
    event_type: EventType = field(default=EventType.INBOX_NOTIFICATION, init=False)


@register_event(EventType.INBOX_DATA)
@dataclass
class InboxDataEvent(IpcEvent):
    """Carries buffered or unread offline messages."""

    alias: str
    messages: List[UnreadMessageEntry] = field(default_factory=list)
    inbox_counts: Dict[str, int] = field(default_factory=dict)
    is_live_flush: bool = False
    event_type: EventType = field(default=EventType.INBOX_DATA, init=False)

    def __post_init__(self) -> None:
        """Casts nested unread-message dictionaries to DTO entries."""
        self.messages = _cast_entry_list(self.messages, UnreadMessageEntry)


@register_event(EventType.CONTACTS_DATA)
@dataclass
class ContactsDataEvent(IpcEvent):
    """Returns the structured address book."""

    saved: List[ContactEntry]
    discovered: List[ContactEntry]
    profile: str
    event_type: EventType = field(default=EventType.CONTACTS_DATA, init=False)

    def __post_init__(self) -> None:
        """Casts nested contact dictionaries to DTO entries."""
        self.saved = _cast_entry_list(self.saved, ContactEntry)
        self.discovered = _cast_entry_list(self.discovered, ContactEntry)


@register_event(EventType.HISTORY_DATA)
@dataclass
class HistoryDataEvent(IpcEvent):
    """Returns stored connection history."""

    history: List[HistoryEntry]
    profile: str
    alias: Optional[str] = None
    event_type: EventType = field(default=EventType.HISTORY_DATA, init=False)

    def __post_init__(self) -> None:
        """Casts nested history dictionaries to DTO entries."""
        self.history = _cast_entry_list(self.history, HistoryEntry)


@register_event(EventType.MESSAGES_DATA)
@dataclass
class MessagesDataEvent(IpcEvent):
    """Returns stored chat messages for a peer."""

    messages: List[MessageEntry]
    alias: str
    event_type: EventType = field(default=EventType.MESSAGES_DATA, init=False)

    def __post_init__(self) -> None:
        """Casts nested message dictionaries to DTO entries."""
        self.messages = _cast_entry_list(self.messages, MessageEntry)


@register_event(EventType.INBOX_COUNTS)
@dataclass
class InboxCountsEvent(IpcEvent):
    """Returns unread-message counts grouped by peer."""

    inbox: Dict[str, int]
    event_type: EventType = field(default=EventType.INBOX_COUNTS, init=False)


@register_event(EventType.UNREAD_MESSAGES)
@dataclass
class UnreadMessagesEvent(IpcEvent):
    """Returns unread offline messages for a peer."""

    messages: List[UnreadMessageEntry]
    alias: str
    event_type: EventType = field(default=EventType.UNREAD_MESSAGES, init=False)

    def __post_init__(self) -> None:
        """Casts nested unread-message dictionaries to DTO entries."""
        self.messages = _cast_entry_list(self.messages, UnreadMessageEntry)


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
class ProfilesDataEvent(IpcEvent):
    """Returns the list of available profiles."""

    profiles: List[ProfileEntry]
    event_type: EventType = field(default=EventType.PROFILES_DATA, init=False)

    def __post_init__(self) -> None:
        """Casts nested profile dictionaries to DTO entries."""
        self.profiles = _cast_entry_list(self.profiles, ProfileEntry)


@register_event(EventType.AUTH_REQUIRED)
@dataclass
class AuthRequiredEvent(IpcEvent):
    """Signals that the session must authenticate first."""

    event_type: EventType = field(default=EventType.AUTH_REQUIRED, init=False)


@register_event(EventType.INVALID_PASSWORD)
@dataclass
class InvalidPasswordEvent(IpcEvent):
    """Signals that the supplied password was invalid."""

    event_type: EventType = field(default=EventType.INVALID_PASSWORD, init=False)


@register_event(EventType.ALREADY_UNLOCKED)
@dataclass
class AlreadyUnlockedEvent(IpcEvent):
    """Signals that the daemon is already unlocked."""

    event_type: EventType = field(default=EventType.ALREADY_UNLOCKED, init=False)


@register_event(EventType.SESSION_AUTHENTICATED)
@dataclass
class SessionAuthenticatedEvent(IpcEvent):
    """Signals that the current session authenticated successfully."""

    event_type: EventType = field(
        default=EventType.SESSION_AUTHENTICATED,
        init=False,
    )


@register_event(EventType.SELF_DESTRUCT_INITIATED)
@dataclass
class SelfDestructInitiatedEvent(IpcEvent):
    """Signals that daemon self-destruction has started."""

    event_type: EventType = field(
        default=EventType.SELF_DESTRUCT_INITIATED,
        init=False,
    )


@register_event(EventType.DAEMON_UNLOCKED)
@dataclass
class DaemonUnlockedEvent(IpcEvent):
    """Signals that the daemon was unlocked successfully."""

    event_type: EventType = field(default=EventType.DAEMON_UNLOCKED, init=False)


@register_event(EventType.DAEMON_LOCKED)
@dataclass
class DaemonLockedEvent(IpcEvent):
    """Signals that the daemon is locked."""

    event_type: EventType = field(default=EventType.DAEMON_LOCKED, init=False)


@register_event(EventType.DAEMON_OFFLINE)
@dataclass
class DaemonOfflineEvent(IpcEvent):
    """Signals that no local daemon is running."""

    event_type: EventType = field(default=EventType.DAEMON_OFFLINE, init=False)


@register_event(EventType.UNKNOWN_COMMAND)
@dataclass
class UnknownCommandEvent(IpcEvent):
    """Signals that the daemon received an unknown command."""

    event_type: EventType = field(default=EventType.UNKNOWN_COMMAND, init=False)


@register_event(EventType.INVALID_SETTING_KEY)
@dataclass
class InvalidSettingKeyEvent(IpcEvent):
    """Signals that a setting key was invalid."""

    event_type: EventType = field(default=EventType.INVALID_SETTING_KEY, init=False)


@register_event(EventType.INVALID_CONFIG_KEY)
@dataclass
class InvalidConfigKeyEvent(IpcEvent):
    """Signals that a configuration key was invalid."""

    event_type: EventType = field(default=EventType.INVALID_CONFIG_KEY, init=False)


@register_event(EventType.DAEMON_CANNOT_MANAGE_UI)
@dataclass
class DaemonCannotManageUiEvent(IpcEvent):
    """Signals that a UI-only setting was routed to the daemon."""

    event_type: EventType = field(
        default=EventType.DAEMON_CANNOT_MANAGE_UI,
        init=False,
    )


@register_event(EventType.SETTING_UPDATED)
@dataclass
class SettingUpdatedEvent(IpcEvent):
    """Signals that a global setting was updated."""

    key: str
    event_type: EventType = field(default=EventType.SETTING_UPDATED, init=False)


@register_event(EventType.SETTING_UPDATE_FAILED)
@dataclass
class SettingUpdateFailedEvent(IpcEvent):
    """Signals that a global setting update failed."""

    event_type: EventType = field(
        default=EventType.SETTING_UPDATE_FAILED,
        init=False,
    )


@register_event(EventType.SETTING_TYPE_ERROR)
@dataclass
class SettingTypeErrorEvent(IpcEvent):
    """Signals a type mismatch while applying a setting value."""

    event_type: EventType = field(default=EventType.SETTING_TYPE_ERROR, init=False)


@register_event(EventType.SETTING_DATA)
@dataclass
class SettingDataEvent(IpcEvent):
    """Returns a global setting value."""

    key: str
    value: str
    event_type: EventType = field(default=EventType.SETTING_DATA, init=False)


@register_event(EventType.CONFIG_UPDATED)
@dataclass
class ConfigUpdatedEvent(IpcEvent):
    """Signals that a profile-specific config override was updated."""

    key: str
    event_type: EventType = field(default=EventType.CONFIG_UPDATED, init=False)


@register_event(EventType.CONFIG_UPDATE_FAILED)
@dataclass
class ConfigUpdateFailedEvent(IpcEvent):
    """Signals that a config update failed."""

    event_type: EventType = field(
        default=EventType.CONFIG_UPDATE_FAILED,
        init=False,
    )


@register_event(EventType.CONFIG_DATA)
@dataclass
class ConfigDataEvent(IpcEvent):
    """Returns a profile-specific config value."""

    key: str
    value: str
    event_type: EventType = field(default=EventType.CONFIG_DATA, init=False)


@register_event(EventType.CONFIG_SYNCED)
@dataclass
class ConfigSyncedEvent(IpcEvent):
    """Signals that profile config overrides were cleared."""

    event_type: EventType = field(default=EventType.CONFIG_SYNCED, init=False)


@register_event(EventType.CANNOT_CONNECT_SELF)
@dataclass
class CannotConnectSelfEvent(IpcEvent):
    """Signals that the local onion cannot connect to itself."""

    event_type: EventType = field(default=EventType.CANNOT_CONNECT_SELF, init=False)


@register_event(EventType.INVALID_TARGET)
@dataclass
class InvalidTargetEvent(IpcEvent):
    """Signals that a user-supplied target could not be resolved."""

    target: str
    event_type: EventType = field(default=EventType.INVALID_TARGET, init=False)


@register_event(EventType.CANNOT_SWITCH_SELF)
@dataclass
class CannotSwitchSelfEvent(IpcEvent):
    """Signals that the UI cannot focus the local onion."""

    event_type: EventType = field(default=EventType.CANNOT_SWITCH_SELF, init=False)


@register_event(EventType.NO_CONNECTION_TO_REJECT)
@dataclass
class NoConnectionToRejectEvent(IpcEvent):
    """Signals that there is no connection to reject."""

    alias: str
    event_type: EventType = field(
        default=EventType.NO_CONNECTION_TO_REJECT,
        init=False,
    )


@register_event(EventType.NO_CONNECTION_TO_DISCONNECT)
@dataclass
class NoConnectionToDisconnectEvent(IpcEvent):
    """Signals that there is no connection to disconnect."""

    alias: str
    event_type: EventType = field(
        default=EventType.NO_CONNECTION_TO_DISCONNECT,
        init=False,
    )


@register_event(EventType.NO_PENDING_CONNECTION)
@dataclass
class NoPendingConnectionEvent(IpcEvent):
    """Signals that there is no pending connection to accept."""

    alias: str
    event_type: EventType = field(default=EventType.NO_PENDING_CONNECTION, init=False)


@register_event(EventType.MAX_CONNECTIONS_REACHED)
@dataclass
class MaxConnectionsReachedEvent(IpcEvent):
    """Signals that the maximum live connection count was reached."""

    target: str
    max_conn: int
    event_type: EventType = field(
        default=EventType.MAX_CONNECTIONS_REACHED,
        init=False,
    )


@register_event(EventType.DROPS_DISABLED)
@dataclass
class DropsDisabledEvent(IpcEvent):
    """Signals that offline drops are disabled."""

    event_type: EventType = field(default=EventType.DROPS_DISABLED, init=False)


@register_event(EventType.CANNOT_DROP_SELF)
@dataclass
class CannotDropSelfEvent(IpcEvent):
    """Signals that the local onion cannot send drops to itself."""

    event_type: EventType = field(default=EventType.CANNOT_DROP_SELF, init=False)


@register_event(EventType.DROP_QUEUED)
@dataclass
class DropQueuedEvent(IpcEvent):
    """Signals that a drop was queued successfully."""

    alias: str
    event_type: EventType = field(default=EventType.DROP_QUEUED, init=False)


@register_event(EventType.NO_PENDING_LIVE_MSGS)
@dataclass
class NoPendingLiveMessagesEvent(IpcEvent):
    """Signals that no pending live messages existed for fallback."""

    alias: str
    event_type: EventType = field(default=EventType.NO_PENDING_LIVE_MSGS, init=False)


@register_event(EventType.FALLBACK_SUCCESS)
@dataclass
class FallbackSuccessEvent(IpcEvent):
    """Signals that pending live messages were converted to drops."""

    alias: str
    count: int
    msg_ids: List[str]
    event_type: EventType = field(default=EventType.FALLBACK_SUCCESS, init=False)


@register_event(EventType.CONTACT_ADDED)
@dataclass
class ContactAddedEvent(IpcEvent):
    """Signals that a contact was added to the address book."""

    alias: str
    profile: str
    event_type: EventType = field(default=EventType.CONTACT_ADDED, init=False)


@register_event(EventType.PEER_NOT_FOUND)
@dataclass
class PeerNotFoundEvent(IpcEvent):
    """Signals that a user-supplied peer could not be resolved."""

    target: str
    event_type: EventType = field(default=EventType.PEER_NOT_FOUND, init=False)


@register_event(EventType.CONTACT_ALREADY_SAVED)
@dataclass
class ContactAlreadySavedEvent(IpcEvent):
    """Signals that a discovered peer was already saved."""

    alias: str
    event_type: EventType = field(
        default=EventType.CONTACT_ALREADY_SAVED,
        init=False,
    )


@register_event(EventType.PEER_PROMOTED)
@dataclass
class PeerPromotedEvent(IpcEvent):
    """Signals that a discovered peer was promoted to a contact."""

    alias: str
    event_type: EventType = field(default=EventType.PEER_PROMOTED, init=False)


@register_event(EventType.ALIAS_IN_USE)
@dataclass
class AliasInUseEvent(IpcEvent):
    """Signals that an alias is already in use."""

    alias: str
    event_type: EventType = field(default=EventType.ALIAS_IN_USE, init=False)


@register_event(EventType.ONION_IN_USE)
@dataclass
class OnionInUseEvent(IpcEvent):
    """Signals that an onion is already bound to a saved contact."""

    alias: str
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
    event_type: EventType = field(default=EventType.ALIAS_RENAMED, init=False)


@register_event(EventType.PEER_CANT_DELETE_ACTIVE)
@dataclass
class PeerCantDeleteActiveEvent(IpcEvent):
    """Signals that an active peer cannot be deleted."""

    alias: str
    event_type: EventType = field(
        default=EventType.PEER_CANT_DELETE_ACTIVE,
        init=False,
    )


@register_event(EventType.CONTACT_DOWNGRADED)
@dataclass
class ContactDowngradedEvent(IpcEvent):
    """Signals that a saved contact was downgraded to unsaved."""

    alias: str
    event_type: EventType = field(default=EventType.CONTACT_DOWNGRADED, init=False)


@register_event(EventType.CONTACT_REMOVED_DOWNGRADED)
@dataclass
class ContactRemovedDowngradedEvent(IpcEvent):
    """Signals that a removed contact was downgraded to a session peer."""

    alias: str
    new_alias: str
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
    event_type: EventType = field(default=EventType.PEER_ANONYMIZED, init=False)


@register_event(EventType.PEER_REMOVED)
@dataclass
class PeerRemovedEvent(IpcEvent):
    """Signals that a discovered peer was removed."""

    alias: str
    event_type: EventType = field(default=EventType.PEER_REMOVED, init=False)


@register_event(EventType.CONTACTS_CLEARED)
@dataclass
class ContactsClearedEvent(IpcEvent):
    """Signals that the address book was cleared."""

    profile: str
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
    event_type: EventType = field(default=EventType.MESSAGES_CLEARED, init=False)


@register_event(EventType.MESSAGES_CLEARED_NON_CONTACTS)
@dataclass
class MessagesClearedNonContactsEvent(IpcEvent):
    """Signals that non-contact messages for a peer were cleared."""

    alias: str
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
    event_type: EventType = field(default=EventType.DB_CLEARED, init=False)


@register_event(EventType.DB_CLEAR_FAILED)
@dataclass
class DatabaseClearFailedEvent(IpcEvent):
    """Signals that clearing the profile database failed."""

    event_type: EventType = field(default=EventType.DB_CLEAR_FAILED, init=False)


@register_event(EventType.RETUNNEL_INITIATED)
@dataclass
class RetunnelInitiatedEvent(IpcEvent):
    """Signals that retunneling has started for a peer."""

    alias: str
    event_type: EventType = field(default=EventType.RETUNNEL_INITIATED, init=False)


@register_event(EventType.RETUNNEL_SUCCESS)
@dataclass
class RetunnelSuccessEvent(IpcEvent):
    """Signals that retunneling succeeded for a peer."""

    alias: str
    event_type: EventType = field(default=EventType.RETUNNEL_SUCCESS, init=False)


@register_event(EventType.RETUNNEL_FAILED)
@dataclass
class RetunnelFailedEvent(IpcEvent):
    """Signals that retunneling failed for a peer."""

    alias: str
    error: Optional[str] = None
    event_type: EventType = field(default=EventType.RETUNNEL_FAILED, init=False)
