"""Regression tests for the typed history DTO and projection contract."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import (
    HistoryDataEvent,
    HistoryEntryActor,
    HistoryEntryFamily,
    HistoryEntryReasonCode,
    HistoryRawDataEvent,
    HistoryRawEventCode,
    HistorySummaryEventCode,
    RawHistoryEntry,
    SummaryHistoryEntry,
)
from metor.data.history import (
    HistoryActor,
    HistoryEvent,
    HistoryFamily,
    HistoryLedgerEntry,
    HistoryReasonCode,
    HistorySummaryCode,
    HistoryTrigger,
)
from metor.data.history.projector import HistoryProjector
from metor.ui import UIPresenter


class HistoryContractTests(unittest.TestCase):
    def test_history_event_family_mapping_is_explicit(self) -> None:
        self.assertIs(HistoryEvent.REQUESTED.family, HistoryFamily.LIVE)
        self.assertIs(HistoryEvent.QUEUED.family, HistoryFamily.DROP)
        self.assertIs(HistoryEvent.TUNNEL_CLOSED.family, HistoryFamily.DROP)

    def test_history_projector_uses_typed_raw_entries(self) -> None:
        entries = [
            HistoryLedgerEntry(
                timestamp='2026-04-05T10:00:00+00:00',
                family=HistoryFamily.LIVE,
                event_code=HistoryEvent.REQUESTED,
                peer_onion='peer.onion',
                actor=HistoryActor.LOCAL,
                trigger=HistoryTrigger.MANUAL,
                detail_code=None,
                detail_text='',
                flow_id='flow-live',
            ),
            HistoryLedgerEntry(
                timestamp='2026-04-05T10:01:00+00:00',
                family=HistoryFamily.LIVE,
                event_code=HistoryEvent.REQUESTED,
                peer_onion='peer.onion',
                actor=HistoryActor.SYSTEM,
                trigger=HistoryTrigger.AUTO_RECONNECT,
                detail_code=None,
                detail_text='',
                flow_id='flow-live-auto',
            ),
            HistoryLedgerEntry(
                timestamp='2026-04-05T10:02:00+00:00',
                family=HistoryFamily.DROP,
                event_code=HistoryEvent.QUEUED,
                peer_onion='peer.onion',
                actor=HistoryActor.SYSTEM,
                trigger=HistoryTrigger.MANUAL,
                detail_code=HistoryReasonCode.MANUAL_FALLBACK_TO_DROP,
                detail_text='',
                flow_id='flow-drop',
            ),
        ]

        projected = HistoryProjector.project(entries)

        self.assertEqual(len(projected), 2)
        self.assertEqual(
            [entry.event_code for entry in projected],
            [
                HistorySummaryCode.CONNECTION_REQUESTED,
                HistorySummaryCode.DROP_QUEUED,
            ],
        )
        self.assertIs(projected[0].family, HistoryFamily.LIVE)
        self.assertIs(projected[1].family, HistoryFamily.DROP)

    def test_history_events_cast_nested_entries_to_typed_codes(self) -> None:
        history_event = HistoryDataEvent(
            entries=[
                {
                    'timestamp': '2026-04-05T10:03:00+00:00',
                    'family': 'live',
                    'event_code': 'connection_failed',
                    'peer_onion': 'peer.onion',
                    'actor': 'system',
                    'trigger': 'auto_reconnect',
                    'detail_code': 'retry_exhausted',
                    'detail_text': '',
                    'flow_id': 'flow-summary',
                    'alias': 'peer',
                }
            ],
            profile='default',
        )
        raw_event = HistoryRawDataEvent(
            entries=[
                {
                    'timestamp': '2026-04-05T10:04:00+00:00',
                    'family': 'drop',
                    'event_code': 'queued',
                    'peer_onion': 'peer.onion',
                    'actor': 'system',
                    'trigger': 'manual',
                    'detail_code': 'manual_fallback_to_drop',
                    'detail_text': '',
                    'flow_id': 'flow-raw',
                    'alias': 'peer',
                }
            ],
            profile='default',
        )

        summary_entry = history_event.entries[0]
        raw_entry = raw_event.entries[0]

        self.assertIsInstance(summary_entry, SummaryHistoryEntry)
        self.assertIs(summary_entry.family, HistoryEntryFamily.LIVE)
        self.assertIs(summary_entry.actor, HistoryEntryActor.SYSTEM)
        self.assertIs(
            summary_entry.event_code, HistorySummaryEventCode.CONNECTION_FAILED
        )
        self.assertIs(
            summary_entry.detail_code,
            HistoryEntryReasonCode.RETRY_EXHAUSTED,
        )
        self.assertIsInstance(raw_entry, RawHistoryEntry)
        self.assertIs(raw_entry.family, HistoryEntryFamily.DROP)
        self.assertIs(raw_entry.event_code, HistoryRawEventCode.QUEUED)

        rendered = UIPresenter.format_history(history_event)

        self.assertIn('Connection to', rendered)
        self.assertIn('retry limit exhausted', rendered)


if __name__ == '__main__':
    unittest.main()
