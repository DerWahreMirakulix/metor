"""Unified GUI message review, publication and lock boundaries without native audio."""

from unittest.mock import Mock
import unittest

from metor.client import FrontendLaunchContext, FrontendProfileState
from metor.core.api import (
    Delivery,
    ContentType,
    MessageStatusCode,
    MessageOperationReason,
    MessageOutcomeEvent,
    RetainedMessageEntry,
    LiveContextEntry,
    MessageDirectionCode,
    RuntimeSnapshotEvent,
    VoiceCommittedEvent,
    VoiceFinalizedEvent,
    VoiceOperationRejectedEvent,
)
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.voice import PressSource
from metor.ui.gui.runtime.voice.models import VoiceReview
from metor.ui.gui.runtime.voice.press import CaptureBinding
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update


class VoiceReviewTests(unittest.TestCase):
    """Checks original recording identity and explicit intent across both delivery modes."""

    def setUp(self) -> None:
        """Creates a real coordinator around inert public SDK and endpoint mocks."""
        self.gui = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture', True, False, False
                    )
                ),
            )
        )
        self.addCleanup(self.gui.close)
        self.gui.state.covered = False
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            '',
            epoch='epoch',
            profile_instance_id='instance',
            live_contexts=[
                LiveContextEntry(
                    'Peer', 'peer', True, 'connected', context_generation=7
                )
            ],
        )
        self.gui.voice_owner.token = 'owner'
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)

    def binding(self, delivery: Delivery) -> CaptureBinding:
        """Builds an immutable draft target in the current original chat generation."""
        return CaptureBinding(
            'instance',
            'epoch',
            self.gui.state.generation,
            'peer',
            delivery,
            'recording',
            7 if delivery is Delivery.LIVE else None,
        )

    def test_release_finalizes_both_modes_as_review_without_a_send(self) -> None:
        """Releasing hardware PTT requests stop and never publishes a voice message."""
        for delivery in (Delivery.DROP, Delivery.LIVE):
            with self.subTest(delivery=delivery):
                binding = self.binding(delivery)
                self.gui.voice.reviews.clear()
                self.gui.voice.worker = Mock()
                self.assertTrue(
                    self.gui.voice.press.down(PressSource.PHYSICAL, binding, True)
                )
                self.gui.voice.press.accepted(binding)
                self.gui.voice.up(PressSource.PHYSICAL)
                self.gui.voice.worker.request_stop.assert_called_once_with()
                event = VoiceFinalizedEvent(
                    'recording',
                    640,
                    duration_ms=20,
                    onion='peer',
                    direction=MessageDirectionCode.OUT,
                    delivery=delivery,
                )
                self.gui.voice.install(
                    Update(binding.generation, 'voice-finished:recording', event)
                )
                review = self.gui.voice.reviews['peer']
                self.assertEqual(review.binding, binding)
                self.assertEqual(review.size_bytes, 640)
                self.assertFalse(self.gui.voice.live_turns)
                self.gui.client.commit_voice.assert_not_called()
                self.gui.playback.audio = Mock()
                self.gui.playback.audio.play_frame.assert_not_called()

    def test_explicit_live_send_works_without_preview(self) -> None:
        """Preview is optional; Send preserves the exact identity and original chat."""
        binding = self.binding(Delivery.LIVE)
        self.gui.voice.reviews['peer'] = VoiceReview(binding, 640, 20)
        self.assertTrue(self.gui.voice.review_actions.act('peer', send=True))
        operation, request = self.gui.submit.call_args.args
        self.assertEqual(operation, 'review:commit:recording')
        request()
        self.gui.client.commit_voice.assert_called_once_with(
            'peer',
            'recording',
            owner_token='owner',
            delivery=Delivery.LIVE,
            context_generation=7,
        )
        self.assertIsNone(self.gui.playback.worker)

    def test_ended_chat_preserves_draft_and_requires_explicit_drop_conversion(
        self,
    ) -> None:
        """A stale/replaced chat cannot retarget publication or implicitly create DROP."""
        binding = self.binding(Delivery.LIVE)
        self.gui.voice.reviews['peer'] = VoiceReview(binding, 640, 20)
        self.gui.state.snapshot.live_contexts[0].context_generation = 8
        self.assertFalse(self.gui.voice.review_actions.act('peer', send=True))
        self.gui.submit.assert_not_called()
        self.assertEqual(self.gui.voice.reviews['peer'].binding, binding)
        self.assertTrue(
            self.gui.voice.review_actions.act('peer', send=True, delivery=Delivery.DROP)
        )
        self.gui.submit.call_args.args[1]()
        self.gui.client.commit_voice.assert_called_once_with(
            'peer',
            'recording',
            owner_token='owner',
            delivery=Delivery.DROP,
            context_generation=7,
        )

    def test_live_publication_adds_timeline_only_after_positive_receipt(self) -> None:
        """Local draft metadata is kept outside the sent-message projection until commit."""
        self.gui.state.route = Route('V09', 'peer', Delivery.LIVE)
        binding = self.binding(Delivery.LIVE)
        self.gui.voice.reviews['peer'] = VoiceReview(binding, 640, 20)
        self.gui.voice.review_actions.install(
            Update(
                binding.generation,
                'review:commit:recording',
                VoiceCommittedEvent(
                    'Peer', 'recording', 'peer', delivery=Delivery.LIVE
                ),
            )
        )
        self.assertFalse(self.gui.voice.reviews)
        turn = self.gui.voice.live_turns['recording']
        self.assertEqual(turn.binding, binding)
        self.assertTrue(turn.finalized)

    def test_successful_send_clears_review_without_duplicate_feedback(self) -> None:
        """The sent card confirms publication while another action's notice remains intact."""
        for delivery in (Delivery.DROP, Delivery.LIVE):
            with self.subTest(delivery=delivery):
                binding = self.binding(delivery)
                self.gui.state.route = Route(
                    'V08' if delivery is Delivery.DROP else 'V09', 'peer', delivery
                )
                self.gui.voice.reviews['peer'] = VoiceReview(binding, 640, 20)
                self.gui.state.status = 'Contact renamed'
                before = self.gui.state.feedback.revision
                self.assertTrue(self.gui.voice.review_actions.act('peer', send=True))
                self.gui.voice.review_actions.install(
                    Update(
                        binding.generation,
                        'review:commit:recording',
                        VoiceCommittedEvent(
                            'Peer', 'recording', 'peer', delivery=delivery
                        ),
                    )
                )
                self.assertNotIn('peer', self.gui.voice.reviews)
                self.assertEqual(self.gui.voice.review_actions.notice('peer'), '')
                self.assertEqual(self.gui.state.feedback.revision, before)
                self.assertEqual(self.gui.state.feedback.visible(), 'Contact renamed')

    def test_rejected_review_keeps_local_note_until_an_admitted_retry(self) -> None:
        """A rejected recording stays recoverable without an expiring overlay."""
        binding = self.binding(Delivery.DROP)
        self.gui.state.route = Route('V08', 'peer', Delivery.DROP)
        self.gui.voice.reviews['peer'] = VoiceReview(binding, 640, 20)
        self.gui.state.status = 'Contact renamed'
        before = self.gui.state.feedback.revision
        self.gui.voice.review_actions.install(
            Update(
                binding.generation,
                'review:commit:recording',
                VoiceOperationRejectedEvent(
                    'recording', MessageOperationReason.NOT_FOUND, 'peer'
                ),
            )
        )
        self.assertEqual(
            self.gui.voice.review_actions.notice('peer'), 'Recording remains unsent'
        )
        self.assertFalse(self.gui.voice.reviews['peer'].unknown)
        self.assertEqual(self.gui.state.feedback.revision, before)
        self.gui.state.feedback.expires_at = 0
        self.assertEqual(
            self.gui.voice.review_actions.notice('peer'), 'Recording remains unsent'
        )
        self.gui.submit.return_value = False
        self.assertFalse(self.gui.voice.review_actions.act('peer', send=True))
        self.assertTrue(self.gui.voice.review_actions.notice('peer'))
        self.gui.submit.return_value = True
        self.assertTrue(self.gui.voice.review_actions.act('peer', send=True))
        self.assertEqual(self.gui.voice.review_actions.notice('peer'), '')
        self.assertEqual(self.gui.state.status, 'Contact renamed')

    def test_unknown_review_rechecks_read_only_and_keeps_local_recovery(self) -> None:
        """An uncertain result blocks resend and visibly reconciles the original identity."""
        binding = self.binding(Delivery.DROP)
        self.gui.state.route = Route('V08', 'peer', Delivery.DROP)
        self.gui.voice.reviews['peer'] = VoiceReview(binding, 640, 20)
        actions = self.gui.voice.review_actions
        before = self.gui.state.feedback.revision
        actions.install(Update(binding.generation, 'review:commit:recording'))
        self.assertTrue(self.gui.voice.reviews['peer'].unknown)
        self.assertEqual(
            actions.notice('peer'),
            'Recording outcome is unconfirmed. Recheck before sending again.',
        )
        self.assertFalse(actions.act('peer', send=True))
        self.gui.submit.assert_not_called()
        self.assertTrue(actions.check('peer'))
        operation, request = self.gui.submit.call_args.args
        self.assertEqual(operation, 'review:check:recording')
        self.assertTrue(self.gui.submit.call_args.kwargs['background'])
        self.assertEqual(actions.notice('peer'), 'Checking recording…')
        request()
        self.gui.client.commit_voice.assert_not_called()
        command = self.gui.client.request.call_args.args[0]
        self.assertEqual((command.onion, command.msg_id), ('peer', 'recording'))
        actions.install(
            Update(
                binding.generation,
                operation,
                MessageOutcomeEvent(
                    'peer', 'recording', status=MessageStatusCode.DRAFT
                ),
            )
        )
        self.assertFalse(self.gui.voice.reviews['peer'].unknown)
        self.assertEqual(actions.notice('peer'), 'Recording is still unsent')
        self.assertEqual(self.gui.state.feedback.revision, before)

    def test_departed_review_failure_notifies_and_respects_newer_feedback(self) -> None:
        """Background failure alerts once; resolution cannot dismiss another action's result."""
        binding = self.binding(Delivery.DROP)
        self.gui.state.route = Route('V17')
        self.gui.voice.reviews['peer'] = VoiceReview(binding, 640, 20)
        actions = self.gui.voice.review_actions
        actions.install(Update(binding.generation, 'review:commit:recording'))
        self.assertEqual(self.gui.state.feedback.visible(), actions.notice('peer'))
        self.gui.state.status = 'Contact renamed'
        actions.install(
            Update(
                binding.generation,
                'review:check:recording',
                MessageOutcomeEvent(
                    'peer',
                    'recording',
                    delivery=Delivery.DROP,
                    status=MessageStatusCode.PENDING,
                ),
            )
        )
        self.assertEqual(actions.notice('peer'), '')
        self.assertEqual(self.gui.state.feedback.visible(), 'Contact renamed')

    def test_readback_replaces_only_its_own_background_failure_notice(self) -> None:
        """A deliberate readback clears its stale toast and shows persistent local progress."""
        binding = self.binding(Delivery.DROP)
        self.gui.state.route = Route('V17')
        self.gui.voice.reviews['peer'] = VoiceReview(binding, 640, 20)
        actions = self.gui.voice.review_actions
        actions.install(Update(binding.generation, 'review:commit:recording'))
        self.assertTrue(self.gui.state.feedback.visible())
        self.assertTrue(actions.check('peer'))
        self.assertEqual(self.gui.state.feedback.visible(), '')
        self.assertEqual(actions.notice('peer'), 'Checking recording…')

    def test_review_notice_is_covered_and_rejects_old_generation_results(self) -> None:
        """A late completion cannot publish feedback across authorization generations."""
        binding = self.binding(Delivery.DROP)
        self.gui.voice.reviews['peer'] = VoiceReview(binding, 640, 20)
        actions = self.gui.voice.review_actions
        self.gui.state.covered = True
        before = self.gui.state.feedback.revision
        actions.install(Update(binding.generation, 'review:commit:recording'))
        self.assertEqual(actions.notice('peer'), '')
        self.assertEqual(self.gui.state.feedback.revision, before)
        self.gui.state.covered = False
        self.assertTrue(actions.notice('peer'))
        self.gui.state.generation += 1
        self.assertEqual(actions.notice('peer'), '')
        self.assertFalse(actions.check('peer'))
        actions.install(
            Update(
                binding.generation,
                'review:commit:recording',
                VoiceCommittedEvent('Peer', 'recording', 'peer'),
            )
        )
        self.assertIn('peer', self.gui.voice.reviews)
        self.assertEqual(self.gui.state.feedback.revision, before)

    def test_interrupted_draft_is_explicitly_reclaimed_into_original_review(
        self,
    ) -> None:
        """Recovery preserves original peer, mode and context without publishing audio."""
        item = RetainedMessageEntry(
            'peer',
            'Peer',
            MessageDirectionCode.OUT,
            Delivery.LIVE,
            MessageStatusCode.DRAFT,
            ContentType.VOICE,
            'orphan',
            True,
            size_bytes=640,
            duration_ms=20,
            producer_interrupted=True,
            can_retry_finalization=True,
            context_generation=7,
        )
        self.assertTrue(self.gui.voice.recovery.claim(item))
        operation, request = self.gui.submit.call_args.args
        self.assertEqual(operation, 'capture:claim:orphan')
        request()
        self.gui.client.finalize_voice.assert_called_once_with(
            'orphan', 20, owner_token='owner'
        )
        self.gui.voice.recovery.install(
            Update(
                self.gui.state.generation,
                operation,
                VoiceFinalizedEvent(
                    'orphan',
                    640,
                    onion='peer',
                    delivery=Delivery.LIVE,
                    direction=MessageDirectionCode.OUT,
                    duration_ms=20,
                ),
            )
        )
        review = self.gui.voice.reviews['peer']
        self.assertEqual(review.binding.msg_id, 'orphan')
        self.assertEqual(review.binding.context_generation, 7)
        self.assertFalse(self.gui.voice.live_turns)
        self.gui.client.commit_voice.assert_not_called()

    def test_lock_blocks_message_media_and_retains_the_exact_unsent_review(
        self,
    ) -> None:
        """Cover never restores recording, playback or send on a held input or draft."""
        for delivery in (Delivery.DROP, Delivery.LIVE):
            with self.subTest(delivery=delivery):
                binding = self.binding(delivery)
                self.gui.voice.reviews['peer'] = VoiceReview(binding, 640, 20)
                self.gui.state.covered = True
                self.assertIsNone(self.gui.voice._scope())
                self.assertFalse(self.gui.voice.available())
                self.assertFalse(self.gui.voice.review_actions.act('peer', send=True))
                self.assertEqual(self.gui.voice.reviews['peer'].binding, binding)
        self.gui.submit.assert_not_called()
        self.gui.client.commit_voice.assert_not_called()


if __name__ == '__main__':
    unittest.main()
