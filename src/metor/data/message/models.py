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
    DRAFT = 'draft'


class MessageDirection(str, Enum):
    """Represents the flow direction of a message."""

    IN = 'in'
    OUT = 'out'


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
    msg_id: str
    content_type: str


@dataclass(frozen=True)
class PendingLiveRecord:
    """Represents one durable outbound LIVE item eligible for replay/fallback."""

    receipt_id: int
    peer_onion: str
    content_type: str
    payload: str
    msg_id: str
    timestamp: str


@dataclass(frozen=True)
class InboundVoiceRecord:
    """Represents one crash-safe inbound Voice spool item."""

    receipt_id: int
    peer_onion: str
    delivery: str
    payload: str
    msg_id: str
    timestamp: str
    retained_bytes: int
    status: str


@dataclass(frozen=True)
class VoicePayloadRecord:
    """Represents one exact-direction Voice payload ownership record."""

    peer_onion: str
    direction: MessageDirection
    delivery: str
    payload: str
    msg_id: str
    status: str


@dataclass(frozen=True)
class RetainedMessageRecord:
    """Content-free descriptor for one durably retained logical message."""

    peer_onion: str
    direction: MessageDirection
    delivery: str
    content_type: str
    msg_id: str
    status: str
    finalized: bool
    retained_bytes: int
    codec: Optional[str] = None
    duration_ms: Optional[int] = None


@dataclass(frozen=True)
class RetainedMessagePage:
    """One stable page of retained-message descriptors."""

    messages: list[RetainedMessageRecord]
    next_cursor: Optional[str]
    inventory_version: str


class MessageDeleteOutcome(str, Enum):
    """Domain outcomes for local single-message deletion."""

    DELETED = 'deleted'
    NOT_FOUND = 'not_found'
    NOT_DROP = 'not_drop'
    PENDING_DELIVERY = 'pending_delivery'
    AMBIGUOUS_IDENTITY = 'ambiguous_identity'


class InboundDropOutcome(str, Enum):
    """Results for same-identity inbound DROP durability transitions."""

    CREATED = 'created'
    DUPLICATE = 'duplicate'
    PROMOTED = 'promoted'
    CONFLICT = 'conflict'
    LIMIT = 'limit'


class PendingLiveAdmission(str, Enum):
    """Atomic profile-wide admission results for outbound LIVE content."""

    ACCEPTED = 'accepted'
    DUPLICATE = 'duplicate'
    COUNT_LIMIT = 'count_limit'
    BYTE_LIMIT = 'byte_limit'


@dataclass(frozen=True)
class UnreadInboxSummaryRecord:
    """Represents one peer unread-summary row for chat startup rendering."""

    contact_onion: str
    total_unread: int
    drop_unread: int
    live_unread: int


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
