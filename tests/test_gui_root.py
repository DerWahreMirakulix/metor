"""Canonical root membership, protected pin ordering and bounded local LIVE retention."""

import unittest
from unittest.mock import Mock

from test_gui_contacts import address
from metor.client import FrontendProfileState
from metor.client import FrontendLaunchContext
from metor.core.api import (
    Delivery,
    ConnectedEvent,
    DisconnectedEvent,
    DropConversationSummaryEntry,
    GuiPreferences,
    GuiPreferencesEvent,
    LiveContextEntry,
    MessageDirectionCode,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.runtime import GuiController, conversation_rows
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.state.mailbox import Update


class RootProjectionTests(unittest.TestCase):
    """Checks presentation rules without substituting frontend guesses for Core state."""

    def setUp(self) -> None:
        """Creates an unlocked inert coordinator with typed public snapshots.

        Args:
            None
        Returns:
            None
        """
        self.gui = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture', True, False, False
                    )
                ),
            ),
            simulator=True,
        )
        self.gui.state.covered = False
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', address(1))

    def test_drop_pins_preserve_explicit_order_without_ghosts(self) -> None:
        """Pins reorder actual Core rows only, with unpinned recency left intact.

        Args:
            None
        Returns:
            None
        """
        a, b, c, absent = [address(index) for index in range(2, 6)]
        self.gui.state.snapshot.conversations = [
            DropConversationSummaryEntry('Newest', a),
            DropConversationSummaryEntry('Middle', b, 2, 3),
            DropConversationSummaryEntry('Oldest', c),
        ]
        self.gui.state.preferences = GuiPreferencesEvent(
            preferences=GuiPreferences(pins=[c, absent, b])
        )
        self.gui.state.set_draft(absent, Delivery.DROP, 'unsent')
        rows = conversation_rows(self.gui, Delivery.DROP)
        self.assertEqual([row.peer for row in rows], [c, b, a])
        self.assertEqual((rows[1].unseen, rows[1].pending), (2, 3))
        self.gui.state.covered = True
        self.assertEqual(conversation_rows(self.gui, Delivery.DROP), [])

    def test_live_priority_and_local_consumed_membership(self) -> None:
        """Disconnected consumed content remains local and never fabricates unseen or pending.

        Args:
            None
        Returns:
            None
        """
        a, b, c, d = [address(index) for index in range(2, 6)]
        self.gui.state.snapshot.live_contexts = [
            LiveContextEntry(
                'Pending', a, False, 'disconnected', pending_outbound_count=1
            ),
            LiveContextEntry('Active', b, False, 'connected'),
            LiveContextEntry(
                'Recovering', c, False, 'connecting', recovery_eligible=True
            ),
        ]
        self.gui.transcript.admit(
            TranscriptItem(
                d, Delivery.LIVE, MessageDirectionCode.IN, 'consumed', 'text'
            )
        )
        self.gui.state.set_draft(address(8), Delivery.DROP, 'not a conversation')
        rows = conversation_rows(self.gui, Delivery.LIVE)
        self.assertEqual([row.peer for row in rows], [b, c, a, d])
        self.assertTrue(rows[-1].local_only)
        self.assertEqual((rows[-1].unseen, rows[-1].pending), (0, 0))
        self.gui.transcript.discard(d, Delivery.LIVE)
        self.assertEqual(len(conversation_rows(self.gui, Delivery.LIVE)), 3)

    def test_unknown_delete_never_repeats_or_discards_local_source(self) -> None:
        """Uncertain mutation requires a new snapshot and another explicit action.

        Args:
            None
        Returns:
            None
        """
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        self.gui.refresh_state = Mock()
        self.gui.transcript.admit(
            TranscriptItem(
                address(2), Delivery.DROP, MessageDirectionCode.IN, 'item', 'text'
            )
        )
        self.assertTrue(
            self.gui.drop.delete(address(2), 'item', MessageDirectionCode.IN)
        )
        operation = self.gui.drop.pending.operation
        self.gui.drop.install(Update(0, operation))
        self.gui.drop.poll()
        self.assertFalse(self.gui.drop.clear(address(2)))
        self.assertEqual(len(self.gui.transcript.items), 1)
        self.assertEqual(self.gui.submit.call_count, 1)
        self.gui.state.snapshot = RuntimeSnapshotEvent('fixture', address(1))
        self.gui.drop.poll()
        self.assertIsNone(self.gui.drop.pending)
        self.assertEqual(self.gui.submit.call_count, 1)
        self.assertEqual(len(self.gui.transcript.items), 1)

    def test_remote_lifecycle_refresh_is_coalesced_and_never_reads_through_cover(
        self,
    ) -> None:
        """Lifecycle bursts request current Core state without navigation or covered reads.

        Args:
            None
        Returns:
            None
        """
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        route = self.gui.state.route
        for event in (
            ConnectedEvent('Peer', address(2)),
            DisconnectedEvent('Peer', address(2)),
            ConnectedEvent('Peer', address(2)),
        ):
            self.gui.mailbox.put(Update(0, 'event', event))
        self.gui.poll()
        snapshots = [
            call
            for call in self.gui.submit.call_args_list
            if call.args[0] == 'snapshot'
        ]
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(self.gui.state.route, route)
        self.gui.submit.reset_mock()
        self.gui.state.covered = True
        self.gui._refresh_needed = True
        self.gui.mailbox.put(Update(0, 'event', DisconnectedEvent('Peer', address(2))))
        self.gui.poll()
        self.assertFalse(
            any(call.args[0] == 'snapshot' for call in self.gui.submit.call_args_list)
        )
