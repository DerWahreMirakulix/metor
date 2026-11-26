"""Message enums shared across the IPC boundary."""

from enum import Enum


class MessageDirectionCode(str, Enum):
    """Enumeration of message direction codes exposed by the IPC API."""

    IN = 'in'
    OUT = 'out'


class MessageStatusCode(str, Enum):
    """Enumeration of message lifecycle status codes exposed by the IPC API."""

    PENDING = 'pending'
    DELIVERED = 'delivered'
    UNREAD = 'unread'
    READ = 'read'
    DRAFT = 'draft'


class MessageOperationReason(str, Enum):
    """Machine-readable rejection reasons for message operations."""

    INVALID_SELECTION = 'invalid_selection'
    WRONG_PEER = 'wrong_peer'
    NOT_PENDING_LIVE = 'not_pending_live'
    NOT_DROP = 'not_drop'
    PENDING_DELIVERY = 'pending_delivery'
    NOT_FOUND = 'not_found'
    NO_RECOVERY = 'no_recovery'
    COUNT_LIMIT = 'count_limit'
    BYTE_LIMIT = 'byte_limit'
    OUTBOUND_PENDING_LIVE = 'outbound_pending_live'
    ACTIVE_LIVE_CONTEXT = 'active_live_context'
    AMBIGUOUS_IDENTITY = 'ambiguous_identity'
    NOT_FINALIZED = 'not_finalized'
    INVALID_RANGE = 'invalid_range'
    UNSUPPORTED_CONTENT = 'unsupported_content'
    MEDIA_LIMIT = 'media_limit'
    MALFORMED_CHUNK = 'malformed_chunk'
    STALE_CAPTURE = 'stale_capture'
    PERSISTENCE_FAILED = 'persistence_failed'
