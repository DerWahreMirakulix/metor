"""Typed message-domain models and enums for the persistence service."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MessageStatus(str, Enum):
    """Represents the delivery and consume status of a persisted message."""

    PENDING = 'pending'
    DELIVERED = 'delivered'
    UNREAD = 'unread'
    READ = 'read'


class MessageDirection(str, Enum):
    """Represents the flow direction of a message."""

    IN = 'in'
    OUT = 'out'


class MessageType(str, Enum):
    """Represents the transport role of a persisted message payload."""

    TEXT = 'text'
    DROP_TEXT = 'drop_text'
    LIVE_TEXT = 'live_text'


@dataclass(frozen=True)
class QueuedMessageResult:
    """Represents the result of a message queue operation."""

    row_id: int
    was_duplicate: bool = False


@dataclass(frozen=True)
class StoredMessageRecord:
    """Represents one persisted chat-history row."""

    direction: str
    status: str
    payload: str
    timestamp: str


class MessageClearOperationType(str, Enum):
    """Enumeration of message-clear outcomes independent from IPC events."""

    ALL_CLEARED = 'all_cleared'
    CLEAR_FAILED = 'clear_failed'
    NON_CONTACTS_ALL_CLEARED = 'non_contacts_all_cleared'
    NON_CONTACTS_TARGET_CLEARED = 'non_contacts_target_cleared'
    TARGET_CLEARED = 'target_cleared'


@dataclass(frozen=True)
class MessageClearResult:
    """Represents one typed message-clear result."""

    success: bool
    operation_type: MessageClearOperationType
    target_onion: Optional[str] = None
    profile: Optional[str] = None
