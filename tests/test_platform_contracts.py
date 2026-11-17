"""Checks frontend-independent observations and loss-safe physical input consumption."""

import math
import subprocess
import sys
import unittest

from metor.client.platform import (
    BatteryStatus,
    ButtonSample,
    HardwareAvailability,
    HardwareStatus,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.buttons import ButtonAction, PhysicalButtons


class PlatformContractTests(unittest.TestCase):
    """Pins unknown telemetry and input-session safety independently of any board."""

    def test_sdk_platform_import_does_not_load_frontend_or_driver(self) -> None:
        """Checks the public contract import in an independent interpreter.

        Args:
            None
        Returns:
            None
        """
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'import sys; import metor.client.platform; '
                'assert not any(name.startswith(("metor.ui.", "kivy", '
                '"sounddevice", "metor.application", "metor.data")) '
                'for name in sys.modules)',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_expired_and_discontinuous_status_becomes_unknown(self) -> None:
        """Prevents stale battery readings from being presented as current facts.

        Args:
            None
        Returns:
            None
        """
        battery = BatteryStatus(HardwareAvailability.AVAILABLE, 0.5, False, True)
        status = HardwareStatus(10.0, 20.0, battery)
        self.assertEqual(status.current_battery(10.0), battery)
        for now in (9.0, 20.0, math.nan, math.inf):
            self.assertEqual(status.current_battery(now), BatteryStatus())

    def test_malformed_and_unavailable_facts_are_rejected(self) -> None:
        """Rejects false precision, booleans as charge and non-finite bounds.

        Args:
            None
        Returns:
            None
        """
        for charge in (-0.1, 1.1, math.nan, math.inf, True):
            with self.assertRaises(ValueError):
                BatteryStatus(HardwareAvailability.AVAILABLE, charge)
        with self.assertRaises(ValueError):
            BatteryStatus(charge_fraction=0.5)
        with self.assertRaises(ValueError):
            HardwareStatus(20.0, 10.0)
        with self.assertRaises(ValueError):
            ButtonSample(0, math.nan, False, False)

    def test_initial_held_control_requires_observed_release(self) -> None:
        """Attaching an adapter cannot turn a held key into a fresh recording press.

        Args:
            None
        Returns:
            None
        """
        buttons = PhysicalButtons()
        first = buttons.observe(ButtonSample(0, 0.0, True, False))
        self.assertIn(ButtonAction.STOP_CAPTURE, first.actions)
        self.assertNotIn(ButtonAction.PTT_DOWN, first.actions)
        self.assertEqual(buttons.observe(ButtonSample(1, 1.0, True, False)).actions, ())
        buttons.observe(ButtonSample(2, 2.0, False, False))
        self.assertEqual(
            buttons.observe(ButtonSample(3, 3.0, True, False)).actions,
            (ButtonAction.PTT_DOWN,),
        )

    def test_input_gap_cancels_chord_and_cannot_trigger_purge(self) -> None:
        """Missing input cannot be interpreted as a continuously held purge chord.

        Args:
            None
        Returns:
            None
        """
        buttons = PhysicalButtons()
        buttons.observe(ButtonSample(0, 0.0, False, False))
        buttons.observe(ButtonSample(1, 1.0, True, True))
        result = buttons.observe(
            ButtonSample(3, 1.0 + GuiLimits.PURGE_SECONDS, True, True)
        )
        self.assertIn(ButtonAction.CANCEL_PURGE, result.actions)
        self.assertNotIn(ButtonAction.REQUEST_PURGE, result.actions)
        self.assertTrue(result.release_required)
        duplicate = buttons.observe(ButtonSample(3, 20.0, True, True))
        self.assertNotIn(ButtonAction.REQUEST_PURGE, duplicate.actions)
        buttons.observe(ButtonSample(4, 21.0, False, False))
        fresh = buttons.observe(ButtonSample(5, 22.0, True, True))
        self.assertIn(ButtonAction.ARM_PURGE, fresh.actions)


if __name__ == '__main__':
    unittest.main()
