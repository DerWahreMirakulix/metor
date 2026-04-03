"""Structured models used by the history persistence and projection layers."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class HistoryLedgerEntry:
    """Represents one raw persisted transport ledger row."""

    timestamp: str
    family: str
    event_code: str
    peer_onion: Optional[str]
    actor: str
    trigger: Optional[str]
    detail_code: Optional[str]
    detail_text: str
    flow_id: str


@dataclass(frozen=True)
class HistorySummaryEntry:
    """Represents one projected user-facing history row."""

    timestamp: str
    family: str
    event_code: str
    peer_onion: Optional[str]
    actor: str
    trigger: Optional[str]
    detail_code: Optional[str]
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
