"""GUI prompt, worker, and partial native teardown regressions."""

import threading
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import Mock, patch

from metor.client import FrontendLaunchContext, FrontendProfileState
from metor.core.api import (
    RuntimeSnapshotEvent,
    SelfDestructCompletedEvent,
    SelfDestructInitiatedEvent,
)
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state.mailbox import Update


class GuiExceptionLifecycleTests(unittest.TestCase):
    """Check cancellation without opening a native window or a daemon."""

    def test_close_wakes_bootstrap_prompt_before_other_teardown(self) -> None:
        """Blocked authentication must not outlive controller and host disposal.

        Args:
            None
        Returns:
            None
        """
        controller = GuiController(FrontendLaunchContext(None, Mock()), simulator=True)
        worker_finished = threading.Event()

        def wait_for_password() -> None:
            """Wait for a graphical response from the bootstrap worker.

            Args:
                None
            Returns:
                None
            """
            controller.interactions.request_session_auth_secret()
            worker_finished.set()

        worker = threading.Thread(target=wait_for_password, daemon=True)
        worker.start()
        bridge = controller.interactions
        with bridge._condition:
            self.assertTrue(
                bridge._condition.wait_for(
                    lambda: bridge._prompt is not None, timeout=5
                )
            )
        original_dispose = controller.purge.dispose

        def dispose() -> None:
            """Assert the prompt has already been cancelled before teardown.

            Args:
                None
            Returns:
                None
            """
            self.assertIsNone(bridge.prompt)
            self.assertTrue(bridge._cancelled)
            original_dispose()

        with patch.object(controller.purge, 'dispose', side_effect=dispose):
            controller.close()
        self.assertTrue(worker_finished.wait(5))
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(bridge.request_session_auth_secret())

    def test_source_loss_cancels_target_prompt_during_host_selection(self) -> None:
        """A late profile-switch factory cannot prompt after native monitor loss.

        Args:
            None
        Returns:
            None
        """
        entered = threading.Event()
        release = threading.Event()
        host = Mock()
        host.profile_state.return_value = FrontendProfileState(
            'source', True, False, False
        )

        def select(_name: str) -> FrontendProfileState:
            """Hold target selection across cancellation.

            Args:
                _name: Requested target profile.
            Returns:
                FrontendProfileState: Selected target if not cancelled.
            """
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Selection fixture timed out')
            return FrontendProfileState('target', True, False, False)

        host.select_profile.side_effect = select
        controller = GuiController(FrontendLaunchContext('source', host))
        controller.client = Mock()
        controller.state.covered = False

        def switch(_target: str, **_options: object) -> None:
            """Exercise the production factory without IPC or a native window.

            Args:
                _target: Requested target.
                _options: Public coordinator callbacks.
            Returns:
                None
            """
            factory = coordinator.call_args.args[1]
            factory('target')

        with patch(
            'metor.ui.gui.runtime.profiles.transition.ProfileRuntimeCoordinator'
        ) as coordinator:
            coordinator.return_value.switch.side_effect = switch
            try:
                self.assertTrue(controller.lifecycle.start('target'))
                self.assertTrue(entered.wait(5))
                worker = controller._worker
                assert worker is not None
                controller.fail_native_lifecycle()
                release.set()
                worker.join(5)
                self.assertFalse(worker.is_alive())
                controller.poll()
                self.assertTrue(controller.native_lifecycle_failed)
                self.assertTrue(controller.state.covered)
                self.assertIsNone(controller.client)
                host.bootstrap.assert_not_called()
            finally:
                release.set()
                controller.close()

    def test_source_loss_rejects_late_bootstrap_and_future_profile_entry(self) -> None:
        """A hydrated candidate cannot cross the permanent native-monitor fence."""
        entered, release = threading.Event(), threading.Event()
        controller = GuiController(FrontendLaunchContext('source', Mock()))
        candidate = Mock()
        snapshot = RuntimeSnapshotEvent('source', 'private-address')

        def hydrate(*_args: object) -> Mock:
            """Hold actual bootstrap orchestration just before client adoption."""
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Bootstrap fixture timed out')
            return Mock(snapshot=snapshot)

        with (
            patch.object(controller.activation, 'connect', return_value=candidate),
            patch.object(controller.activation, 'hydrate', side_effect=hydrate),
        ):
            try:
                self.assertTrue(controller.open_profile())
                self.assertTrue(entered.wait(5))
                worker = controller._worker
                assert worker is not None
                controller.fail_native_lifecycle()
                release.set()
                worker.join(5)
                self.assertFalse(worker.is_alive())
                candidate.disconnect.assert_called_once()
                controller.poll()
                self.assertIsNone(controller.client)
                self.assertIsNone(controller.state.snapshot)
                self.assertTrue(controller.state.covered)
                for simulator in (False, True):
                    controller.simulator = simulator
                    controller.close()
                    controller.resume()
                    self.assertTrue(controller.native_lifecycle_failed)
                    self.assertFalse(controller.open_profile())
                    self.assertFalse(controller.create_profile('new', 'unused'))
                    self.assertFalse(
                        controller.adopt_client(candidate, controller.state.generation)
                    )
                    work = Mock()
                    self.assertFalse(controller.submit('bootstrap', work))
                    work.assert_not_called()
                    controller.mailbox.put(
                        Update(controller.state.generation, 'bootstrap', snapshot)
                    )
                    controller.poll()
                    self.assertTrue(controller.state.covered)
                    self.assertIsNone(controller.state.snapshot)
                self.assertTrue(controller.lifecycle.start())
                self.assertTrue(controller.lifecycle.exit_ready)
            finally:
                release.set()
                controller.close()

    def test_source_loss_preserves_only_accepted_purge_observation(self) -> None:
        """Accepted destruction keeps its original observer without new commands."""
        controller = GuiController(FrontendLaunchContext(None, Mock()), simulator=True)
        detached = threading.Event()
        client = Mock()
        client.disconnect.side_effect = detached.set
        controller.client = client
        controller.voice_owner.token = 'owned-staging'
        generation = controller.state.generation
        monitor = controller.purge
        fields = {'profile': 'source', 'operation_id': 'a' * 32}
        try:
            self.assertTrue(
                monitor.observe(generation, SelfDestructInitiatedEvent(**fields))
            )
            controller.fail_native_lifecycle()
            self.assertIs(controller.purge, monitor)
            self.assertTrue(monitor.active)
            self.assertIsNone(controller.client)
            client.disconnect.assert_not_called()
            client.request.assert_not_called()
            self.assertTrue(
                monitor.observe(generation, SelfDestructCompletedEvent(**fields))
            )
            controller.poll()
            self.assertTrue(detached.wait(5))
            self.assertTrue(controller.state.covered)
            self.assertTrue(controller.native_lifecycle_failed)
            client.request.assert_not_called()
        finally:
            controller.close()

    def test_cancelled_bootstrap_reports_rejection_not_silent_none(self) -> None:
        """The explicit bootstrap cancellation outcome reaches the GUI mailbox.

        Args:
            None
        Returns:
            None
        """
        controller = GuiController(FrontendLaunchContext(None, Mock()), simulator=True)
        try:
            self.assertTrue(controller.submit('bootstrap', lambda: None))
            worker = controller._worker
            assert worker is not None
            worker.join(5)
            self.assertFalse(worker.is_alive())
            controller.poll()
            self.assertEqual(
                controller.state.status, 'Profile opening was cancelled or rejected.'
            )
        finally:
            controller.close()

    def test_caught_worker_failure_has_safe_debug_location(self) -> None:
        """Keep the GUI recovery status and reveal only source-checked debug data.

        Args:
            None
        Returns:
            None
        """
        sentinel = 'credential-private'
        custom_error = type(sentinel, (Exception,), {})
        controller = GuiController(
            FrontendLaunchContext(None, Mock(), debug=True), simulator=True
        )
        output = StringIO()

        def fail() -> None:
            """Raise an untrusted exception inside a controlled worker.

            Args:
                None
            Returns:
                None
            """
            raise custom_error(sentinel)

        try:
            with redirect_stderr(output):
                self.assertTrue(controller.submit('bootstrap', fail))
                worker = controller._worker
                assert worker is not None
                worker.join(5)
            controller.poll()
            self.assertIn('Profile opening failed', controller.state.status)
            self.assertIn('Metor GUI worker [work]: Exception.', output.getvalue())
            self.assertIn('runtime/operations.py:', output.getvalue())
            self.assertNotIn(sentinel, output.getvalue())
        finally:
            controller.close()


if __name__ == '__main__':
    unittest.main()
