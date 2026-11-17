"""Authoritative protected GUI preference results and explicit rejections."""

from dataclasses import dataclass, field

# Local Package Imports
from ..base import IpcEvent
from ..codes import EventType
from ..preferences import GuiPreferences, GuiPreferenceFailure
from ..registry import register_event


@register_event(EventType.GUI_PREFERENCES)
@dataclass
class GuiPreferencesEvent(IpcEvent):
    """Returns current protected preferences and the stable owning profile ID."""

    profile_instance_id: str = ''
    preferences_revision: int = 0
    preferences: GuiPreferences = field(default_factory=GuiPreferences)
    event_type: EventType = field(default=EventType.GUI_PREFERENCES, init=False)


@register_event(EventType.GUI_PREFERENCES_REJECTED)
@dataclass
class GuiPreferencesRejectedEvent(IpcEvent):
    """Rejects a policy update without optimistic mutation or profile disclosure."""

    reason: GuiPreferenceFailure = GuiPreferenceFailure.UNAVAILABLE
    event_type: EventType = field(
        default=EventType.GUI_PREFERENCES_REJECTED, init=False
    )
