"""Module defining the data models and render roles for the Chat UI."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from metor.ui.models import AliasPolicy, StatusTone


class ChatMessageType(str, Enum):
    """Enumeration for the different visual routing roles in chat."""

    STATUS = 'status'
    RAW = 'raw'
    SELF = 'self'
    REMOTE = 'remote'


@dataclass
class ChatLine:
    """Strongly typed data object representing a single rendered line in the UI."""

    text: str
    msg_type: ChatMessageType
    tone: Optional[StatusTone] = None
    alias: Optional[str] = None
    peer_onion: Optional[str] = None
    alias_policy: AliasPolicy = AliasPolicy.NONE
    timestamp: Optional[str] = None
    is_pending: bool = False
    msg_id: Optional[str] = None
    is_drop: bool = False
    is_failed: bool = False
