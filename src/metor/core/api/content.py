"""Message content and delivery types shared across the public IPC boundary."""

from dataclasses import dataclass, field
from enum import Enum


class Delivery(str, Enum):
    """How a message is delivered and retained."""

    LIVE = 'live'
    DROP = 'drop'


class ContentType(str, Enum):
    """Content kinds implemented by this release."""

    TEXT = 'text'


@dataclass(frozen=True)
class TextContent:
    """UTF-8 text message content.

    Voice and file content will use blob references once a binary transfer
    protocol exists; binary data must not be embedded in NDJSON.
    """

    text: str
    type: ContentType = field(default=ContentType.TEXT, init=False)


MessageContent = TextContent
