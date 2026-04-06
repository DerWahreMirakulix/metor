"""History event DTOs for projected and raw transport history."""

from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Dict, Optional, Sequence, TypeVar

from metor.core.api.base import IpcEvent
from metor.core.api.codes import EventType
from metor.core.api.codes.history import (
    HistoryEntryActor,
    HistoryEntryFamily,
    HistoryEntryReasonCode,
    HistoryEntryTrigger,
    HistoryRawEventCode,
    HistorySummaryEventCode,
)

# Local Package Imports
from metor.core.api.events.shared import NestedEntryCastingMixin
from metor.core.api.registry import register_event


EnumT = TypeVar('EnumT', bound=Enum)


def _coerce_enum(enum_type: type[EnumT], value: EnumT | str) -> EnumT:
    """Coerces a string-backed value to its target enum type."""

    if isinstance(value, enum_type):
        return value
    return enum_type(value)


def _coerce_optional_enum(
    enum_type: type[EnumT],
    value: Optional[EnumT | str],
) -> Optional[EnumT]:
    """Coerces an optional string-backed value to its target enum type."""

    if value is None:
        return None
    return _coerce_enum(enum_type, value)


class _HistoryEntryCastingMixin:
    """Casts shared string-backed history entry fields to strict enums."""

    family: HistoryEntryFamily
    actor: HistoryEntryActor
    trigger: Optional[HistoryEntryTrigger]
    detail_code: Optional[HistoryEntryReasonCode]

    def _cast_common_fields(self) -> None:
        self.family = _coerce_enum(HistoryEntryFamily, self.family)
        self.actor = _coerce_enum(HistoryEntryActor, self.actor)
        self.trigger = _coerce_optional_enum(HistoryEntryTrigger, self.trigger)
        self.detail_code = _coerce_optional_enum(
            HistoryEntryReasonCode,
            self.detail_code,
        )


@dataclass
class SummaryHistoryEntry(_HistoryEntryCastingMixin):
    """Represents one projected history row across the IPC boundary."""

    timestamp: str
    family: HistoryEntryFamily
    event_code: HistorySummaryEventCode
    peer_onion: Optional[str]
    actor: HistoryEntryActor
    trigger: Optional[HistoryEntryTrigger]
    detail_code: Optional[HistoryEntryReasonCode]
    detail_text: str
    flow_id: str
    alias: Optional[str] = None

    def __post_init__(self) -> None:
        self._cast_common_fields()
        self.event_code = _coerce_enum(HistorySummaryEventCode, self.event_code)


@dataclass
class RawHistoryEntry(_HistoryEntryCastingMixin):
    """Represents one raw history row across the IPC boundary."""

    timestamp: str
    family: HistoryEntryFamily
    event_code: HistoryRawEventCode
    peer_onion: Optional[str]
    actor: HistoryEntryActor
    trigger: Optional[HistoryEntryTrigger]
    detail_code: Optional[HistoryEntryReasonCode]
    detail_text: str
    flow_id: str
    alias: Optional[str] = None

    def __post_init__(self) -> None:
        self._cast_common_fields()
        self.event_code = _coerce_enum(HistoryRawEventCode, self.event_code)


@dataclass
class BaseHistoryDataEvent(NestedEntryCastingMixin, IpcEvent):
    """Shared payload for summary and raw history transport events."""

    entries: Sequence[object]
    profile: str
    alias: Optional[str] = None
    peer_onion: Optional[str] = None


@register_event(EventType.HISTORY_DATA)
@dataclass
class HistoryDataEvent(BaseHistoryDataEvent):
    """Returns projected user-facing history rows."""

    entries: Sequence[SummaryHistoryEntry]
    event_type: EventType = field(default=EventType.HISTORY_DATA, init=False)
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'entries': SummaryHistoryEntry,
    }


@register_event(EventType.HISTORY_RAW_DATA)
@dataclass
class HistoryRawDataEvent(BaseHistoryDataEvent):
    """Returns raw transport history ledger rows."""

    entries: Sequence[RawHistoryEntry]
    event_type: EventType = field(default=EventType.HISTORY_RAW_DATA, init=False)
    _nested_entry_types: ClassVar[Dict[str, type[object]]] = {
        'entries': RawHistoryEntry,
    }
