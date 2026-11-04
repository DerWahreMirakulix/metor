"""Public Voice producer lease results with no local storage paths or keys."""

from dataclasses import dataclass, field

# Local Package Imports
from ..base import IpcEvent
from ..codes import EventType, MessageOperationReason
from ..registry import register_event


@register_event(EventType.VOICE_OWNER_REGISTERED)
@dataclass(repr=False)
class VoiceOwnerRegisteredEvent(IpcEvent):
    """Grants one connection-bound disposable staging owner for this runtime."""

    owner_token: str = ''
    event_type: EventType = field(default=EventType.VOICE_OWNER_REGISTERED, init=False)


@register_event(EventType.VOICE_OWNER_RELEASED)
@dataclass
class VoiceOwnerReleasedEvent(IpcEvent):
    """Revokes an owner; remaining cleanup is durably tracked and retried by Core."""

    cleanup_pending: bool = False
    event_type: EventType = field(default=EventType.VOICE_OWNER_RELEASED, init=False)


@register_event(EventType.VOICE_OWNER_REJECTED)
@dataclass
class VoiceOwnerRejectedEvent(IpcEvent):
    """Rejects unsupported or stale owner operations without claiming cleanup."""

    reason: MessageOperationReason = MessageOperationReason.STALE_CAPTURE
    event_type: EventType = field(default=EventType.VOICE_OWNER_REJECTED, init=False)
