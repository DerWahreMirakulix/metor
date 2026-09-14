"""Outgoing text budget reservation and out-of-order receipt presentation."""

from unittest.mock import Mock, patch
import unittest

from metor.client import FrontendLaunchContext
from metor.core.api import (
    AckEvent,
    Delivery,
    MessageDirectionCode,
    MessageStatusCode,
    ReadReceiptEvent,
    TextAcceptedEvent,
    TextRejectedEvent,
    MessageOperationReason,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.state.mailbox import Update


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
            FrontendLaunchContext('fixture', Mock()), simulator=True
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
            self.gui.send_text('peer', Delivery.LIVE)
        self.gui.command.assert_not_called()
        self.assertEqual(self.gui.text.operations, {})
        self.assertIn(('peer', Delivery.LIVE), self.gui.state.drafts)

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
