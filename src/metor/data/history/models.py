"""Structured models used by the history persistence and projection layers."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from metor.data.history.codes import (
    HistoryActor,
    HistoryEvent,
    HistoryFamily,
    HistoryReasonCode,
    HistorySummaryCode,
    HistoryTrigger,
)


@dataclass(frozen=True)
class HistoryLedgerEntry:
    """Represents one raw persisted transport ledger row."""

    timestamp: str
    family: HistoryFamily
    event_code: HistoryEvent
    peer_onion: Optional[str]
    actor: HistoryActor
    trigger: Optional[HistoryTrigger]
    detail_code: Optional[HistoryReasonCode]
    detail_text: str
    flow_id: str


@dataclass(frozen=True)
class HistorySummaryEntry:
    """Represents one projected user-facing history row."""

    timestamp: str
    family: HistoryFamily
    event_code: HistorySummaryCode
    peer_onion: Optional[str]
    actor: HistoryActor
    trigger: Optional[HistoryTrigger]
    detail_code: Optional[HistoryReasonCode]
    detail_text: str
    flow_id: str


class HistoryClearOperationType(str, Enum):
    """Enumeration of history-clear outcomes independent from IPC events."""

    ALL_CLEARED = 'all_cleared'
    CLEAR_FAILED = 'clear_failed'
    TARGET_CLEARED = 'target_cleared'


@dataclass(frozen=True)
class HistoryClearResult:
    """Represents one typed history-clear result."""

    success: bool
    operation_type: HistoryClearOperationType
    target_onion: Optional[str] = None
    profile: Optional[str] = None
