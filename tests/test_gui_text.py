"""Outgoing text budget reservation and out-of-order receipt presentation."""

from unittest.mock import Mock, patch
import unittest

from metor.client import FrontendProfileState
from metor.client import FrontendLaunchContext
from metor.core.api import (
    AckEvent,
    Delivery,
    MessageDirectionCode,
    MessageStatusCode,
    ReadReceiptEvent,
    TextAcceptedEvent,
    DropQueuedEvent,
    TextRejectedEvent,
    MessageOperationReason,
    MessageOutcomeEvent,
    GetMessageOutcomeCommand,
    DropsDisabledEvent,
    MessagesDataEvent,
    MessageEntry,
    TextContent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.state import Route


class TextAdmissionTests(unittest.TestCase):
    """Uses real GUI state logic with an inert command-admission boundary."""

    def setUp(self) -> None:
        """Creates one unlocked draft without opening a profile or network connection.

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
        self.gui.state.capabilities = frozenset({'local_text_acceptance'})
        self.gui.state.set_draft('peer', Delivery.LIVE, 'keep the exact text')
        self.gui.command = Mock(return_value=True)

    def admit(self) -> tuple[str, str]:
        """Starts an explicit send and returns its stable local operation identity.

        Args:
            None
        Returns:
            tuple[str, str]: Operation and message IDs.
        """
        self.gui.send_text('peer', Delivery.LIVE)
        action = next(iter(self.gui.text.operations))
        return action, action.removeprefix('A11:')

    def test_full_transcript_refuses_send_before_core_admission(self) -> None:
        """An accepted send cannot silently erase a draft that cannot fit locally.

        Args:
            None
        Returns:
            None
        """
        with patch.object(GuiLimits, 'LIVE_ITEMS', 1):
            self.gui.transcript.admit(
                TranscriptItem(
                    'other', Delivery.LIVE, MessageDirectionCode.IN, 'existing'
                )
            )
            for delivery in (Delivery.LIVE, Delivery.DROP):
                self.gui.state.set_draft('peer', delivery, 'keep the exact text')
                self.gui.send_text('peer', delivery)
        self.gui.command.assert_not_called()
        self.assertEqual(self.gui.text.operations, {})
        self.assertIn(('peer', Delivery.LIVE), self.gui.state.drafts)

    def test_confirmed_drop_refreshes_open_archive_without_a_live_context(self) -> None:
        """Local acceptance refreshes the history while preserving newer draft edits."""
        self.gui.state.set_draft('peer', Delivery.DROP, 'a new drop')
        self.gui.send_text('peer', Delivery.DROP)
        action = next(iter(self.gui.text.operations))
        self.gui.state.set_draft('peer', Delivery.DROP, 'the next draft')
        self.gui.text.install(Update(0, action, DropQueuedEvent('Peer', 'peer')))
        self.assertTrue(self.gui._messages_needed)
        self.assertTrue(self.gui._refresh_needed)
        self.assertEqual(
            self.gui.state.drafts[('peer', Delivery.DROP)], 'the next draft'
        )
        self.assertFalse(self.gui.text.operations)

    def test_confirmed_drop_is_immediately_presented_without_clearing_latest_history(
        self,
    ) -> None:
        """Core-positive acceptance appends one exact local row while the existing page stays visible."""
        self.gui.state.route = Route('V08', 'peer', Delivery.DROP)
        prior = MessagesDataEvent(
            [
                MessageEntry(
                    MessageDirectionCode.IN,
                    MessageStatusCode.READ,
                    Delivery.DROP,
                    TextContent('earlier message'),
                    '2026-10-06',
                    'earlier',
                )
            ],
            'Peer',
            'peer',
        )
        self.gui.messages = prior
        self.gui.state.set_draft('peer', Delivery.DROP, 'new message')
        self.gui.send_text('peer', Delivery.DROP)
        action = next(iter(self.gui.text.operations))
        identity = action.removeprefix('A11:')
        self.assertFalse(self.gui.transcript.items)
        self.gui.text.install(Update(0, action, DropQueuedEvent('Peer', 'peer')))
        self.assertIs(self.gui.messages, prior)
        row = self.gui.transcript.items[
            ('peer', Delivery.DROP, MessageDirectionCode.OUT, identity)
        ]
        self.assertEqual(row.text, 'new message')
        self.assertEqual(row.status, MessageStatusCode.PENDING)
        self.assertNotIn(('peer', Delivery.DROP), self.gui.state.drafts)

    def test_confirmed_drop_returns_older_archive_to_latest_without_navigation(
        self,
    ) -> None:
        """An accepted new message cannot remain behind the previously selected page cursor."""
        route = Route('V08', 'peer', Delivery.DROP)
        self.gui.state.route = route
        self.gui.archive.before = MessageDirectionCode.IN, 'oldest-on-older-page'
        self.gui.state.set_draft('peer', Delivery.DROP, 'newest message')
        self.gui.send_text('peer', Delivery.DROP)
        action = next(iter(self.gui.text.operations))
        self.gui.text.install(Update(0, action, DropQueuedEvent('Peer', 'peer')))
        self.assertEqual(self.gui.state.route, route)
        self.assertIsNone(self.gui.archive.before)
        self.assertTrue(self.gui.archive.needed)
        self.assertNotIn(('peer', Delivery.DROP), self.gui.state.drafts)

    def test_accepting_background_peer_preserves_visible_archive_cursor(self) -> None:
        """A late receipt cannot navigate away from the peer currently being read."""
        self.gui.state.route = Route('V08', 'other', Delivery.DROP)
        cursor = MessageDirectionCode.IN, 'reading-history'
        self.gui.archive.before = cursor
        self.gui.state.set_draft('peer', Delivery.DROP, 'background message')
        self.gui.send_text('peer', Delivery.DROP)
        action = next(iter(self.gui.text.operations))
        self.gui.text.install(Update(0, action, DropQueuedEvent('Peer', 'peer')))
        self.assertEqual(self.gui.archive.before, cursor)

    def test_rejected_worker_admission_keeps_draft_and_reports_no_send(self) -> None:
        """A click refused before IPC has visible feedback and no unresolved identity."""
        self.gui.command.return_value = False
        self.gui.state.set_draft('peer', Delivery.DROP, 'keep this draft')
        self.gui.send_text('peer', Delivery.DROP)
        self.assertFalse(self.gui.text.pending('peer', Delivery.DROP))
        self.assertEqual(
            self.gui.state.drafts[('peer', Delivery.DROP)], 'keep this draft'
        )
        self.assertIn('has not been sent', self.gui.state.status)

    def test_disabled_drops_report_rejection_without_erasing_draft(self) -> None:
        """A definite Core policy rejection unlocks retry without claiming acceptance."""
        self.gui.state.set_draft('peer', Delivery.DROP, 'keep this draft')
        self.gui.send_text('peer', Delivery.DROP)
        action = next(iter(self.gui.text.operations))
        self.gui.text.install(Update(0, action, DropsDisabledEvent()))
        self.assertFalse(self.gui.text.pending('peer', Delivery.DROP))
        self.assertEqual(
            self.gui.state.drafts[('peer', Delivery.DROP)], 'keep this draft'
        )
        self.assertIn('Drops are disabled', self.gui.state.status)

    def test_unknown_drop_rechecks_bounded_receipts_without_resending(self) -> None:
        """A missing first receipt schedules another read of the same ID after its interval."""
        self.gui.state.set_draft('peer', Delivery.DROP, 'one logical message')
        self.gui.send_text('peer', Delivery.DROP)
        action = next(iter(self.gui.text.operations))
        identity = action.removeprefix('A11:')
        self.assertEqual(
            self.gui.text.pending_status('peer', Delivery.DROP), 'Sending…'
        )
        self.assertEqual(self.gui.text.pending_status('other', Delivery.DROP), '')
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        self.gui.state.capabilities = frozenset({'message_outcome'})
        self.gui.text.install(Update(0, action, None))
        self.assertEqual(
            self.gui.text.pending_status('peer', Delivery.DROP), 'Checking send result…'
        )
        with patch('metor.ui.gui.runtime.text.time.monotonic', return_value=10.0):
            self.gui.text.poll()
            first = self.gui.submit.call_args
            self.assertEqual(first.args[0], 'text-check:' + action)
            self.assertTrue(first.kwargs['background'])
            first.args[1]()
            self.gui.client.request.assert_called_once_with(
                GetMessageOutcomeCommand('peer', identity), MessageOutcomeEvent
            )
            self.gui.text.install(
                Update(0, 'text-check:' + action, MessageOutcomeEvent('peer', identity))
            )
            self.gui.text.poll()
            self.assertEqual(self.gui.submit.call_count, 1)
        with patch(
            'metor.ui.gui.runtime.text.time.monotonic',
            return_value=10.0 + GuiLimits.TEXT_OUTCOME_SECONDS,
        ):
            self.gui.text.poll()
        self.assertEqual(self.gui.submit.call_count, 2)
        self.assertTrue(self.gui.text.pending('peer', Delivery.DROP))
        self.gui.send_text('peer', Delivery.DROP)
        self.gui.command.assert_called_once()
        self.gui.text.install(
            Update(
                0,
                'text-check:' + action,
                MessageOutcomeEvent(
                    'peer',
                    identity,
                    delivery=Delivery.DROP,
                    status=MessageStatusCode.PENDING,
                ),
            )
        )
        self.assertNotIn(('peer', Delivery.DROP), self.gui.state.drafts)
        self.assertFalse(self.gui.text.pending('peer', Delivery.DROP))
        self.assertEqual(self.gui.text.pending_status('peer', Delivery.DROP), '')

    def test_wrong_drop_receipt_keeps_exact_send_identity_unknown(self) -> None:
        """A success or rejection for another peer cannot open a duplicate-send path."""
        self.gui.state.set_draft('peer', Delivery.DROP, 'one logical message')
        self.gui.send_text('peer', Delivery.DROP)
        action = next(iter(self.gui.text.operations))
        for event in (
            DropQueuedEvent('Other', 'other'),
            TextRejectedEvent('other', action.removeprefix('A11:')),
        ):
            self.gui.text.install(Update(0, action, event))
            self.assertTrue(self.gui.text.pending('peer', Delivery.DROP))
            self.assertFalse(self.gui.text.pending('other', Delivery.DROP))
            self.assertIn(action, self.gui._unknown_actions)
        self.assertEqual(
            self.gui.state.drafts[('peer', Delivery.DROP)], 'one logical message'
        )

    def test_reserved_capacity_survives_arrivals_until_positive_acceptance(
        self,
    ) -> None:
        """Incoming presentation cannot steal the payload slot reserved for an in-flight send.

        Args:
            None
        Returns:
            None
        """
        with patch.object(GuiLimits, 'LIVE_ITEMS', 1):
            action, identity = self.admit()
            self.assertEqual(self.gui.transcript.capacity()[0], 0)
            self.assertFalse(
                self.gui.transcript.admit(
                    TranscriptItem(
                        'other', Delivery.LIVE, MessageDirectionCode.IN, 'arrival'
                    )
                )
            )
            self.gui.text.install(
                Update(
                    0,
                    action,
                    TextAcceptedEvent('peer', identity, Delivery.LIVE),
                )
            )
            self.assertEqual(len(self.gui.transcript.items), 1)
        self.assertFalse(self.gui.text.reservations)
        self.assertNotIn(('peer', Delivery.LIVE), self.gui.state.drafts)

    def test_early_read_and_late_ack_never_downgrade_text_or_voice(self) -> None:
        """Positive peer evidence survives acceptance-result races and later inventory updates.

        Args:
            None
        Returns:
            None
        """
        action, identity = self.admit()
        self.gui.text.install(
            Update(0, 'event', ReadReceiptEvent('peer', identity, 'peer'))
        )
        self.gui.text.install(Update(0, 'event', AckEvent(identity)))
        self.gui.text.install(
            Update(0, action, TextAcceptedEvent('peer', identity, Delivery.LIVE))
        )
        key = ('peer', Delivery.LIVE, MessageDirectionCode.OUT, identity)
        self.assertEqual(self.gui.transcript.items[key].status, MessageStatusCode.READ)
        self.gui.transcript.install(AckEvent(identity))
        self.gui.transcript.admit(
            TranscriptItem(*key, status=MessageStatusCode.PENDING)
        )
        self.assertEqual(self.gui.transcript.items[key].status, MessageStatusCode.READ)
        turn = Mock(status=MessageStatusCode.READ)
        self.gui.voice.live_turns['voice'] = turn
        self.gui.transcript.install(AckEvent('voice'))
        self.assertEqual(turn.status, MessageStatusCode.READ)

    def test_starting_capture_reserves_metadata_before_core_result(self) -> None:
        """Incoming handoff cannot steal a pending capture's chronological metadata slot.

        Args:
            None
        Returns:
            None
        """
        from metor.ui.gui.runtime.voice.press import CaptureBinding, PressSource
        from metor.ui.gui.runtime.voice.controller import LocalVoiceTurn

        binding = CaptureBinding(
            'profile', 'epoch', 0, 'peer', Delivery.LIVE, 'capture', 1
        )
        with patch.object(GuiLimits, 'LIVE_ITEMS', 1):
            self.assertTrue(
                self.gui.voice.press.down(PressSource.POINTER, binding, True)
            )
            free = self.gui.transcript.capacity()
            self.assertEqual(free[0], 0)
            self.assertFalse(
                self.gui.transcript.admit(
                    TranscriptItem(
                        'other', Delivery.LIVE, MessageDirectionCode.IN, 'arrival'
                    )
                )
            )
            self.gui.voice.live_turns[binding.msg_id] = LocalVoiceTurn(binding)
            self.assertEqual(self.gui.transcript.capacity(), free)

    def test_rejected_send_releases_reservation_but_unknown_keeps_it(self) -> None:
        """Only definite rejection frees the slot while preserving the unsent draft.

        Args:
            None
        Returns:
            None
        """
        action, identity = self.admit()
        self.gui.text.install(Update(0, action, None))
        self.assertIn(action, self.gui.text.reservations)
        self.assertIn(action, self.gui.text.operations)
        self.gui.text.install(
            Update(
                0,
                action,
                TextRejectedEvent(
                    'peer', identity, MessageOperationReason.INVALID_SELECTION
                ),
            )
        )
        self.assertFalse(self.gui.text.reservations)
        self.assertIn(('peer', Delivery.LIVE), self.gui.state.drafts)
