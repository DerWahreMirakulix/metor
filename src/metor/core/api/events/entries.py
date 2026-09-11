"""Shared IPC entry DTOs for nested event payloads."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, TypeVar

from metor.core.api.codes import (
    ConnectionActor,
    ConnectionOrigin,
    ConnectionReasonCode,
    MessageDirectionCode,
    MessageStatusCode,
    PendingConnectionReasonCode,
)
from metor.core.api.content import (
    ContentType,
    Delivery,
    MessageContent,
    TextContent,
    VoiceContent,
)


EnumT = TypeVar('EnumT', bound=Enum)


def _coerce_enum(enum_type: type[EnumT], value: object) -> EnumT:
    """Coerces one string-backed DTO field to its target enum type."""

    if isinstance(value, enum_type):
        return value
    return enum_type(value)


def _coerce_content(value: MessageContent | dict[str, object]) -> MessageContent:
    """Casts one JSON-shaped content payload by its discriminator.

    Args:
        value (MessageContent | dict[str, object]): Content DTO or decoded object.

    Returns:
        MessageContent: Typed content DTO.
    """
    if not isinstance(value, dict):
        return value
    if value.get('type') == ContentType.VOICE.value:
        duration = value.get('duration_ms')
        return VoiceContent(
            blob_id=str(value['blob_id']),
            codec=str(value['codec']),
            size_bytes=int(str(value['size_bytes'])),
            duration_ms=int(str(duration)) if duration is not None else None,
        )
    return TextContent(text=str(value['text']))


@dataclass
class ContactEntry:
    """Represents a structured contact entry."""

    alias: str
    onion: str
    saved: bool = True


@dataclass
class MessageEntry:
    """Represents a stored chat message."""

    direction: MessageDirectionCode
    status: MessageStatusCode
    delivery: Delivery
    content: MessageContent
    timestamp: str
    msg_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Coerces string-backed direction and status fields to their typed enum equivalents."""
        self.direction = _coerce_enum(MessageDirectionCode, self.direction)
        self.status = _coerce_enum(MessageStatusCode, self.status)
        self.delivery = _coerce_enum(Delivery, self.delivery)
        if isinstance(self.content, dict):
            self.content = _coerce_content(self.content)


@dataclass
class RetainedMessageEntry:
    """Identifies one retained item without exposing its content or storage path."""

    onion: str
    alias: str
    direction: MessageDirectionCode
    delivery: Delivery
    status: MessageStatusCode
    content_type: ContentType
    msg_id: str
    finalized: bool
    size_bytes: int = 0
    codec: Optional[str] = None
    duration_ms: Optional[int] = None

    def __post_init__(self) -> None:
        """Coerces serialized enum fields into their typed representations.

        Args:
            None

        Returns:
            None
        """
        self.direction = _coerce_enum(MessageDirectionCode, self.direction)
        self.delivery = _coerce_enum(Delivery, self.delivery)
        self.status = _coerce_enum(MessageStatusCode, self.status)
        self.content_type = _coerce_enum(ContentType, self.content_type)


@dataclass
class UnreadMessageEntry:
    """Represents one unread message awaiting explicit consume."""

    timestamp: str
    delivery: Delivery
    content: MessageContent
    msg_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Casts JSON-shaped nested content to its typed DTO.

        Args:
            None

        Returns:
            None
        """
        self.delivery = _coerce_enum(Delivery, self.delivery)
        if isinstance(self.content, dict):
            self.content = _coerce_content(self.content)


@dataclass
class PendingConnectionEntry:
    """Represents one retained inbound live request in the startup snapshot."""

    alias: str
    onion: Optional[str]
    origin: ConnectionOrigin
    reason: PendingConnectionReasonCode
    expires_at: Optional[str] = None

    def __post_init__(self) -> None:
        """Coerces string-backed origin and reason values to typed enums."""
        self.origin = _coerce_enum(ConnectionOrigin, self.origin)
        self.reason = _coerce_enum(PendingConnectionReasonCode, self.reason)


@dataclass
class UnreadInboxSummaryEntry:
    """Represents one peer unread summary in the chat startup snapshot."""

    alias: str
    onion: Optional[str]
    total_unread: int
    drop_unread: int
    live_unread: int


@dataclass
class LiveContextEntry:
    """Represents canonical per-peer LIVE state in an aggregate snapshot."""

    alias: str
    onion: str
    saved: bool
    session_state: str
    unseen_count: int = 0
    pending_outbound_count: int = 0
    recovery_eligible: bool = False
    disconnect_actor: Optional[ConnectionActor] = None
    disconnect_reason: Optional[ConnectionReasonCode] = None

    def __post_init__(self) -> None:
        """Coerces optional disconnect fields to their public enums."""
        if self.disconnect_actor is not None:
            self.disconnect_actor = _coerce_enum(ConnectionActor, self.disconnect_actor)
        if self.disconnect_reason is not None:
            self.disconnect_reason = _coerce_enum(
                ConnectionReasonCode, self.disconnect_reason
            )


@dataclass
class DropConversationSummaryEntry:
    """Represents a content-free DROP conversation summary."""

    alias: str
    onion: str
    unread_count: int = 0


@dataclass
class ProfileEntry:
    """Represents one profile in the profile list response."""

    name: str
    is_active: bool
    is_remote: bool
    port: Optional[int]


@dataclass
class SettingSnapshotEntry:
    """
    Represents one settings/config snapshot row.

    Attributes:
        key (str): The fully-qualified settings or config key.
        value (str): The rendered effective value.
        source (str): The source label for the rendered value.
        category (str): The presenter grouping label.
    """

    key: str
    value: str
    source: str
    category: str
