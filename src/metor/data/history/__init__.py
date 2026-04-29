"""Facade exports for history persistence and projection."""

from typing import TYPE_CHECKING

from metor.data.history.codes import (
    HistoryActor,
    HistoryEvent,
    HistoryFamily,
    HistoryReasonCode,
    HistorySummaryCode,
    HistoryTrigger,
)
from metor.data.history.models import (
    HistoryClearOperationType,
    HistoryClearResult,
    HistoryLedgerEntry,
    HistorySummaryEntry,
)

if TYPE_CHECKING:
    from metor.data.history.manager import HistoryManager


__all__ = [
    'HistoryActor',
    'HistoryClearOperationType',
    'HistoryClearResult',
    'HistoryEvent',
    'HistoryFamily',
    'HistoryLedgerEntry',
    'HistoryManager',
    'HistoryReasonCode',
    'HistorySummaryCode',
    'HistorySummaryEntry',
    'HistoryTrigger',
]


def __getattr__(name: str) -> object:
    """
    Lazily resolves heavy facade exports to avoid package import cycles.

    Args:
        name (str): The requested export name.

    Raises:
        AttributeError: If the export is unknown.

    Returns:
        object: The resolved export.
    """
    if name == 'HistoryManager':
        from metor.data.history.manager import HistoryManager

        return HistoryManager

    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
