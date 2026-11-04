"""Privacy and lifetime checks for action feedback and conversation navigation."""

import unittest

from metor.core.api import Delivery
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import GuiState, Route
from metor.ui.gui.state.feedback import ActionFeedback


class FeedbackTests(unittest.TestCase):
    """Verifies one temporary result without inventing notification history."""

    def test_repeated_action_result_has_a_new_bounded_display_interval(self) -> None:
        """The same successful action can be reported again after its first expiry."""
        feedback = ActionFeedback()
        feedback.publish('Contact saved', now=10)
        self.assertEqual(feedback.visible(now=10), 'Contact saved')
        self.assertEqual(feedback.visible(now=10 + GuiLimits.FEEDBACK_SECONDS), '')
        first_revision = feedback.revision
        feedback.publish('Contact saved', now=20)
        self.assertGreater(feedback.revision, first_revision)
        self.assertEqual(feedback.visible(now=20), 'Contact saved')
        feedback.clear()
        self.assertEqual(feedback.visible(now=20), '')

    def test_cover_and_navigation_revoke_action_results(self) -> None:
        """A previous result cannot follow private content across views or a cover."""
        state = GuiState()
        state.covered = False
        state.status = 'Contact saved'
        self.assertEqual(state.feedback.visible(), 'Contact saved')
        state.covered = True
        self.assertEqual(state.feedback.visible(), '')
        state.covered = False
        state.status = 'Contact saved'
        state.navigate(Route('V17'))
        self.assertEqual(state.feedback.visible(), '')

    def test_switching_conversation_tabs_preserves_the_originating_back_target(
        self,
    ) -> None:
        """DROP/LIVE are projections of one conversation, not navigation ancestors."""
        state = GuiState()
        root = Route('V06')
        state.route = root
        peer = 'a' * 56
        state.navigate(Route('V08', peer, Delivery.DROP))
        for delivery in (Delivery.LIVE, Delivery.DROP, Delivery.LIVE):
            state.navigate(
                Route('V08' if delivery is Delivery.DROP else 'V09', peer, delivery)
            )
        self.assertEqual(state.back_stack, [root])
        state.back()
        self.assertEqual(state.route, root)

    def test_contact_origin_and_different_conversation_remain_real_back_targets(
        self,
    ) -> None:
        """Changing mode preserves Contacts; opening another peer retains history."""
        state = GuiState()
        contacts = Route('V12')
        state.route = contacts
        first, second = 'a' * 56, 'b' * 56
        state.navigate(Route('V08', first, Delivery.DROP))
        state.navigate(Route('V09', first, Delivery.LIVE))
        state.navigate(Route('V08', second, Delivery.DROP))
        state.back()
        self.assertEqual(state.route, Route('V09', first, Delivery.LIVE))
        state.back()
        self.assertEqual(state.route, contacts)
