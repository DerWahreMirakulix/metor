"""Typed result events for local profile lifecycle operations."""

from dataclasses import dataclass, field
from typing import Dict

# Local Package Imports
from metor.core.api.base import IpcEvent, JsonValue
from metor.core.api.codes import EventType, ProfileOperationCode
from metor.core.api.registry import register_event


@register_event(EventType.PROFILE_OPERATION_RESULT)
@dataclass
class ProfileOperationResultEvent(IpcEvent):
    """Carries one structured local profile-operation result over IPC."""

    success: bool
    operation_type: ProfileOperationCode
    params: Dict[str, JsonValue]
    event_type: EventType = field(
        default=EventType.PROFILE_OPERATION_RESULT,
        init=False,
    )
