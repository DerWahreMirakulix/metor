"""Privacy, finite admission and invalid projection regressions without native widgets."""

from dataclasses import replace
import unittest

from metor.ui.gui.accessibility.model import (
    AccessibleAction,
    AccessibleNode,
    AccessibleRole,
    AccessibleSnapshot,
    AccessibleState,
)
from metor.ui.gui.state import GuiState
from metor.ui.gui.constants import GuiLimits


class AccessibilityTests(unittest.TestCase):
    """Verifies the thread boundary independently of installed native AT adapters."""

    def test_privacy_fence_revokes_tree_and_queued_actions(self) -> None:
        """Cover assignment synchronously forgets private nodes and pending invocation.

        Args:
            None
        Returns:
            None
        """
        model = AccessibleState()
        node = AccessibleNode(
            1, AccessibleRole.BUTTON, 'Private alias', (0, 0, 48, 48), clickable=True
        )
        model.publish(AccessibleSnapshot((node,)))
        self.assertTrue(model.request(1, AccessibleAction.CLICK))
        state = GuiState()
        state.privacy_fence = model.revoke
        state.covered = True
        self.assertEqual(model.read().nodes, ())
        self.assertIsNone(model.take())
        self.assertFalse(model.request(1, AccessibleAction.CLICK))

    def test_password_value_and_invalid_bounds_are_rejected(self) -> None:
        """Native projection cannot disclose a secret or pass nonfinite geometry.

        Args:
            None
        Returns:
            None
        """
        model = AccessibleState()
        node = AccessibleNode(1, AccessibleRole.PASSWORD, 'Password', (0, 0, 48, 48))
        for invalid in (
            replace(node, value='secret'),
            replace(node, bounds=(0, 0, float('nan'), 1)),
            replace(node, identity=0),
        ):
            with self.assertRaises(ValueError):
                model.publish(AccessibleSnapshot((invalid,)))
        model.publish(AccessibleSnapshot((node,)))
        self.assertFalse(model.request(1, AccessibleAction.SET_VALUE, 'secret'))
        self.assertFalse(model.request(1, AccessibleAction.CLICK))

    def test_only_advertised_current_targets_accept_actions(self) -> None:
        """Disabled, vanished and nonclickable PTT-style controls cannot be invoked.

        Args:
            None
        Returns:
            None
        """
        model = AccessibleState()
        node = AccessibleNode(
            1, AccessibleRole.BUTTON, 'Hold to talk', (0, 0, 48, 48), focusable=True
        )
        model.publish(AccessibleSnapshot((node,)))
        self.assertTrue(model.request(1, AccessibleAction.FOCUS))
        self.assertFalse(model.request(1, AccessibleAction.CLICK))
        model.publish(AccessibleSnapshot((replace(node, enabled=False),)))
        self.assertFalse(model.request(1, AccessibleAction.FOCUS))
        model.revoke()
        self.assertIsNone(model.take())

    def test_editor_replacements_are_bounded_and_revocable(self) -> None:
        """Text actions retain only an admitted value and disappear at the privacy fence.

        Args:
            None
        Returns:
            None
        """
        model = AccessibleState()
        node = AccessibleNode(
            1, AccessibleRole.TEXT, 'Message', (0, 0, 48, 48), editable=True
        )
        model.publish(AccessibleSnapshot((node,)))
        self.assertFalse(
            model.request(
                1, AccessibleAction.SET_VALUE, 'x' * (GuiLimits.TEXT_BYTES + 1)
            )
        )
        self.assertTrue(model.request(1, AccessibleAction.SET_VALUE, 'ordinary text'))
        request = model.take()
        self.assertIsNotNone(request)
        self.assertEqual(request.value, 'ordinary text')
        self.assertTrue(model.request(1, AccessibleAction.SET_VALUE, 'pending text'))
        model.revoke()
        self.assertIsNone(model.take())


if __name__ == '__main__':
    unittest.main()
