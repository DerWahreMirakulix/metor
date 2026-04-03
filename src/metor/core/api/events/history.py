"""History event DTOs for projected and raw transport history."""

from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Optional

from metor.core.api.base import IpcEvent
from metor.core.api.codes import EventType

# Local Package Imports
from metor.core.api.events.shared import NestedEntryCastingMixin
from metor.core.api.registry import register_event


@dataclass
class HistoryEntry:
    """Represents one summary or raw history row across the IPC boundary."""

    timestamp: str
    family: str
    event_code: str
    peer_onion: Optional[str]
    actor: str
    trigger: Optional[str]
    detail_code: Optional[str]
    detail_text: str
    flow_id: str
    alias: Optional[str] = None


@dataclass
class BaseHistoryDataEvent(NestedEntryCastingMixin, IpcEvent):
    """Shared payload for summary and raw history transport events."""

    entries: List[HistoryEntry]
    profile: str
    alias: Optional[str] = None
    peer_onion: Optional[str] = None
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'entries': HistoryEntry,
    }


@register_event(EventType.HISTORY_DATA)
@dataclass
class HistoryDataEvent(BaseHistoryDataEvent):
    """Returns projected user-facing history rows."""

    event_type: EventType = field(default=EventType.HISTORY_DATA, init=False)


@register_event(EventType.HISTORY_RAW_DATA)
@dataclass
class HistoryRawDataEvent(BaseHistoryDataEvent):
    """Returns raw transport history ledger rows."""

    event_type: EventType = field(default=EventType.HISTORY_RAW_DATA, init=False)
