"""
Module defining the data models and enumerations for the Chat UI.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class ChatMessageType(str, Enum):
    """Enumeration for the different visual routing types of chat messages."""

    INFO = 'info'
    SYSTEM = 'system'
    RAW = 'raw'
    SELF = 'self'
    REMOTE = 'remote'


@dataclass
class ChatLine:
    """Strongly typed data object representing a single rendered line in the UI."""

    text: str
    msg_type: ChatMessageType
    alias: Optional[str] = None
    is_pending: bool = False
    msg_id: Optional[str] = None
    is_drop: bool = False
