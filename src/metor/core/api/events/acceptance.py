"""Explicit local text acceptance, distinct from remote delivery acknowledgement."""

from dataclasses import dataclass, field
from typing import Optional

# Local Package Imports
from ..base import IpcEvent
from ..codes import (
    EventType,
    MessageOperationReason,
    MessageDirectionCode,
    MessageStatusCode,
)
from ..content import Delivery
from ..registry import register_event


@register_event(EventType.TEXT_ACCEPTED)
@dataclass
class TextAcceptedEvent(IpcEvent):
    """Confirms durable local text admission without claiming peer delivery."""

    onion: str = ''
    msg_id: str = ''
    delivery: Delivery = Delivery.LIVE
    event_type: EventType = field(default=EventType.TEXT_ACCEPTED, init=False)


@register_event(EventType.TEXT_REJECTED)
@dataclass
class TextRejectedEvent(IpcEvent):
    """Rejects a local text admission without treating resource pressure as unknown."""

    onion: str = ''
    msg_id: str = ''
    reason: MessageOperationReason = MessageOperationReason.INVALID_SELECTION
    event_type: EventType = field(default=EventType.TEXT_REJECTED, init=False)


@register_event(EventType.MESSAGE_OUTCOME)
@dataclass
class MessageOutcomeEvent(IpcEvent):
    """Returns content-free receipt facts; absence does not prove non-delivery."""

    onion: str = ''
    msg_id: str = ''
    direction: MessageDirectionCode = MessageDirectionCode.OUT
    delivery: Optional[Delivery] = None
    status: Optional[MessageStatusCode] = None
    archive_available: Optional[bool] = None
    event_type: EventType = field(default=EventType.MESSAGE_OUTCOME, init=False)
