"""
Module defining the strict Data Transfer Objects (DTOs) for outbound Daemon events.
Utilizes dynamic decorators for registry mapping and specific Domain Codes for status tracking.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict

# Local Package Imports
from metor.core.api.base import IpcEvent
from metor.core.api.codes import (
    ContactCode,
    EventType,
    Action,
    DomainCode,
    NetworkCode,
)
from metor.core.api.registry import register_event


# --- Sub-Models (Nested DTOs) ---


@dataclass
class ContactEntry:
    """
    Represents a single contact entry in the address book.

    Attributes:
        alias (str): The user-defined alias.
        onion (str): The remote onion address.
    """

    alias: str
    onion: str


@dataclass
class HistoryEntry:
    """
    Represents a single historical network event.

    Attributes:
        timestamp (str): The ISO 8601 timestamp.
        status (str): The event state.
        onion (Optional[str]): The associated onion address, if any.
        reason (str): The context or reason for the event.
        alias (str): The resolved alias of the peer.
    """

    timestamp: str
    status: str
    onion: Optional[str]
    reason: str
    alias: str


@dataclass
class MessageEntry:
    """
    Represents a chat message within the history database.

    Attributes:
        direction (str): The flow direction ('in' or 'out').
        status (str): The current message status.
        payload (str): The actual message content.
        timestamp (str): The ISO 8601 timestamp.
    """

    direction: str
    status: str
    payload: str
    timestamp: str


@dataclass
class UnreadMessageEntry:
    """
    Represents an unread asynchronous message.

    Attributes:
        timestamp (str): The ISO 8601 timestamp.
        payload (str): The unread message content.
    """

    timestamp: str
    payload: str


@dataclass
class ProfileEntry:
    """
    Represents a Metor profile state.

    Attributes:
        name (str): The profile name.
        is_active (bool): True if this is the currently loaded profile.
        is_remote (bool): True if configured for remote Daemon access.
        port (Optional[int]): The bound static port, if applicable.
    """

    name: str
    is_active: bool
    is_remote: bool
    port: Optional[int]


# --- Core State & Chat Events ---


@register_event(EventType.INIT)
@dataclass
class InitEvent(IpcEvent):
    """
    Data Transfer Object for daemon initialization state.

    Attributes:
        onion (Optional[str]): The local onion address.
        type (EventType): The strict IPC event type code.
    """

    onion: Optional[str] = None
    type: EventType = field(default=EventType.INIT, init=False)


@register_event(EventType.REMOTE_MSG)
@dataclass
class RemoteMsgEvent(IpcEvent):
    """
    Data Transfer Object for receiving a live chat message.

    Attributes:
        alias (str): The sender's alias.
        text (str): The message content.
        timestamp (Optional[str]): The message timestamp.
        type (EventType): The strict IPC event type code.
    """

    alias: str
    text: str
    timestamp: Optional[str] = None
    type: EventType = field(default=EventType.REMOTE_MSG, init=False)


@register_event(EventType.ACK)
@dataclass
class AckEvent(IpcEvent):
    """
    Data Transfer Object confirming delivery of a sent message.

    Attributes:
        msg_id (str): The unique identifier of the acknowledged message.
        text (Optional[str]): The acknowledged payload.
        type (EventType): The strict IPC event type code.
    """

    msg_id: str
    text: Optional[str] = None
    type: EventType = field(default=EventType.ACK, init=False)


@register_event(EventType.DROP_FAILED)
@dataclass
class DropFailedEvent(IpcEvent):
    """
    Data Transfer Object indicating an asynchronous drop delivery failure.

    Attributes:
        msg_id (str): The unique identifier of the failed message.
        type (EventType): The strict IPC event type code.
    """

    msg_id: str
    type: EventType = field(default=EventType.DROP_FAILED, init=False)


@register_event(EventType.CONNECTED)
@dataclass
class ConnectedEvent(IpcEvent):
    """
    Data Transfer Object indicating a successfully established Tor connection.

    Attributes:
        alias (str): The peer's alias.
        onion (Optional[str]): The peer's onion address.
        type (EventType): The strict IPC event type code.
    """

    alias: str
    onion: Optional[str] = None
    type: EventType = field(default=EventType.CONNECTED, init=False)


@register_event(EventType.DISCONNECTED)
@dataclass
class DisconnectedEvent(IpcEvent):
    """
    Data Transfer Object indicating a severed Tor connection.

    Attributes:
        alias (str): The disconnected peer's alias.
        type (EventType): The strict IPC event type code.
    """

    alias: str
    type: EventType = field(default=EventType.DISCONNECTED, init=False)


@register_event(EventType.RENAME_SUCCESS)
@dataclass
class RenameSuccessEvent(IpcEvent):
    """
    Data Transfer Object indicating a successful local alias rename.

    Attributes:
        old_alias (str): The previous alias.
        new_alias (str): The newly assigned alias.
        is_demotion (bool): True if the contact was removed from permanent storage.
        was_saved (bool): True if the contact was previously saved.
        type (EventType): The strict IPC event type code.
    """

    old_alias: str
    new_alias: str
    is_demotion: bool = False
    was_saved: bool = True
    type: EventType = field(default=EventType.RENAME_SUCCESS, init=False)


@register_event(EventType.CONTACT_REMOVED)
@dataclass
class ContactRemovedEvent(IpcEvent):
    """
    Data Transfer Object indicating the deletion of a contact.

    Attributes:
        alias (str): The alias of the removed contact.
        type (EventType): The strict IPC event type code.
    """

    alias: str
    type: EventType = field(default=EventType.CONTACT_REMOVED, init=False)


@register_event(EventType.CONNECTIONS_STATE)
@dataclass
class ConnectionsStateEvent(IpcEvent):
    """
    Data Transfer Object broadcasting the current network connection states.

    Attributes:
        active (List[str]): List of active session aliases.
        pending (List[str]): List of pending session aliases.
        contacts (List[str]): List of saved contact aliases.
        is_header (bool): Flag indicating if this is a header-state broadcast.
        type (EventType): The strict IPC event type code.
    """

    active: List[str]
    pending: List[str]
    contacts: List[str]
    is_header: bool = False
    type: EventType = field(default=EventType.CONNECTIONS_STATE, init=False)


@register_event(EventType.SWITCH_SUCCESS)
@dataclass
class SwitchSuccessEvent(IpcEvent):
    """
    Data Transfer Object confirming a successful UI focus switch.

    Attributes:
        alias (Optional[str]): The newly focused alias.
        type (EventType): The strict IPC event type code.
    """

    alias: Optional[str] = None
    type: EventType = field(default=EventType.SWITCH_SUCCESS, init=False)


# --- Transient States ---


@register_event(EventType.CONNECTION_PENDING)
@dataclass
class ConnectionPendingEvent(IpcEvent):
    """
    Data Transfer Object indicating an outbound connection is awaiting remote acceptance.

    Attributes:
        alias (Optional[str]): The target peer alias.
        type (EventType): The strict IPC event type code.
    """

    alias: Optional[str] = None
    type: EventType = field(default=EventType.CONNECTION_PENDING, init=False)


@register_event(EventType.CONNECTION_AUTO_ACCEPTED)
@dataclass
class ConnectionAutoAcceptedEvent(IpcEvent):
    """
    Data Transfer Object indicating a mutual connection was automatically accepted.

    Attributes:
        alias (Optional[str]): The target peer alias.
        type (EventType): The strict IPC event type code.
    """

    alias: Optional[str] = None
    type: EventType = field(default=EventType.CONNECTION_AUTO_ACCEPTED, init=False)


@register_event(EventType.CONNECTION_RETRY)
@dataclass
class ConnectionRetryEvent(IpcEvent):
    """
    Data Transfer Object indicating a failed connection attempt will be retried.

    Attributes:
        alias (Optional[str]): The target peer alias.
        attempt (int): The current retry attempt.
        max_retries (int): The maximum allowed retries.
        type (EventType): The strict IPC event type code.
    """

    alias: Optional[str] = None
    attempt: int = 1
    max_retries: int = 3
    type: EventType = field(default=EventType.CONNECTION_RETRY, init=False)


@register_event(EventType.CONNECTION_FAILED)
@dataclass
class ConnectionFailedEvent(IpcEvent):
    """
    Data Transfer Object indicating a final connection failure.

    Attributes:
        alias (Optional[str]): The target peer alias.
        reason (str): The specific failure reason.
        type (EventType): The strict IPC event type code.
    """

    alias: Optional[str] = None
    reason: str = ''
    type: EventType = field(default=EventType.CONNECTION_FAILED, init=False)


@register_event(EventType.INCOMING_CONNECTION)
@dataclass
class IncomingConnectionEvent(IpcEvent):
    """
    Data Transfer Object alerting the UI of an inbound connection request.

    Attributes:
        alias (Optional[str]): The requesting peer alias.
        type (EventType): The strict IPC event type code.
    """

    alias: Optional[str] = None
    type: EventType = field(default=EventType.INCOMING_CONNECTION, init=False)


@register_event(EventType.CONNECTION_REJECTED)
@dataclass
class ConnectionRejectedEvent(IpcEvent):
    """
    Data Transfer Object indicating a connection was rejected.

    Attributes:
        alias (Optional[str]): The target peer alias.
        by_remote (bool): True if the remote peer rejected the request.
        type (EventType): The strict IPC event type code.
    """

    alias: Optional[str] = None
    by_remote: bool = False
    type: EventType = field(default=EventType.CONNECTION_REJECTED, init=False)


@register_event(EventType.TIEBREAKER_REJECTED)
@dataclass
class TiebreakerRejectedEvent(IpcEvent):
    """
    Data Transfer Object indicating a mutual connection tie-breaker resulted in a local reject.

    Attributes:
        alias (Optional[str]): The target peer alias.
        type (EventType): The strict IPC event type code.
    """

    alias: Optional[str] = None
    type: EventType = field(default=EventType.TIEBREAKER_REJECTED, init=False)


@register_event(EventType.AUTO_RECONNECT_ATTEMPT)
@dataclass
class AutoReconnectAttemptEvent(IpcEvent):
    """
    Data Transfer Object indicating an automated background reconnect attempt.

    Attributes:
        alias (Optional[str]): The target peer alias.
        code (DomainCode): The translation code.
        type (EventType): The strict IPC event type code.
    """

    alias: Optional[str] = None
    code: DomainCode = NetworkCode.AUTO_RECONNECT_ATTEMPT
    type: EventType = field(default=EventType.AUTO_RECONNECT_ATTEMPT, init=False)


# --- Inbox & Drops ---


@register_event(EventType.INBOX_NOTIFICATION)
@dataclass
class InboxNotificationEvent(IpcEvent):
    """
    Data Transfer Object alerting the UI to newly arrived offline messages.

    Attributes:
        alias (Optional[str]): The sender's alias.
        count (int): Number of new messages received.
        type (EventType): The strict IPC event type code.
    """

    alias: Optional[str] = None
    count: int = 1
    type: EventType = field(default=EventType.INBOX_NOTIFICATION, init=False)


@register_event(EventType.INBOX_DATA)
@dataclass
class InboxDataEvent(IpcEvent):
    """
    Data Transfer Object carrying buffered or inbox message payloads.

    Attributes:
        messages (List[UnreadMessageEntry]): List of unread message DTOs.
        inbox_counts (Dict[str, int]): Map of aliases to their unread message counts.
        alias (Optional[str]): The target sender alias.
        is_live_flush (bool): True if flushing a headless live RAM buffer.
        type (EventType): The strict IPC event type code.
    """

    messages: List[UnreadMessageEntry] = field(default_factory=list)
    inbox_counts: Dict[str, int] = field(default_factory=dict)
    alias: Optional[str] = None
    is_live_flush: bool = False
    type: EventType = field(default=EventType.INBOX_DATA, init=False)

    def __post_init__(self) -> None:
        """
        Casts dictionary payloads to strong UnreadMessageEntry DTOs.

        Args:
            None

        Returns:
            None
        """
        if self.messages and isinstance(self.messages[0], dict):
            self.messages = [UnreadMessageEntry(**x) for x in self.messages]  # type: ignore


# --- Query Response DTOs ---


@register_event(EventType.CONTACTS_DATA)
@dataclass
class ContactsDataEvent(IpcEvent):
    """
    Data Transfer Object returning the structured address book.

    Attributes:
        saved (List[ContactEntry]): List of permanent contacts.
        discovered (List[ContactEntry]): List of temporary RAM peers.
        profile (str): The active profile name.
        type (EventType): The strict IPC event type code.
    """

    saved: List[ContactEntry]
    discovered: List[ContactEntry]
    profile: str
    type: EventType = field(default=EventType.CONTACTS_DATA, init=False)

    def __post_init__(self) -> None:
        """
        Casts dictionary payloads to strong ContactEntry DTOs.

        Args:
            None

        Returns:
            None
        """
        if self.saved and isinstance(self.saved[0], dict):
            self.saved = [ContactEntry(**x) for x in self.saved]  # type: ignore
        if self.discovered and isinstance(self.discovered[0], dict):
            self.discovered = [ContactEntry(**x) for x in self.discovered]  # type: ignore


@register_event(EventType.HISTORY_DATA)
@dataclass
class HistoryDataEvent(IpcEvent):
    """
    Data Transfer Object returning connection event history.

    Attributes:
        history (List[HistoryEntry]): List of historical event DTOs.
        profile (str): The active profile name.
        target (Optional[str]): The filtered peer alias, if queried.
        type (EventType): The strict IPC event type code.
    """

    history: List[HistoryEntry]
    profile: str
    target: Optional[str] = None
    type: EventType = field(default=EventType.HISTORY_DATA, init=False)

    def __post_init__(self) -> None:
        """
        Casts dictionary payloads to strong HistoryEntry DTOs.

        Args:
            None

        Returns:
            None
        """
        if self.history and isinstance(self.history[0], dict):
            self.history = [HistoryEntry(**x) for x in self.history]  # type: ignore


@register_event(EventType.MESSAGES_DATA)
@dataclass
class MessagesDataEvent(IpcEvent):
    """
    Data Transfer Object returning past chat payloads.

    Attributes:
        messages (List[MessageEntry]): List of message DTOs.
        target (str): The specific peer alias queried.
        type (EventType): The strict IPC event type code.
    """

    messages: List[MessageEntry]
    target: str
    type: EventType = field(default=EventType.MESSAGES_DATA, init=False)

    def __post_init__(self) -> None:
        """
        Casts dictionary payloads to strong MessageEntry DTOs.

        Args:
            None

        Returns:
            None
        """
        if self.messages and isinstance(self.messages[0], dict):
            self.messages = [MessageEntry(**x) for x in self.messages]  # type: ignore


@register_event(EventType.INBOX_COUNTS)
@dataclass
class InboxCountsEvent(IpcEvent):
    """
    Data Transfer Object returning unread message metrics.

    Attributes:
        inbox (Dict[str, int]): Dictionary mapping aliases to unread message counts.
        type (EventType): The strict IPC event type code.
    """

    inbox: Dict[str, int]
    type: EventType = field(default=EventType.INBOX_COUNTS, init=False)


@register_event(EventType.UNREAD_MESSAGES)
@dataclass
class UnreadMessagesEvent(IpcEvent):
    """
    Data Transfer Object returning all unread messages for a specific peer.

    Attributes:
        messages (List[UnreadMessageEntry]): List of unread message DTOs.
        target (str): The sender's alias.
        type (EventType): The strict IPC event type code.
    """

    messages: List[UnreadMessageEntry]
    target: str
    type: EventType = field(default=EventType.UNREAD_MESSAGES, init=False)

    def __post_init__(self) -> None:
        """
        Casts dictionary payloads to strong UnreadMessageEntry DTOs.

        Args:
            None

        Returns:
            None
        """
        if self.messages and isinstance(self.messages[0], dict):
            self.messages = [UnreadMessageEntry(**x) for x in self.messages]  # type: ignore


@register_event(EventType.ADDRESS_DATA)
@dataclass
class AddressDataEvent(IpcEvent):
    """
    Data Transfer Object returning hidden service identity data.

    Attributes:
        action (Action): The triggering command action.
        code (DomainCode): The translation code.
        profile (str): The active profile name.
        onion (str): The local Tor onion address.
        type (EventType): The strict IPC event type code.
    """

    action: Action
    code: DomainCode
    profile: str
    onion: str
    type: EventType = field(default=EventType.ADDRESS_DATA, init=False)


@register_event(EventType.PROFILES_DATA)
@dataclass
class ProfilesDataEvent(IpcEvent):
    """
    Data Transfer Object returning the available isolated profiles.

    Attributes:
        profiles (List[ProfileEntry]): List of profile DTOs.
        type (EventType): The strict IPC event type code.
    """

    profiles: List[ProfileEntry]
    type: EventType = field(default=EventType.PROFILES_DATA, init=False)

    def __post_init__(self) -> None:
        """
        Casts dictionary payloads to strong ProfileEntry DTOs.

        Args:
            None

        Returns:
            None
        """
        if self.profiles and isinstance(self.profiles[0], dict):
            self.profiles = [ProfileEntry(**x) for x in self.profiles]  # type: ignore


# --- Command Success/Error DTOs ---


@register_event(EventType.ACTION_SUCCESS)
@dataclass
class ActionSuccessEvent(IpcEvent):
    """
    Data Transfer Object indicating a generic action completed successfully.

    Attributes:
        code (DomainCode): The translation code denoting success.
        action (Optional[Action]): The triggering action.
        type (EventType): The strict IPC event type code.
    """

    code: DomainCode
    action: Optional[Action] = None
    type: EventType = field(default=EventType.ACTION_SUCCESS, init=False)


@register_event(EventType.ACTION_ERROR)
@dataclass
class ActionErrorEvent(IpcEvent):
    """
    Data Transfer Object indicating a generic action failed.

    Attributes:
        code (DomainCode): The translation code for the error.
        action (Optional[Action]): The triggering action.
        reason (Optional[str]): Specific context for the failure.
        target (Optional[str]): The associated target string, if any.
        alias (Optional[str]): The resolved alias, if any.
        type (EventType): The strict IPC event type code.
    """

    code: DomainCode
    action: Optional[Action] = None
    reason: Optional[str] = None
    target: Optional[str] = None
    alias: Optional[str] = None
    type: EventType = field(default=EventType.ACTION_ERROR, init=False)


@register_event(EventType.CONTACT_ACTION_SUCCESS)
@dataclass
class ContactActionSuccessEvent(IpcEvent):
    """
    Data Transfer Object indicating a contact mutation completed successfully.

    Attributes:
        action (Action): The triggering action.
        code (DomainCode): The translation code denoting success.
        alias (str): The affected contact alias.
        profile (Optional[str]): The active profile.
        type (EventType): The strict IPC event type code.
    """

    action: Action
    code: DomainCode
    alias: str
    profile: Optional[str] = None
    type: EventType = field(default=EventType.CONTACT_ACTION_SUCCESS, init=False)


@register_event(EventType.CONTACT_RENAMED)
@dataclass
class ContactRenamedEvent(IpcEvent):
    """
    Data Transfer Object indicating a contact was renamed.

    Attributes:
        action (Action): The triggering action.
        code (DomainCode): The translation code.
        old_alias (str): The previous alias.
        new_alias (str): The new alias.
        type (EventType): The strict IPC event type code.
    """

    action: Action
    code: DomainCode
    old_alias: str
    new_alias: str
    type: EventType = field(default=EventType.CONTACT_RENAMED, init=False)


@register_event(EventType.PROFILE_ACTION_SUCCESS)
@dataclass
class ProfileActionSuccessEvent(IpcEvent):
    """
    Data Transfer Object indicating a profile mutation completed successfully.

    Attributes:
        action (Action): The triggering action.
        code (DomainCode): The translation code.
        profile (str): The affected profile name.
        remote_tag (Optional[str]): Network routing configuration tag.
        port (Optional[int]): Target port if remote.
        type (EventType): The strict IPC event type code.
    """

    action: Action
    code: DomainCode
    profile: str
    remote_tag: Optional[str] = None
    port: Optional[int] = None
    type: EventType = field(default=EventType.PROFILE_ACTION_SUCCESS, init=False)


@register_event(EventType.TARGET_ACTION_SUCCESS)
@dataclass
class TargetActionSuccessEvent(IpcEvent):
    """
    Data Transfer Object indicating an action targeting a specific peer succeeded.

    Attributes:
        action (Action): The triggering action.
        code (DomainCode): The translation code.
        target (Optional[str]): The specific target identifier.
        profile (Optional[str]): The active profile context.
        type (EventType): The strict IPC event type code.
    """

    action: Action
    code: DomainCode
    target: Optional[str] = None
    profile: Optional[str] = None
    type: EventType = field(default=EventType.TARGET_ACTION_SUCCESS, init=False)


@register_event(EventType.SETTING_UPDATED)
@dataclass
class SettingUpdatedEvent(IpcEvent):
    """
    Data Transfer Object indicating an application setting was mutated.

    Attributes:
        action (Action): The triggering action.
        code (DomainCode): The translation code.
        key (str): The specific setting key modified.
        type (EventType): The strict IPC event type code.
    """

    action: Action
    code: DomainCode
    key: str
    type: EventType = field(default=EventType.SETTING_UPDATED, init=False)


@register_event(EventType.FALLBACK_SUCCESS)
@dataclass
class FallbackSuccessEvent(IpcEvent):
    """
    Data Transfer Object indicating live messages were successfully converted to drops.

    Attributes:
        code (DomainCode): The translation code.
        alias (str): The target peer alias.
        count (int): Number of messages converted.
        msg_ids (List[str]): List of converted message identifiers.
        action (Optional[Action]): The triggering action.
        type (EventType): The strict IPC event type code.
    """

    code: DomainCode
    alias: str
    count: int
    msg_ids: List[str]
    action: Optional[Action] = None
    type: EventType = field(default=EventType.FALLBACK_SUCCESS, init=False)


# --- Specific Asynchronous Notification DTOs ---


@register_event(EventType.MAX_CONNECTIONS_REACHED)
@dataclass
class MaxConnectionsReachedEvent(IpcEvent):
    """
    Data Transfer Object indicating the connection limit has been exhausted.

    Attributes:
        target (str): The peer whose connection was blocked.
        max_conn (int): The current system limit.
        code (DomainCode): The translation code.
        type (EventType): The strict IPC event type code.
    """

    target: str
    max_conn: int
    code: DomainCode = NetworkCode.MAX_CONNECTIONS_REACHED
    type: EventType = field(default=EventType.MAX_CONNECTIONS_REACHED, init=False)


@register_event(EventType.PEER_NOT_FOUND)
@dataclass
class PeerNotFoundEvent(IpcEvent):
    """
    Data Transfer Object indicating the specified peer could not be resolved.

    Attributes:
        target (str): The unresolvable target string.
        code (DomainCode): The translation code.
        type (EventType): The strict IPC event type code.
    """

    target: str
    code: DomainCode = ContactCode.PEER_NOT_FOUND
    type: EventType = field(default=EventType.PEER_NOT_FOUND, init=False)


@register_event(EventType.RETUNNEL_INITIATED)
@dataclass
class RetunnelInitiatedEvent(IpcEvent):
    """
    Data Transfer Object indicating circuit rotation has started for a peer.

    Attributes:
        alias (str): The target peer alias.
        code (DomainCode): The translation code.
        type (EventType): The strict IPC event type code.
    """

    alias: str
    code: DomainCode = NetworkCode.RETUNNEL_INITIATED
    type: EventType = field(default=EventType.RETUNNEL_INITIATED, init=False)


@register_event(EventType.RETUNNEL_SUCCESS)
@dataclass
class RetunnelSuccessEvent(IpcEvent):
    """
    Data Transfer Object indicating circuit rotation completed successfully.

    Attributes:
        alias (str): The target peer alias.
        code (DomainCode): The translation code.
        type (EventType): The strict IPC event type code.
    """

    alias: str
    code: DomainCode = NetworkCode.RETUNNEL_SUCCESS
    type: EventType = field(default=EventType.RETUNNEL_SUCCESS, init=False)
