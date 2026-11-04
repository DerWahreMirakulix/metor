"""Ended LIVE fallback presentation preserves ongoing recovery and request ownership."""

import unittest
from dataclasses import replace
from unittest.mock import Mock

from metor.client import FrontendLaunchContext
from metor.core.api import (
    ConnectionConnectingEvent,
    Delivery,
    FallbackSuccessEvent,
    LiveContextEntry,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.live import pending_fallback_count
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update


class PendingLivePresentationTests(unittest.TestCase):
    """Follows local admission and snapshots without any transport or native devices."""

    def setUp(self) -> None:
        """Creates ended retained work with the real action/progress owner."""
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.gui.state.covered = False
        self.route = Route('V09', 'bob', Delivery.LIVE)
        self.gui.state.route = self.route
        self.entry = LiveContextEntry(
            'Bob', 'bob', True, 'disconnected', pending_outbound_count=2
        )
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', 'self', live_contexts=[self.entry], revision=4
        )
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        self.gui.refresh_state = Mock()

    def live_requests(self) -> int:
        """Counts mutation requests independently of navigation's read-only handoff."""
        return sum(
            call.args[0].startswith('live:') for call in self.gui.submit.call_args_list
        )

    def test_start_admission_hides_fallback_before_snapshot_and_through_recovery(
        self,
    ) -> None:
        """A retry's stale ended snapshot never replaces its composer with fallback."""
        self.assertEqual(pending_fallback_count(self.gui, self.route), 2)
        self.assertTrue(self.gui.live.start('bob'))
        self.assertEqual(pending_fallback_count(self.gui, self.route), 0)
        mutation = self.gui.live.pending
        assert mutation is not None
        self.gui.live.install(
            Update(0, mutation.operation, ConnectionConnectingEvent('Bob', 'bob'))
        )
        self.assertEqual(pending_fallback_count(self.gui, self.route), 0)
        for phase in ('reconnect_grace', 'reconnect_scheduled', 'disconnected'):
            self.gui.state.snapshot = replace(
                self.gui.state.snapshot,
                live_contexts=[
                    replace(self.entry, session_state=phase, recovery_eligible=True)
                ],
            )
            self.gui.live.poll()
            self.assertEqual(pending_fallback_count(self.gui, self.route), 0)
        self.assertFalse(self.gui.live.starting('bob'))
        self.assertEqual(self.live_requests(), 1)

    def test_ended_policy_reads_do_not_convert_and_drop_projection_never_offers_it(
        self,
    ) -> None:
        """Rendering retained work is read-only and never changes delivery semantics."""
        for _ in range(3):
            self.assertEqual(pending_fallback_count(self.gui, self.route), 2)
        self.assertEqual(
            pending_fallback_count(self.gui, Route('V08', 'bob', Delivery.DROP)),
            0,
        )
        self.gui.submit.assert_not_called()
        self.assertIsNone(self.gui.live.pending)
        self.gui.state.covered = True
        self.assertEqual(pending_fallback_count(self.gui, self.route), 0)

    def test_outbound_attempt_identity_keeps_fallback_hidden_in_stale_end_state(
        self,
    ) -> None:
        """An authoritative outstanding invitation cannot be presented as ended work."""
        snapshot = self.gui.state.snapshot
        assert snapshot is not None
        snapshot.live_contexts = [replace(self.entry, outbound_attempt_id='attempt')]
        self.assertEqual(pending_fallback_count(self.gui, self.route), 0)

    def test_send_and_remove_waits_for_positive_fallback_and_fresh_ended_snapshot(
        self,
    ) -> None:
        """Successful conversion does not dismiss against a pre-conversion snapshot."""
        self.assertTrue(self.gui.live.remove_context('bob', send_pending_as_drops=True))
        mutation = self.gui.live.pending
        assert mutation is not None
        self.gui.live.install(
            Update(
                0,
                mutation.operation,
                FallbackSuccessEvent('Bob', 2, ['first', 'second'], 'bob', revision=5),
            )
        )
        self.gui.live.poll()
        self.assertTrue(self.gui.live.removing('bob'))
        self.assertEqual(self.live_requests(), 1)
        snapshot = self.gui.state.snapshot
        assert snapshot is not None
        self.gui.state.snapshot = replace(
            snapshot,
            live_contexts=[replace(self.entry, pending_outbound_count=0)],
            revision=5,
        )
        self.gui.live.poll()
        self.assertFalse(self.gui.live.removing('bob'))
        self.assertEqual(self.gui.live.pending.kind, 'close')
        self.assertEqual(self.live_requests(), 2)

    def test_unknown_bulk_fallback_never_arms_automatic_removal(self) -> None:
        """A missing conversion reply leaves removal as a separate explicit action."""
        self.assertTrue(self.gui.live.remove_context('bob', send_pending_as_drops=True))
        mutation = self.gui.live.pending
        assert mutation is not None
        self.gui.live.install(Update(0, mutation.operation))
        snapshot = self.gui.state.snapshot
        assert snapshot is not None
        self.gui.state.snapshot = replace(
            snapshot,
            live_contexts=[replace(self.entry, pending_outbound_count=0)],
            revision=5,
        )
        self.gui.live.poll()
        self.assertFalse(self.gui.live.removing('bob'))
        self.assertEqual(self.live_requests(), 1)

    def test_new_recovery_after_conversion_prevents_queued_removal(self) -> None:
        """A fresh accepted session is never ended by an older removal choice."""
        self.assertTrue(self.gui.live.remove_context('bob', send_pending_as_drops=True))
        mutation = self.gui.live.pending
        assert mutation is not None
        self.gui.live.install(
            Update(
                0,
                mutation.operation,
                FallbackSuccessEvent('Bob', 2, ['first', 'second'], 'bob'),
            )
        )
        snapshot = self.gui.state.snapshot
        assert snapshot is not None
        self.gui.state.snapshot = replace(
            snapshot,
            live_contexts=[
                replace(self.entry, pending_outbound_count=0, recovery_eligible=True)
            ],
        )
        self.gui.live.poll()
        self.assertFalse(self.gui.live.removing('bob'))
        self.assertIsNone(self.gui.live.pending)
        self.assertEqual(self.live_requests(), 1)

    def test_cover_cancels_deferred_removal_after_explicit_conversion(self) -> None:
        """Unlock cannot resume destructive dismissal from an earlier foreground flow."""
        self.assertTrue(self.gui.live.remove_context('bob', send_pending_as_drops=True))
        mutation = self.gui.live.pending
        assert mutation is not None
        self.gui.live.install(
            Update(
                0,
                mutation.operation,
                FallbackSuccessEvent('Bob', 2, ['first', 'second'], 'bob'),
            )
        )
        self.gui.live.cover()
        snapshot = self.gui.state.snapshot
        assert snapshot is not None
        self.gui.state.snapshot = replace(
            snapshot, live_contexts=[replace(self.entry, pending_outbound_count=0)]
        )
        self.gui.live.poll()
        self.assertFalse(self.gui.live.removing('bob'))
        self.assertEqual(self.live_requests(), 1)


if __name__ == '__main__':
    unittest.main()
