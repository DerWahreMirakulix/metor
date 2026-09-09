"""Regression tests for the typed history DTO and projection contract."""

# ruff: noqa: E402

import sys
import re
import unittest
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.core.api import (
    HistoryDataEvent,
    HistoryEntryActor,
    HistoryEntryFamily,
    HistoryEntryReasonCode,
    HistoryEntryTrigger,
    HistoryRawDataEvent,
    HistoryRawEventCode,
    HistorySummaryEventCode,
    RawHistoryEntry,
    SummaryHistoryEntry,
    TransportStateEvent,
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
    """
    Covers history contract regression scenarios.
    """

    def test_history_event_family_mapping_is_explicit(self) -> None:
        """
        Verifies that history event family mapping is explicit.

        Args:
            None

        Returns:
            None
        """

        self.assertIs(HistoryEvent.REQUESTED.family, HistoryFamily.LIVE)
        self.assertIs(HistoryEvent.QUEUED.family, HistoryFamily.DROP)
        self.assertIs(HistoryEvent.TUNNEL_CLOSED.family, HistoryFamily.DROP)

    def test_history_projector_uses_typed_raw_entries(self) -> None:
        """
        Verifies that history projector uses typed raw entries.

        Args:
            None

        Returns:
            None
        """

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
        """
        Verifies that history events cast nested entries to typed codes.

        Args:
            None

        Returns:
            None
        """

        history_event = HistoryDataEvent(
            entries=cast(
                list[SummaryHistoryEntry],
                [
                    {
                        'timestamp': '2026-04-05T10:03:00+00:00',
                        'family': 'live',
                        'event_code': 'connection_failed',
                        'peer_onion': 'peer.onion',
                        'actor': 'system',
                        'trigger': HistoryEntryTrigger.AUTO_RECONNECT.value,
                        'detail_code': 'retry_exhausted',
                        'detail_text': '',
                        'flow_id': 'flow-summary',
                        'alias': 'peer',
                    }
                ],
            ),
            profile='default',
        )
        raw_event = HistoryRawDataEvent(
            entries=cast(
                list[RawHistoryEntry],
                [
                    {
                        'timestamp': '2026-04-05T10:04:00+00:00',
                        'family': 'drop',
                        'event_code': 'queued',
                        'peer_onion': 'peer.onion',
                        'actor': 'system',
                        'trigger': HistoryEntryTrigger.MANUAL.value,
                        'detail_code': 'manual_fallback_to_drop',
                        'detail_text': '',
                        'flow_id': 'flow-raw',
                        'alias': 'peer',
                    }
                ],
            ),
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

    def test_raw_history_presenter_renders_transport_field(self) -> None:
        """
        Verifies that format_raw_history renders the ledger transport field.

        Regression guard: the transport field existed in the ledger DTO but the
        CLI presenter never printed it, so `history show --raw` could not show
        session/tunnel/direct provenance.

        Args:
            None

        Returns:
            None
        """
        from metor.ui.presenter.history import format_raw_history

        event = HistoryRawDataEvent(
            profile='alice',
            alias='bob',
            entries=[
                RawHistoryEntry(
                    timestamp=1700000000.0,
                    family=HistoryEntryFamily.DROP,
                    event_code=HistoryRawEventCode.SENT,
                    actor=HistoryEntryActor.LOCAL,
                    peer_onion='bob',
                    flow_id='flow-1',
                    trigger=None,
                    detail_code=None,
                    detail_text=None,
                    transport='session',
                ),
            ],
        )
        rendered = format_raw_history(event)
        clean_rendered = re.sub(r'\x1b\[[0-9;]*m', '', rendered)
        self.assertIn('transport: session', clean_rendered)

    def test_transport_state_formatting_has_no_decorative_header(self) -> None:
        """
        Verifies the terminal transport-state formatting convention.

        Regression guard: transport output used '--- Transport state ---' header
        decorators and a leading blank line; the peer case must start with the
        header as first line and the no-peer case must render only the message.

        Args:
            None

        Returns:
            None
        """
        from metor.ui.presenter.transport import format_transport_state

        peer_output = format_transport_state(
            TransportStateEvent(
                peer='k4i7sr',
                session_state='connected',
                drop_tunnel=None,
                focus_count=1,
                pending_live_count=0,
                auto_accept=False,
            )
        )
        clean_peer = re.sub(r'\x1b\[[0-9;]*m', '', peer_output)
        self.assertFalse(clean_peer.startswith('\n'))
        self.assertNotIn('---', clean_peer)
        self.assertTrue(clean_peer.startswith('Transport state for k4i7sr'))
        self.assertIn(
            'Transport state for k4i7sr\n\nsession_state: connected', clean_peer
        )

        no_peer_output = format_transport_state(
            TransportStateEvent(
                peer='',
                session_state='disconnected',
                drop_tunnel=None,
                focus_count=0,
                pending_live_count=0,
                auto_accept=False,
            )
        )
        clean_no_peer = re.sub(r'\x1b\[[0-9;]*m', '', no_peer_output)
        self.assertNotIn('Transport state', clean_no_peer)
        self.assertNotIn('---', clean_no_peer)
        self.assertIn('No active sessions.', clean_no_peer)


if __name__ == '__main__':
    unittest.main()
