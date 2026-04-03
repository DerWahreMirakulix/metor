"""Shared IPC entry DTOs for nested event payloads."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ContactEntry:
    """Represents a structured contact entry."""

    alias: str
    onion: str


@dataclass
class MessageEntry:
    """Represents a stored chat message."""

    direction: str
    status: str
    payload: str
    timestamp: str


@dataclass
class UnreadMessageEntry:
    """Represents one unread message awaiting explicit consume."""

    timestamp: str
    payload: str
    is_drop: bool


@dataclass
class ProfileEntry:
    """Represents one profile in the profile list response."""

    name: str
    is_active: bool
    is_remote: bool
    port: Optional[int]
