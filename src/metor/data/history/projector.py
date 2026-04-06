"""Projects raw history ledger rows into concise user-facing summary rows."""

from typing import List, Optional, Sequence

# Local Package Imports
from metor.data.history.codes import (
    HistoryEvent,
    HistoryReasonCode,
    HistorySummaryCode,
    HistoryTrigger,
)
from metor.data.history.models import HistoryLedgerEntry, HistorySummaryEntry


class HistoryProjector:
    """Converts raw transport ledger rows into compact summary history."""

    @staticmethod
    def _map_summary_code(
        entry: HistoryLedgerEntry,
    ) -> Optional[HistorySummaryCode]:
        """
        Maps one raw ledger row to its projected summary code.

        Args:
            entry (HistoryLedgerEntry): The raw ledger row.

        Returns:
            Optional[HistorySummaryCode]: The projected summary code, or None if the row is raw-only noise.
        """
        event_code: HistoryEvent = entry.event_code
        detail_code: Optional[HistoryReasonCode] = entry.detail_code

        if event_code is HistoryEvent.REQUESTED:
            if entry.trigger in {
                HistoryTrigger.AUTO_RECONNECT,
                HistoryTrigger.RETUNNEL,
            }:
                return None
            return HistorySummaryCode.CONNECTION_REQUESTED

        if event_code is HistoryEvent.CONNECTED:
            return HistorySummaryCode.CONNECTED

        if event_code is HistoryEvent.REJECTED:
            if detail_code in {
                HistoryReasonCode.MUTUAL_TIEBREAKER_LOSER,
                HistoryReasonCode.DUPLICATE_INCOMING_CONNECTED,
                HistoryReasonCode.DUPLICATE_INCOMING_PENDING,
            }:
                return None
            return HistorySummaryCode.CONNECTION_REJECTED

        if event_code is HistoryEvent.DISCONNECTED:
            return HistorySummaryCode.DISCONNECTED

        if event_code is HistoryEvent.CONNECTION_LOST:
            if detail_code in {
                HistoryReasonCode.LATE_ACCEPTANCE_TIMEOUT,
                HistoryReasonCode.PENDING_ACCEPTANCE_EXPIRED,
            }:
                return HistorySummaryCode.PENDING_EXPIRED
            if detail_code in {
                HistoryReasonCode.RETRY_EXHAUSTED,
                HistoryReasonCode.RETUNNEL_PENDING_CONNECTION_MISSING,
                HistoryReasonCode.OUTBOUND_ATTEMPT_REJECTED,
                HistoryReasonCode.OUTBOUND_ATTEMPT_CLOSED_BEFORE_ACCEPTANCE,
            }:
                return HistorySummaryCode.CONNECTION_FAILED
            return HistorySummaryCode.CONNECTION_LOST

        if event_code is HistoryEvent.RETUNNEL_INITIATED:
            return HistorySummaryCode.RETUNNEL_INITIATED

        if event_code is HistoryEvent.RETUNNEL_SUCCEEDED:
            return HistorySummaryCode.RETUNNEL_SUCCEEDED

        if event_code is HistoryEvent.QUEUED:
            return HistorySummaryCode.DROP_QUEUED

        if event_code is HistoryEvent.SENT:
            return HistorySummaryCode.DROP_SENT

        if event_code is HistoryEvent.RECEIVED:
            return HistorySummaryCode.DROP_RECEIVED

        if event_code is HistoryEvent.FAILED:
            return HistorySummaryCode.DROP_FAILED

        return None

    @staticmethod
    def project(entries: Sequence[HistoryLedgerEntry]) -> List[HistorySummaryEntry]:
        """
        Projects raw transport ledger rows into concise summary entries.

        Args:
            entries (Sequence[HistoryLedgerEntry]): Raw history rows ordered newest-first.

        Returns:
            List[HistorySummaryEntry]: The projected summary rows ordered newest-first.
        """
        projected: List[HistorySummaryEntry] = []
        for entry in entries:
            summary_code: Optional[HistorySummaryCode] = (
                HistoryProjector._map_summary_code(entry)
            )
            if summary_code is None:
                continue

            projected.append(
                HistorySummaryEntry(
                    timestamp=entry.timestamp,
                    family=entry.family,
                    event_code=summary_code,
                    peer_onion=entry.peer_onion,
                    actor=entry.actor,
                    trigger=entry.trigger,
                    detail_code=entry.detail_code,
                    detail_text=entry.detail_text,
                    flow_id=entry.flow_id,
                )
            )

        return projected
