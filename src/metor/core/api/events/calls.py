"""Call lifecycle and exact-owner ephemeral audio response DTOs."""

from dataclasses import dataclass, field

# Local Package Imports
from metor.core.api.base import IpcEvent
from metor.core.api.calls import CallAudioFrame, CallInfo, CallReason
from metor.core.api.codes import EventType
from metor.core.api.registry import register_event


@register_event(EventType.CALL_STATE)
@dataclass
class CallStateEvent(IpcEvent):
    """Reports one lifecycle transition with privacy and ownership projected per client."""

    call: CallInfo = field(default_factory=CallInfo)
    event_type: EventType = field(default=EventType.CALL_STATE, init=False)


@register_event(EventType.CALLS_STATE)
@dataclass
class CallsStateEvent(IpcEvent):
    """Returns bounded current and recent Call metadata visible to the requesting client."""

    calls: list[CallInfo] = field(default_factory=list)
    event_type: EventType = field(default=EventType.CALLS_STATE, init=False)


@register_event(EventType.CALL_AUDIO_SENT)
@dataclass
class CallAudioSentEvent(IpcEvent):
    """Acknowledges local frame admission and the next sequence, without promising playback."""

    call_id: str = ''
    next_sequence: int = 0
    event_type: EventType = field(default=EventType.CALL_AUDIO_SENT, init=False)


@register_event(EventType.CALL_AUDIO)
@dataclass
class CallAudioEvent(IpcEvent):
    """Transfers fresh received frames to the exact owner, removing them from Core's queue."""

    call_id: str = ''
    frames: list[CallAudioFrame] = field(default_factory=list)
    event_type: EventType = field(default=EventType.CALL_AUDIO, init=False)


@register_event(EventType.CALL_REJECTED)
@dataclass
class CallRejectedEvent(IpcEvent):
    """Rejects an exact Call operation with a domain reason and no new media authority."""

    call_id: str = ''
    reason: CallReason = CallReason.INVALID_STATE
    event_type: EventType = field(default=EventType.CALL_REJECTED, init=False)
