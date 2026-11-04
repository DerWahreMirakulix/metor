"""PTT input arbitration, target immutability and release-required regressions."""

from dataclasses import replace
import unittest
from unittest.mock import Mock

from metor.core.api import Delivery
from metor.ui.gui.runtime.voice.press import (
    CaptureBinding,
    PressMachine,
    PressPhase,
    PressSource,
)
from metor.ui.gui.runtime.voice.inputs import InputBridge


class PressMachineTests(unittest.TestCase):
    """Deterministic input tests do not imply microphone or GUI acceptance."""

    def setUp(self) -> None:
        """Creates one released press and immutable target."""
        self.press = PressMachine()
        self.binding = CaptureBinding(
            'profile', 'epoch', 1, 'alice', Delivery.LIVE, 'one', 4
        )

    def test_repeat_and_second_source_cannot_steal_or_release(self) -> None:
        """Only the initiating source ends the exact logical turn."""
        self.assertTrue(self.press.down(PressSource.PHYSICAL, self.binding, True))
        self.assertFalse(self.press.down(PressSource.PHYSICAL, self.binding, True))
        other = replace(self.binding, peer='bob', msg_id='two')
        self.assertFalse(self.press.down(PressSource.POINTER, other, True))
        self.assertFalse(self.press.up(PressSource.POINTER))
        self.assertEqual(self.press.binding, self.binding)
        self.assertTrue(self.press.accepted(self.binding))
        self.assertTrue(self.press.up(PressSource.PHYSICAL))
        self.assertEqual(self.press.phase, PressPhase.FINALIZING)
        self.assertTrue(self.press.complete(self.binding, confirmed=True))
        self.assertEqual(self.press.phase, PressPhase.IDLE)

    def test_departure_and_capacity_recovery_require_release_then_new_down(
        self,
    ) -> None:
        """Navigation and newly available capacity never synthesize a press."""
        self.assertTrue(self.press.down(PressSource.PHYSICAL, self.binding, True))
        self.press.depart()
        self.press.accepted(self.binding)
        self.press.complete(self.binding, confirmed=True)
        self.assertEqual(self.press.phase, PressPhase.RELEASE_REQUIRED)
        self.assertFalse(self.press.down(PressSource.KEYBOARD, self.binding, True))
        self.press.up(PressSource.PHYSICAL)
        self.assertEqual(self.press.phase, PressPhase.RELEASE_REQUIRED)
        self.press.up(PressSource.KEYBOARD)
        self.assertFalse(self.press.down(PressSource.POINTER, self.binding, False))
        self.assertFalse(self.press.down(PressSource.POINTER, self.binding, True))
        self.press.up(PressSource.POINTER)
        self.assertTrue(self.press.down(PressSource.POINTER, self.binding, True))

    def test_release_before_admission_does_not_start_microphone_or_retarget(
        self,
    ) -> None:
        """A slow Begin response finalizes its own turn after an early release."""
        self.press.down(PressSource.POINTER, self.binding, True)
        self.press.up(PressSource.POINTER)
        self.assertTrue(self.press.accepted(self.binding))
        self.assertTrue(self.press.stop_requested)
        self.assertEqual(self.press.phase, PressPhase.FINALIZING)
        self.assertFalse(self.press.accepted(replace(self.binding, generation=2)))

    def test_unknown_result_and_purge_cannot_rearm_implicitly(self) -> None:
        """Unknown outcomes retain identity, and purge rejects late acceptance."""
        self.press.down(PressSource.PHYSICAL, self.binding, True)
        self.press.complete(self.binding, confirmed=False)
        self.press.up(PressSource.PHYSICAL)
        self.assertEqual(self.press.phase, PressPhase.FAILED)
        self.assertEqual(self.press.binding, self.binding)
        self.assertFalse(self.press.down(PressSource.POINTER, self.binding, True))
        self.press.up(PressSource.POINTER)
        self.press.complete(self.binding, confirmed=True)
        self.assertTrue(self.press.down(PressSource.PHYSICAL, self.binding, True))
        self.press.depart(purge=True)
        self.assertFalse(self.press.accepted(self.binding))
        self.assertTrue(self.press.aborted)

    def test_native_release_keeps_its_owner_across_view_and_profile_replacement(
        self,
    ) -> None:
        """Rebuilt controls and a replacement profile cannot adopt a held input."""
        bridge = InputBridge()
        first, replacement = Mock(), Mock()
        first.down.return_value = True
        self.assertTrue(bridge.down(PressSource.KEYBOARD, '32', first))
        self.assertFalse(bridge.down(PressSource.KEYBOARD, '32', replacement))
        self.assertFalse(bridge.up(PressSource.KEYBOARD, '13'))
        bridge.focus_lost()
        first.depart.assert_called_once()
        self.assertTrue(bridge.up(PressSource.KEYBOARD, '32'))
        first.up.assert_called_once_with(PressSource.KEYBOARD)
        replacement.up.assert_not_called()
        self.assertTrue(bridge.down(PressSource.KEYBOARD, '32', replacement))


if __name__ == '__main__':
    unittest.main()
