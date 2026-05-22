"""Shared IPC entry DTOs for nested event payloads."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, TypeVar

from metor.core.api.codes import (
    ConnectionOrigin,
    MessageDirectionCode,
    MessageStatusCode,
    PendingConnectionReasonCode,
)


EnumT = TypeVar('EnumT', bound=Enum)


def _coerce_enum(enum_type: type[EnumT], value: object) -> EnumT:
    """Coerces one string-backed DTO field to its target enum type."""

    if isinstance(value, enum_type):
        return value
    return enum_type(value)


@dataclass
class ContactEntry:
    """Represents a structured contact entry."""

    alias: str
    onion: str


@dataclass
class MessageEntry:
    """Represents a stored chat message."""

    direction: MessageDirectionCode
    status: MessageStatusCode
    payload: str
    timestamp: str

    def __post_init__(self) -> None:
        """Coerces string-backed direction and status fields to their typed enum equivalents."""
        self.direction = _coerce_enum(MessageDirectionCode, self.direction)
        self.status = _coerce_enum(MessageStatusCode, self.status)


@dataclass
class UnreadMessageEntry:
    """Represents one unread message awaiting explicit consume."""

    timestamp: str
    payload: str
    is_drop: bool


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
