"""GUI prompt, worker, and partial native teardown regressions."""

import threading
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import Mock, patch

from metor.client import FrontendLaunchContext, FrontendProfileState
from metor.ui.gui.runtime import GuiController


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

    def test_close_cancels_target_prompt_created_during_host_selection(self) -> None:
        """A late profile-switch factory cannot prompt after GUI close.

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
                controller.close()
                release.set()
                controller._worker.join(5)
                self.assertFalse(controller._worker.is_alive())
                host.bootstrap.assert_not_called()
            finally:
                release.set()
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
            controller._worker.join(5)
            self.assertFalse(controller._worker.is_alive())
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
                controller._worker.join(5)
            controller.poll()
            self.assertIn('Profile opening failed', controller.state.status)
            self.assertIn('Metor GUI worker [work]: Exception.', output.getvalue())
            self.assertIn('runtime/controller.py:', output.getvalue())
            self.assertNotIn(sentinel, output.getvalue())
        finally:
            controller.close()


if __name__ == '__main__':
    unittest.main()
