"""Device lifecycle integration over typed ports without real purge or host shutdown."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from metor.client import FrontendLaunchContext, FrontendProfileState
from metor.client.platform import (
    BatteryStatus,
    ButtonSample,
    HardwareAvailability,
    HardwareStatus,
    PlatformActionResult,
    PlatformBindings,
)
from metor.core.api import (
    ClientRestrictedEvent,
    ClientUnlockMethod,
    RestrictClientCommand,
    RuntimeSnapshotEvent,
    SelfDestructCompletedEvent,
    SelfDestructInitiatedEvent,
    SelfDestructSafeEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform import read_configuration
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.device import DevicePhase
from metor.ui.gui.state import Route
from metor.utils import open_private_binary_file


def _write_private_configuration(path: Path, content: str) -> None:
    """Writes one native-private UTF-8 device configuration fixture.

    Args:
        path (Path): Exact temporary configuration path.
        content (str): TOML fixture content.

    Returns:
        None
    """
    with open_private_binary_file(path) as handle:
        handle.write(content.encode('utf-8'))


class DeviceLifecycleTests(unittest.TestCase):
    """Proves that physical intent, Core safety and actuation remain separate."""

    def setUp(self) -> None:
        """Creates one local typed deployment with inert test ports.

        Args:
            None
        Returns:
            None
        """
        self.receiver = None
        self.subscription = Mock()
        self.inputs = Mock()

        def subscribe(receiver: object) -> Mock:
            """Retains the callback like a registered driver subscription.

            Args:
                receiver: Complete-sample callback.
            Returns:
                Mock: Explicit subscription owner.
            """
            self.receiver = receiver
            return self.subscription

        self.inputs.subscribe.side_effect = subscribe
        self.shutdown = Mock()
        self.shutdown.request_shutdown.return_value = PlatformActionResult.ACCEPTED
        self.indicator = Mock()
        self.haptics = Mock()
        self.bindings = PlatformBindings(
            'fixture',
            self.inputs,
            self.shutdown,
            indicator=self.indicator,
            haptics=self.haptics,
        )
        self.host = Mock()
        self.host.profile_state.return_value = FrontendProfileState(
            'local', True, False, True
        )
        self.host.list_profiles.return_value = (
            FrontendProfileState('local', True, False, True),
        )
        context = FrontendLaunchContext('local', self.host, platform=self.bindings)
        self.gui = GuiController(context)
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            profile='local', onion='', epoch='device-fixture'
        )
        self.gui.state.covered = False
        self.gui.state.route = Route('V06')
        self.client = Mock()
        self.client.prepare_profile_exit.return_value = True
        self.gui.client = self.client

    def sample(
        self,
        sequence: int,
        observed_at: float,
        *,
        ptt: bool = False,
        power: bool = False,
    ) -> None:
        """Queues one complete physical state and drains the UI-thread consumer.

        Args:
            sequence: Strict adapter sequence.
            observed_at: Monotonic driver timestamp.
            ptt: Current physical PTT level.
            power: Current physical Power level.
        Returns:
            None
        """
        self.gui.device.receive(
            ButtonSample(sequence, observed_at, ptt=ptt, power=power)
        )
        self.gui.device.poll()

    def settle(self) -> None:
        """Waits for the one GUI worker and installs its result.

        Args:
            None
        Returns:
            None
        """
        worker = self.gui._worker
        self.assertIsNotNone(worker)
        assert worker is not None
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.gui.poll()

    def settle_purge_shutdown(self) -> None:
        """Drains the dedicated post-purge actuator worker.

        Args:
            None
        Returns:
            None
        """
        self.gui.device.poll()
        worker = self.gui.device._purge_shutdown_worker
        self.assertIsNotNone(worker)
        assert worker is not None
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.gui.device.poll()

    def test_configuration_requires_matching_injected_adapter(self) -> None:
        """A physical file activates only its exact preconstructed typed binding.

        Args:
            None
        Returns:
            None
        """
        source = """schema_version = 1
