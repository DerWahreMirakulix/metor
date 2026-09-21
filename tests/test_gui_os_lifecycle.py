"""Native desktop lifecycle source and bounded GUI handoff contracts."""

import unittest
from unittest.mock import Mock, patch

from metor.ui.gui.platform.lifecycle import (
    DesktopLifecycleEvent,
    LifecycleCoordinator,
    LifecycleInbox,
    WindowsLifecycleSource,
)


class LifecycleInboxTests(unittest.TestCase):
    """Ensures native event bursts cannot create an unbounded GUI queue."""

    def test_inbox_is_bounded_and_never_loses_departure_to_resume(self) -> None:
        inbox = LifecycleInbox(limit=2)

        self.assertTrue(inbox.put(DesktopLifecycleEvent.SUSPEND))
        self.assertTrue(inbox.put(DesktopLifecycleEvent.RESUME))
        self.assertFalse(inbox.put(DesktopLifecycleEvent.RESUME))
        self.assertTrue(inbox.put(DesktopLifecycleEvent.LOCK))

        self.assertEqual(
            inbox.take_all(),
            (DesktopLifecycleEvent.SUSPEND, DesktopLifecycleEvent.LOCK),
        )
        self.assertEqual(inbox.take_all(), ())


class WindowsLifecycleSourceTests(unittest.TestCase):
    """Maps actual WTS and power message identifiers without touching Kivy's HWND."""

    def test_wndproc_messages_publish_lock_suspend_and_resume(self) -> None:
        publish = Mock()
        source = WindowsLifecycleSource(publish)

        with patch.object(source, '_default_window_proc', return_value=17):
            self.assertEqual(source._window_proc(4, 0x02B1, 0x7, 0), 17)
            self.assertEqual(source._window_proc(4, 0x0218, 0x4, 0), 17)
            self.assertEqual(source._window_proc(4, 0x02B1, 0x8, 0), 17)
            self.assertEqual(source._window_proc(4, 0x0218, 0x12, 0), 17)

        self.assertEqual(
            [call.args[0] for call in publish.call_args_list],
            [
                DesktopLifecycleEvent.LOCK,
                DesktopLifecycleEvent.SUSPEND,
                DesktopLifecycleEvent.RESUME,
                DesktopLifecycleEvent.RESUME,
            ],
        )

    def test_unrelated_window_message_is_not_promoted_to_lifecycle(self) -> None:
        publish = Mock()
        source = WindowsLifecycleSource(publish)

        with patch.object(source, '_default_window_proc', return_value=23):
            result = source._window_proc(4, 0x0007, 0, 0)

        self.assertEqual(result, 23)
        publish.assert_not_called()


class ApplicationLifecycleFenceTests(unittest.TestCase):
    """Checks the synchronous GUI-thread privacy and media boundary."""

    def test_lock_revokes_native_projection_before_controller_suspend(self) -> None:
        order: list[str] = []
        coordinator = LifecycleCoordinator(
            lambda: order.append('revoke'),
            lambda: order.append('suspend'),
            lambda: order.append('resume'),
            lambda: order.append('refresh'),
        )

        coordinator.apply(DesktopLifecycleEvent.LOCK)

        self.assertEqual(order, ['revoke', 'suspend', 'refresh'])

    def test_resume_does_not_republish_or_synthesize_focus(self) -> None:
        revoke, suspend, resume, refresh = Mock(), Mock(), Mock(), Mock()
        coordinator = LifecycleCoordinator(revoke, suspend, resume, refresh)

        coordinator.apply(DesktopLifecycleEvent.RESUME)

        resume.assert_called_once_with()
        suspend.assert_not_called()
        revoke.assert_not_called()
        refresh.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
