"""Message content and delivery types shared across the public IPC boundary."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Union
import json
import re

from metor.utils import Constants


_MESSAGE_ID_PATTERN = re.compile(
    rf'^[A-Za-z0-9][A-Za-z0-9._:-]{{0,{Constants.MESSAGE_ID_MAX_CHARS - 1}}}$'
)


def is_valid_message_id(msg_id: str) -> bool:
    """Checks the bounded wire/storage identity grammar."""
    return _MESSAGE_ID_PATTERN.fullmatch(msg_id) is not None


class Delivery(str, Enum):
    """How a message is delivered and retained."""

    LIVE = 'live'
    DROP = 'drop'


class ContentType(str, Enum):
    """Content kinds implemented by this release."""

    TEXT = 'text'
    VOICE = 'voice'


@dataclass(frozen=True)
class TextContent:
    """UTF-8 text message content.

    Voice and file content will use blob references once a binary transfer
    protocol exists; binary data must not be embedded in NDJSON.
    """

    text: str
    type: ContentType = field(default=ContentType.TEXT, init=False)


@dataclass(frozen=True)
class VoiceContent:
    """Metadata referencing one bounded binary Voice object."""

    blob_id: str
    codec: str
    size_bytes: int
    duration_ms: int | None = None
    type: ContentType = field(default=ContentType.VOICE, init=False)


MessageContent = Union[TextContent, VoiceContent]


def deserialize_content(content_type: ContentType, payload: str) -> MessageContent:
    """Deserializes canonical persisted content metadata.

    Args:
        content_type (ContentType): Stored discriminator.
        payload (str): Text body or compact Voice metadata JSON.

    Returns:
        MessageContent: Typed content DTO.
    """
    if content_type is ContentType.TEXT:
        return TextContent(payload)
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError('Invalid Voice metadata.')
    duration = decoded.get('duration_ms')
    return VoiceContent(
        blob_id=str(decoded['blob_id']),
        codec=str(decoded['codec']),
        size_bytes=int(decoded['size_bytes']),
        duration_ms=int(duration) if duration is not None else None,
    )