[display]
adapter = 'fixture'
width_px = 480
height_px = 800
[input]
adapter = 'fixture'
ptt_binding = 'ptt'
power_binding = 'power'
touch = true
[power]
adapter = 'fixture'
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            _write_private_configuration(path, source)
            config = read_configuration(str(path), False, self.bindings)
        self.assertEqual(config.mode, 'device')
        self.assertEqual(config.logical_size, (480, 800))
        self.assertTrue(config.power)
        self.assertIs(config.activate_platform(self.bindings).shutdown, self.shutdown)

    def test_undeclared_optional_ports_are_not_activated(self) -> None:
        """A matching deployment cannot bypass optional capability declarations.

        Args:
            None
        Returns:
            None
        """
        source = """schema_version = 1
[display]
adapter = 'fixture'
width_px = 480
height_px = 800
[input]
adapter = 'fixture'
ptt_binding = 'ptt'
power_binding = 'power'
touch = true
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'device.toml'
            _write_private_configuration(path, source)
            config = read_configuration(str(path), False, self.bindings)
        active = config.activate_platform(self.bindings)
        self.assertIsNotNone(active)
        assert active is not None
        self.assertIsNone(active.shutdown)
        self.assertIsNone(active.indicator)
        self.assertIsNone(active.haptics)
        self.assertIs(active.inputs, self.inputs)

    def test_cached_hardware_status_is_read_without_input_or_actuation(self) -> None:
        """Battery facts use their own freshness contract and invoke no action port.

        Args:
            None
        Returns:
            None
        """
        status = Mock()
        status.snapshot.return_value = HardwareStatus(
            9.0,
            11.0,
            BatteryStatus(
                HardwareAvailability.AVAILABLE,
                charge_fraction=0.75,
                charging=True,
                external_power=True,
            ),
        )
        self.gui.device.bindings = PlatformBindings(
            'fixture', self.inputs, self.shutdown, status=status
        )
        self.gui.device.status = self.gui.device.status.__class__(status)
        with patch(
            'metor.ui.gui.runtime.device.controller.time.monotonic', return_value=10.0
        ):
            self.assertTrue(self.gui.device.poll())
        self.assertEqual(self.gui.device.battery_status, 'Battery 75% · Charging')
        self.shutdown.request_shutdown.assert_not_called()
        self.inputs.subscribe.assert_not_called()

    def test_long_power_opens_menu_and_explicit_action_prepares_before_shutdown(
        self,
    ) -> None:
        """Long Power has no actuator effect until explicit safe preparation succeeds.

        Args:
            None
        Returns:
            None
        """
        order: list[str] = []

        def prepare() -> bool:
            """Records confirmed Core preparation.

            Args:
                None
            Returns:
                bool: Confirmed fixture outcome.
            """
            order.append('prepare')
            return True

        def shutdown() -> PlatformActionResult:
            """Records fixed actuator admission.

            Args:
                None
            Returns:
                PlatformActionResult: Accepted fixture outcome.
            """
            order.append('shutdown')
            return PlatformActionResult.ACCEPTED

        self.client.prepare_profile_exit.side_effect = prepare
        self.client.disconnect.side_effect = lambda: order.append('disconnect')
        self.shutdown.request_shutdown.side_effect = shutdown
        self.sample(0, 0)
        self.sample(1, 1, power=True)
        self.sample(2, 1 + GuiLimits.POWER_SECONDS, power=True)
        self.assertEqual(self.gui.device.phase, DevicePhase.POWER_MENU)
        self.shutdown.request_shutdown.assert_not_called()
        self.assertTrue(self.gui.device.request_poweroff())
        self.settle()
        self.assertEqual(order, ['prepare', 'disconnect', 'shutdown'])
        self.assertEqual(self.gui.device.phase, DevicePhase.POWERING_OFF)
        self.assertEqual(self.gui.state.route, Route('V21'))

    def test_remote_binding_and_missing_restricted_grant_never_reach_actuators(
        self,
    ) -> None:
        """Remote ownership and a locked session without its grant fail closed.

        Args:
            None
        Returns:
            None
        """
        self.host.profile_state.return_value = FrontendProfileState(
            'local', True, True, True
        )
        self.assertTrue(self.gui.device.open_power_menu())
        self.assertTrue(self.gui.device.request_poweroff())
        self.settle()
        self.shutdown.request_shutdown.assert_not_called()
        self.client.prepare_profile_exit.assert_not_called()

        self.gui.device.phase = DevicePhase.IDLE
        self.gui.state.route = Route('V05')
        self.gui.state.covered = True
        self.gui.state.snapshot = None
        self.gui.security.restriction = ClientRestrictedEvent(
            ClientUnlockMethod.PROFILE_PASSWORD, device_lifecycle=False
        )
        self.sample(0, 10)
        self.sample(1, 11, ptt=True, power=True)
        self.sample(2, 11 + GuiLimits.PURGE_SECONDS, ptt=True, power=True)
        self.assertEqual(self.gui.device.phase, DevicePhase.PURGE_UNAVAILABLE)
        self.client.request.assert_not_called()

    def test_competing_local_runtime_prevents_host_shutdown(self) -> None:
        """A second active local profile fails before Core preparation or actuation.

        Args:
            None
        Returns:
            None
        """
        self.host.list_profiles.return_value = (
            FrontendProfileState('local', True, False, True),
            FrontendProfileState('other', True, False, True),
        )
        self.assertTrue(self.gui.device.open_power_menu())
        self.assertTrue(self.gui.device.request_poweroff())
        self.settle()
        self.client.prepare_profile_exit.assert_not_called()
        self.shutdown.request_shutdown.assert_not_called()
        self.assertEqual(self.gui.device.phase, DevicePhase.POWER_FAILED)

    def test_device_lock_requests_scoped_lifecycle_grant(self) -> None:
        """Only a configured device asks Core to retain prior-authenticated lifecycle scope.

        Args:
            None
        Returns:
            None
        """
        self.client.request.return_value = ClientRestrictedEvent(
            ClientUnlockMethod.PROFILE_PASSWORD, device_lifecycle=True
        )
        self.assertTrue(self.gui.security.lock())
        self.gui.security.poll()
        worker = self.gui._worker
        self.assertIsNotNone(worker)
        assert worker is not None
        worker.join(3)
        command = self.client.request.call_args.args[0]
        self.assertIsInstance(command, RestrictClientCommand)
        self.assertTrue(command.device_lifecycle)

    def test_purge_shutdown_waits_for_combined_safe_and_terminal_result(self) -> None:
        """Initiated, EOF and Safe alone cannot invoke the shutdown actuator.

        Args:
            None
        Returns:
            None
        """
        operation = 'a' * (2 * GuiLimits.MESSAGE_ID_BYTES)
        with patch('metor.ui.gui.runtime.purge.time.monotonic', return_value=10.0):
            self.assertTrue(
                self.gui.purge.observe(
                    0,
                    SelfDestructInitiatedEvent(profile='local', operation_id=operation),
                )
            )
        self.gui.purge.poll(now=10.0)
        self.gui.device.poll()
        self.shutdown.request_shutdown.assert_not_called()
        with patch('metor.ui.gui.runtime.purge.time.monotonic', return_value=10.0):
            self.assertTrue(
                self.gui.purge.observe(
                    0,
                    SelfDestructSafeEvent(profile='local', operation_id=operation),
                )
            )
        self.gui.purge.lost(0)
        self.gui.purge.poll(now=10.0 + GuiLimits.PURGE_CLEANUP_SECONDS - 0.001)
        self.gui.device.poll()
        self.shutdown.request_shutdown.assert_not_called()
        self.gui.purge.poll(now=10.0 + GuiLimits.PURGE_CLEANUP_SECONDS)
        self.settle_purge_shutdown()
        self.shutdown.request_shutdown.assert_called_once_with()

    def test_terminal_cleanup_after_safe_requests_shutdown_once(self) -> None:
        """The exact Safe plus terminal cleanup chain invokes one fixed request.

        Args:
            None
        Returns:
            None
        """
        operation = 'b' * (2 * GuiLimits.MESSAGE_ID_BYTES)
        with patch('metor.ui.gui.runtime.purge.time.monotonic', return_value=20.0):
            self.gui.purge.observe(
                0,
                SelfDestructInitiatedEvent(profile='local', operation_id=operation),
            )
            self.gui.purge.observe(
                0, SelfDestructSafeEvent(profile='local', operation_id=operation)
            )
            self.gui.purge.observe(
                0,
                SelfDestructCompletedEvent(profile='local', operation_id=operation),
            )
        self.gui.purge.poll(now=20.0)
        self.settle_purge_shutdown()
        self.gui.purge.poll(now=20.0)
        self.shutdown.request_shutdown.assert_called_once_with()
        self.assertIn('Powering off', self.gui.purge.detail)

    def test_transport_loss_before_queued_safe_still_waits_cleanup_bound(self) -> None:
        """A later Safe event cannot inherit an earlier EOF as terminal cleanup.

        Args:
            None
        Returns:
            None
        """
        operation = 'c' * (2 * GuiLimits.MESSAGE_ID_BYTES)
        with patch('metor.ui.gui.runtime.purge.time.monotonic', return_value=30.0):
            self.gui.purge.observe(
                0,
                SelfDestructInitiatedEvent(profile='local', operation_id=operation),
            )
        self.gui.purge.lost(0)
        with patch('metor.ui.gui.runtime.purge.time.monotonic', return_value=31.0):
            self.gui.purge.observe(
                0, SelfDestructSafeEvent(profile='local', operation_id=operation)
            )
        self.gui.purge.poll(now=31.0)
        self.gui.device.poll()
        self.shutdown.request_shutdown.assert_not_called()
        self.gui.purge.poll(now=31.0 + GuiLimits.PURGE_CLEANUP_SECONDS)
        self.settle_purge_shutdown()
        self.shutdown.request_shutdown.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
