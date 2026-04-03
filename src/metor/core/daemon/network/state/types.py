"""Shared type definitions for network state tracking."""

from enum import Enum


class PendingConnectionReason(str, Enum):
    """Describes why an inbound live socket currently remains pending."""

    USER_ACCEPT = 'user_accept'
    CONSUMER_ABSENT = 'consumer_absent'
