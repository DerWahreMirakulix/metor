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
