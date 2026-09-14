"""Deterministic physical-input arbitration tests without GPIO, profile or shutdown access."""

import unittest

from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.buttons import ButtonAction, PhysicalButtons


class PhysicalButtonTests(unittest.TestCase):
    """Exercises complete physical state snapshots, never global desktop shortcuts."""

    def test_simultaneous_chord_never_admits_ptt_and_triggers_once(self) -> None:
        """The shared edge wins before ordinary PTT and remains consumed through repeats."""
        buttons = PhysicalButtons()
        result = buttons.sample(ptt=True, power=True, now=0)
        self.assertEqual(
            result.actions, (ButtonAction.STOP_CAPTURE, ButtonAction.ARM_PURGE)
        )
        before = buttons.sample(
            ptt=True, power=True, now=GuiLimits.PURGE_SECONDS - 0.001
        )
        self.assertFalse(before.actions)
        self.assertLess(before.progress, 1)
        result = buttons.sample(ptt=True, power=True, now=GuiLimits.PURGE_SECONDS)
        self.assertEqual(result.actions, (ButtonAction.REQUEST_PURGE,))
        self.assertFalse(buttons.sample(ptt=True, power=True, now=20).actions)
        self.assertFalse(buttons.sample(ptt=False, power=True, now=21).actions)
        self.assertFalse(buttons.sample(ptt=False, power=False, now=22).actions)

    def test_both_edge_orders_interrupt_and_require_continuous_chord_time(self) -> None:
        """A previously admitted turn is stopped; time before the second key never counts."""
        for ptt_first in (True, False):
            with self.subTest(ptt_first=ptt_first):
                buttons = PhysicalButtons()
                result = buttons.sample(ptt=ptt_first, power=not ptt_first, now=0)
                self.assertEqual(
                    result.actions, (ButtonAction.PTT_DOWN,) if ptt_first else ()
                )
                result = buttons.sample(ptt=True, power=True, now=1)
                self.assertIn(ButtonAction.STOP_CAPTURE, result.actions)
                self.assertIn(ButtonAction.ARM_PURGE, result.actions)
                self.assertFalse(buttons.sample(ptt=True, power=True, now=5).actions)
                self.assertEqual(
                    buttons.sample(ptt=True, power=True, now=6).actions,
                    (ButtonAction.REQUEST_PURGE,),
                )

    def test_cancelled_chord_consumes_all_delayed_edges(self) -> None:
        """Repressing one key while the other stays down cannot resume arming or recording."""
        buttons = PhysicalButtons()
        buttons.sample(ptt=True, power=True, now=0)
        result = buttons.sample(ptt=False, power=True, now=1)
        self.assertEqual(result.actions, (ButtonAction.CANCEL_PURGE,))
        for ptt, power, now in ((True, True, 2), (True, False, 3), (False, False, 4)):
            self.assertFalse(buttons.sample(ptt=ptt, power=power, now=now).actions)
        result = buttons.sample(ptt=True, power=False, now=5)
        self.assertEqual(result.actions, (ButtonAction.PTT_DOWN,))

    def test_short_release_locks_and_long_press_only_opens_menu_once(self) -> None:
        """Opening a menu is a separate non-shutdown action and release adds no short action."""
        buttons = PhysicalButtons()
        buttons.sample(ptt=False, power=True, now=0)
        self.assertEqual(
            buttons.sample(ptt=False, power=False, now=1).actions, (ButtonAction.LOCK,)
        )
        buttons.sample(ptt=False, power=True, now=2)
        self.assertEqual(
            buttons.sample(ptt=False, power=True, now=4).actions,
            (ButtonAction.POWER_MENU,),
        )
        self.assertFalse(buttons.sample(ptt=False, power=True, now=5).actions)
        self.assertFalse(buttons.sample(ptt=False, power=False, now=6).actions)

    def test_input_loss_requires_observed_release_and_rejects_invalid_clock(
        self,
    ) -> None:
        """Unplug/resume and malformed timing never synthesize a fresh down or purge threshold."""
        buttons = PhysicalButtons()
        buttons.sample(ptt=True, power=False, now=1)
        self.assertEqual(buttons.lost().actions, (ButtonAction.STOP_CAPTURE,))
        self.assertFalse(buttons.sample(ptt=True, power=False, now=2).actions)
        buttons.sample(ptt=False, power=False, now=3)
        self.assertEqual(
            buttons.sample(ptt=True, power=False, now=4).actions,
            (ButtonAction.PTT_DOWN,),
        )
        self.assertIn(
            ButtonAction.STOP_CAPTURE,
            buttons.sample(ptt=True, power=True, now=float('nan')).actions,
        )
        self.assertFalse(buttons.sample(ptt=True, power=True, now=100).actions)


if __name__ == '__main__':
    unittest.main()
