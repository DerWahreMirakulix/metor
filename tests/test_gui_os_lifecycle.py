"""Native desktop lifecycle source and bounded GUI handoff contracts."""

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.lifecycle import (
    DesktopLifecycleEvent,
    LifecycleCoordinator,
    LifecycleHandoff,
    LifecycleInbox,
    LinuxLifecycleSource,
    WindowsLifecycleSource,
    create_desktop_lifecycle_source,
)
from metor.ui.gui.platform.linux_lifecycle import LinuxLifecycleBinding


class _FakeMessage:
    """Retains exact D-Bus call fields for the controlled adapter."""

    def __init__(self, **fields: object) -> None:
        """Store one method or signal payload.

        Args:
            **fields (object): D-Bus message attributes.

        Returns:
            None
        """
        self.__dict__.update(fields)


class _FakeBus:
    """Controlled asynchronous bus with explicit provider and loss state."""

    def __init__(self, kind: str, *, login_available: bool, locked: bool) -> None:
        """Create a system or empty session bus.

        Args:
            kind (str): Bus identity.
            login_available (bool): Whether logind owns its well-known name.
            locked (bool): Initial own-session ``LockedHint``.

        Returns:
            None
        """
        self.kind = kind
        self.login_available = login_available
        self.locked = locked
        self.calls: list[_FakeMessage] = []
        self.handler: object = None
        self.lost = threading.Event()
        self.connect_started = threading.Event()
        self.connect_gate: threading.Event | None = None
        self.disconnected = False

    async def connect(self) -> '_FakeBus':
        """Return the already controlled bus.

        Args:
            None

        Returns:
            _FakeBus: This bus.
        """
        self.connect_started.set()
        while self.connect_gate is not None and not self.connect_gate.is_set():
            await asyncio.sleep(0.001)
        return self

    async def call(self, message: _FakeMessage) -> SimpleNamespace:
        """Return deterministic method replies for lifecycle discovery.

        Args:
            message (_FakeMessage): Exact call request.

        Returns:
            SimpleNamespace: Controlled reply.
        """
        self.calls.append(message)
        if message.member == 'GetNameOwner':
            service = message.body[0]
            if (
                self.kind == 'system'
                and service == LinuxLifecycleBinding.LOGIN_SERVICE
                and self.login_available
            ):
                return SimpleNamespace(message_type='method_return', body=[':1.42'])
            return SimpleNamespace(message_type='error', body=[])
        if message.member == 'GetSessionByPID':
            return SimpleNamespace(
                message_type='method_return',
                body=['/org/freedesktop/login1/session/_42'],
            )
        if message.member == 'Get':
            return SimpleNamespace(
                message_type='method_return',
                body=[SimpleNamespace(value=self.locked)],
            )
        if message.member == 'AddMatch':
            return SimpleNamespace(message_type='method_return', body=[])
        return SimpleNamespace(message_type='error', body=[])

    def add_message_handler(self, handler: object) -> None:
        """Retain the installed low-level message handler.

        Args:
            handler (object): Source callback.

        Returns:
            None
        """
        self.handler = handler

    async def wait_for_disconnect(self) -> None:
        """Wait cooperatively until the test declares provider loss.

        Args:
            None

        Returns:
            None
        """
        while not self.lost.is_set():
            await asyncio.sleep(0.001)

    def disconnect(self) -> None:
        """Record bounded source cleanup.

        Args:
            None

        Returns:
            None
        """
        self.disconnected = True


class _FakeDbusModules:
    """Supplies dbus-next module surfaces to the production source."""

    def __init__(self, *, login_available: bool = True, locked: bool = False) -> None:
        """Create controlled system and session buses.

        Args:
            login_available (bool): Whether system logind exists.
            locked (bool): Initial own-session lock hint.

        Returns:
            None
        """
        self.system = _FakeBus('system', login_available=login_available, locked=locked)
        self.session = _FakeBus(
            'session', login_available=login_available, locked=locked
        )
        self.constants = SimpleNamespace(
            BusType=SimpleNamespace(SYSTEM='system', SESSION='session'),
            MessageType=SimpleNamespace(
                SIGNAL='signal',
                METHOD_RETURN='method_return',
                ERROR='error',
            ),
        )
        self.aio = SimpleNamespace(MessageBus=self._message_bus)
        self.message = SimpleNamespace(Message=_FakeMessage)

    def _message_bus(self, *, bus_type: str) -> _FakeBus:
        """Return the requested controlled bus.

        Args:
            bus_type (str): Fake bus type constant.

        Returns:
            _FakeBus: Matching bus.
        """
        return self.system if bus_type == 'system' else self.session

    def import_module(self, name: str) -> object:
        """Resolve only the three dbus-next modules used by production.

        Args:
            name (str): Requested module name.

        Returns:
            object: Controlled module surface.
        """
        return {
            'dbus_next.aio': self.aio,
            'dbus_next.constants': self.constants,
            'dbus_next.message': self.message,
        }[name]


class LifecycleInboxTests(unittest.TestCase):
    """Ensures native event bursts cannot create an unbounded GUI queue."""

    def test_inbox_is_bounded_and_never_loses_departure_to_resume(self) -> None:
        inbox = LifecycleInbox(limit=2)

        self.assertTrue(inbox.put(DesktopLifecycleEvent.SUSPEND))
        self.assertFalse(inbox.put(DesktopLifecycleEvent.RESUME))
        self.assertFalse(inbox.put(DesktopLifecycleEvent.RESUME))
        self.assertFalse(inbox.put(DesktopLifecycleEvent.LOCK))

        self.assertEqual(
            inbox.take_all(),
            (DesktopLifecycleEvent.SUSPEND, DesktopLifecycleEvent.LOCK),
        )
        self.assertEqual(inbox.take_all(), ())

    def test_event_burst_has_one_wakeup_and_rearms_during_drain(self) -> None:
        """A native burst cannot create a callback per event or lose a late event.

        Args:
            None

        Returns:
            None
        """
        inbox = LifecycleInbox()
        wakeups = 0
        for index in range(10_000):
            event = (
                DesktopLifecycleEvent.LOCK
                if index % 2
                else DesktopLifecycleEvent.RESUME
            )
            wakeups += int(inbox.put(event))

        self.assertEqual(wakeups, 1)
        self.assertLessEqual(len(inbox.take_all()), 4)
        self.assertTrue(inbox.put(DesktopLifecycleEvent.SUSPEND))
        self.assertEqual(inbox.take_all(), (DesktopLifecycleEvent.SUSPEND,))

    def test_closed_inbox_rejects_late_source_events(self) -> None:
        """Closing during startup leaves no queued callback-owned work.

        Args:
            None

        Returns:
            None
        """
        inbox = LifecycleInbox()
        self.assertTrue(inbox.put(DesktopLifecycleEvent.LOCK))
        inbox.close()
        self.assertFalse(inbox.put(DesktopLifecycleEvent.SUSPEND))
        self.assertEqual(inbox.take_all(), ())

    def test_application_burst_schedules_one_callback_and_rearms_during_drain(
        self,
    ) -> None:
        """The actual app handoff keeps a constant pending Clock callback count.

        Args:
            None

        Returns:
            None
        """
        scheduled: list[Callable[[float], None]] = []
        applied: list[DesktopLifecycleEvent] = []
        handoff: LifecycleHandoff

        def apply(event: DesktopLifecycleEvent) -> None:
            """Inject one event while the first callback is draining.

            Args:
                event (DesktopLifecycleEvent): Drained event.

            Returns:
                None
            """
            applied.append(event)
            if len(applied) == 1:
                handoff.publish(DesktopLifecycleEvent.SUSPEND)

        handoff = LifecycleHandoff(scheduled.append, apply)
        for index in range(10_000):
            event = (
                DesktopLifecycleEvent.LOCK
                if index % 2
                else DesktopLifecycleEvent.RESUME
            )
            handoff.publish(event)
        self.assertEqual(len(scheduled), 1)

        first = scheduled.pop()
        first(0.0)
        self.assertEqual(len(scheduled), 1)
        second = scheduled.pop()
        second(0.0)

        self.assertIn(DesktopLifecycleEvent.SUSPEND, applied)

    def test_factory_selects_only_real_supported_desktop_sources(self) -> None:
        with patch(
            'metor.ui.gui.platform.lifecycle.platform.system', return_value='Windows'
        ):
            self.assertIsInstance(
                create_desktop_lifecycle_source(Mock()), WindowsLifecycleSource
            )
        with patch(
            'metor.ui.gui.platform.lifecycle.platform.system', return_value='Linux'
        ):
            self.assertIsInstance(
                create_desktop_lifecycle_source(Mock()), LinuxLifecycleSource
            )
        with patch(
            'metor.ui.gui.platform.lifecycle.platform.system', return_value='Darwin'
        ):
            self.assertIsNone(create_desktop_lifecycle_source(Mock()))


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

    def test_worker_exit_after_registration_is_fail_safe_and_cleans_up(self) -> None:
        """Unexpected message-loop return revokes trust and releases registration.

        Args:
            None

        Returns:
            None
        """

        class WindowClass:
            """Writable controlled replacement for ``win32gui.WNDCLASS``."""

        publish = Mock()
        win32gui = SimpleNamespace(
            WNDCLASS=WindowClass,
            RegisterClass=Mock(),
            CreateWindowEx=Mock(return_value=41),
            PumpMessages=Mock(),
            DestroyWindow=Mock(),
            DefWindowProc=Mock(return_value=0),
            PostQuitMessage=Mock(),
            PostMessage=Mock(),
        )
        win32ts = SimpleNamespace(
            WTSRegisterSessionNotification=Mock(),
            WTSUnRegisterSessionNotification=Mock(),
        )
        modules = {
            'win32api': SimpleNamespace(GetModuleHandle=Mock(return_value=7)),
            'win32gui': win32gui,
            'win32ts': win32ts,
        }
        source = WindowsLifecycleSource(publish)

        with patch(
            'metor.ui.gui.platform.lifecycle.importlib.import_module',
            side_effect=lambda name: modules[name],
        ):
            source._run()

        publish.assert_called_once_with(DesktopLifecycleEvent.SOURCE_LOST)
        win32ts.WTSUnRegisterSessionNotification.assert_called_once_with(41)
        win32gui.DestroyWindow.assert_called_once_with(41)
        self.assertIsNone(source._window)

    def test_partial_windows_registration_failure_destroys_owned_window(self) -> None:
        """A failed WTS registration leaves no native window or false readiness.

        Args:
            None

        Returns:
            None
        """

        class WindowClass:
            """Writable controlled replacement for ``win32gui.WNDCLASS``."""

        publish = Mock()
        win32gui = SimpleNamespace(
            WNDCLASS=WindowClass,
            RegisterClass=Mock(),
            CreateWindowEx=Mock(return_value=43),
            DestroyWindow=Mock(),
        )
        win32ts = SimpleNamespace(
            WTSRegisterSessionNotification=Mock(
                side_effect=OSError('registration failed')
            ),
            WTSUnRegisterSessionNotification=Mock(),
        )
        modules = {
            'win32api': SimpleNamespace(GetModuleHandle=Mock(return_value=7)),
            'win32gui': win32gui,
            'win32ts': win32ts,
        }
        source = WindowsLifecycleSource(publish)

        with patch(
            'metor.ui.gui.platform.lifecycle.importlib.import_module',
            side_effect=lambda name: modules[name],
        ):
            source._run()

        publish.assert_not_called()
        self.assertIsInstance(source._startup_error, OSError)
        win32ts.WTSUnRegisterSessionNotification.assert_not_called()
        win32gui.DestroyWindow.assert_called_once_with(43)
        self.assertIsNone(source._window)


class LinuxLifecycleSourceTests(unittest.TestCase):
    """Maps logind and desktop screen-lock D-Bus signals."""

    @staticmethod
    def _signal(**overrides: object) -> SimpleNamespace:
        """Build one exact trusted logind session signal.

        Args:
            **overrides (object): Fields replacing trusted defaults.

        Returns:
            SimpleNamespace: Candidate low-level message.
        """
        fields: dict[str, object] = {
            'message_type': 'signal',
            'sender': ':1.42',
            'path': '/org/freedesktop/login1/session/_42',
            'interface': 'org.freedesktop.login1.Session',
            'member': 'Lock',
            'body': [],
        }
        fields.update(overrides)
        return SimpleNamespace(**fields)

    def test_fake_bus_binds_own_session_and_initial_locked_state(self) -> None:
        """Readiness follows verified logind ownership, session, and state.

        Args:
            None

        Returns:
            None
        """
        modules = _FakeDbusModules(locked=True)
        received: list[DesktopLifecycleEvent] = []
        source = LinuxLifecycleSource(received.append)
        with patch(
            'metor.ui.gui.platform.lifecycle.importlib.import_module',
            side_effect=modules.import_module,
        ):
            source.start()
            try:
                self.assertEqual(received, [DesktopLifecycleEvent.LOCK])
                calls = modules.system.calls
                session_calls = [
                    call for call in calls if call.member == 'GetSessionByPID'
                ]
                self.assertEqual(len(session_calls), 1)
                self.assertEqual(len(session_calls[0].body), 1)
                match_rules = [
                    call.body[0] for call in calls if call.member == 'AddMatch'
                ]
                self.assertTrue(
                    any(
                        "sender=':1.42'" in rule
                        and "path='/org/freedesktop/login1/session/_42'" in rule
                        for rule in match_rules
                    )
                )
            finally:
                source.close()
        self.assertTrue(modules.system.disconnected)

    def test_empty_bus_does_not_claim_lifecycle_support(self) -> None:
        """A connection without a verified logind service fails startup.

        Args:
            None

        Returns:
            None
        """
        modules = _FakeDbusModules(login_available=False)
        source = LinuxLifecycleSource(Mock())
        with (
            patch(
                'metor.ui.gui.platform.lifecycle.importlib.import_module',
                side_effect=modules.import_module,
            ),
            self.assertRaisesRegex(RuntimeError, 'unavailable'),
        ):
            source.start()
        self.assertTrue(modules.system.disconnected)

    def test_message_requires_signal_owner_path_and_payload(self) -> None:
        """Wrong session, sender, message type, or payload cannot lock or resume.

        Args:
            None

        Returns:
            None
        """
        modules = _FakeDbusModules()
        publish = Mock()
        source = LinuxLifecycleSource(publish)
        with patch(
            'metor.ui.gui.platform.lifecycle.importlib.import_module',
            side_effect=modules.import_module,
        ):
            source.start()
            try:
                for message in (
                    self._signal(message_type='method_return'),
                    self._signal(sender=':1.99'),
                    self._signal(path='/org/freedesktop/login1/session/foreign'),
                    self._signal(body=[True]),
                ):
                    source._message(message)
                publish.assert_not_called()

                source._message(self._signal())
                publish.assert_called_once_with(DesktopLifecycleEvent.LOCK)
            finally:
                source.close()

    def test_owner_change_and_bus_loss_publish_one_fail_safe_departure(self) -> None:
        """Provider generation loss is visible once and terminates monitoring.

        Args:
            None

        Returns:
            None
        """
        modules = _FakeDbusModules()
        received: list[DesktopLifecycleEvent] = []
        failed = threading.Event()

        def publish(event: DesktopLifecycleEvent) -> None:
            """Capture and signal one controlled lifecycle event.

            Args:
                event (DesktopLifecycleEvent): Published event.

            Returns:
                None
            """
            received.append(event)
            if event is DesktopLifecycleEvent.SOURCE_LOST:
                failed.set()

        source = LinuxLifecycleSource(publish)
        with patch(
            'metor.ui.gui.platform.lifecycle.importlib.import_module',
            side_effect=modules.import_module,
        ):
            source.start()
            source._message(
                self._signal(
                    sender='org.freedesktop.DBus',
                    path='/org/freedesktop/DBus',
                    interface='org.freedesktop.DBus',
                    member='NameOwnerChanged',
                    body=['org.freedesktop.login1', ':1.42', ':1.77'],
                )
            )
            self.assertTrue(failed.wait(1.0))
            source._message(self._signal(member='Unlock'))
            modules.system.lost.set()
            source.close()

        self.assertEqual(received, [DesktopLifecycleEvent.SOURCE_LOST])

    def test_unexpected_bus_disconnect_publishes_source_loss(self) -> None:
        """A worker-side disconnect cannot leave monitoring reported as healthy.

        Args:
            None

        Returns:
            None
        """
        modules = _FakeDbusModules()
        received: list[DesktopLifecycleEvent] = []
        delivered = threading.Event()

        def publish(event: DesktopLifecycleEvent) -> None:
            """Capture the fail-safe event from the source thread.

            Args:
                event (DesktopLifecycleEvent): Published event.

            Returns:
                None
            """
            received.append(event)
            delivered.set()

        source = LinuxLifecycleSource(publish)
        with patch(
            'metor.ui.gui.platform.lifecycle.importlib.import_module',
            side_effect=modules.import_module,
        ):
            source.start()
            modules.system.lost.set()
            self.assertTrue(delivered.wait(1.0))
            source.close()

        self.assertEqual(received, [DesktopLifecycleEvent.SOURCE_LOST])

    def test_close_during_startup_is_bounded_and_eventually_releases_buses(
        self,
    ) -> None:
        """Closing a connecting source neither blocks nor leaves late publication.

        Args:
            None

        Returns:
            None
        """
        modules = _FakeDbusModules()
        release_connect = threading.Event()
        modules.system.connect_gate = release_connect
        publish = Mock()
        source = LinuxLifecycleSource(publish)
        start_errors: list[BaseException] = []

        def start() -> None:
            """Run source startup while the controlled connect is paused.

            Args:
                None

            Returns:
                None
            """
            try:
                source.start()
            except BaseException as exc:
                start_errors.append(exc)

        with (
            patch(
                'metor.ui.gui.platform.lifecycle.importlib.import_module',
                side_effect=modules.import_module,
            ),
            patch.object(GuiLimits, 'LIFECYCLE_CLOSE_SECONDS', 0.01),
        ):
            starter = threading.Thread(target=start)
            starter.start()
            self.assertTrue(modules.system.connect_started.wait(1.0))
            source.close()
            release_connect.set()
            starter.join(timeout=1.0)
            source.close()

        self.assertFalse(starter.is_alive())
        self.assertEqual(start_errors, [])
        publish.assert_not_called()
        self.assertTrue(modules.system.disconnected)

    def test_logind_sleep_and_session_signals_map_to_lifecycle(self) -> None:
        publish = Mock()
        source = LinuxLifecycleSource(publish)

        source._dispatch('org.freedesktop.login1.Manager', 'PrepareForSleep', [True])
        source._dispatch('org.freedesktop.login1.Manager', 'PrepareForSleep', [False])
        source._dispatch('org.freedesktop.login1.Session', 'Lock', [])
        source._dispatch('org.freedesktop.login1.Session', 'Unlock', [])

        self.assertEqual(
            [call.args[0] for call in publish.call_args_list],
            [
                DesktopLifecycleEvent.SUSPEND,
                DesktopLifecycleEvent.RESUME,
                DesktopLifecycleEvent.LOCK,
                DesktopLifecycleEvent.RESUME,
            ],
        )

    def test_screensaver_active_state_maps_without_treating_focus_as_lock(self) -> None:
        publish = Mock()
        source = LinuxLifecycleSource(publish)

        for interface in (
            'org.freedesktop.ScreenSaver',
            'org.gnome.ScreenSaver',
        ):
            source._dispatch(interface, 'ActiveChanged', [True])
            source._dispatch(interface, 'ActiveChanged', [False])
        source._dispatch('org.example.Window', 'FocusChanged', [False])
        source._dispatch('org.freedesktop.ScreenSaver', 'ActiveChanged', [])

        self.assertEqual(
            [call.args[0] for call in publish.call_args_list],
            [
                DesktopLifecycleEvent.LOCK,
                DesktopLifecycleEvent.RESUME,
                DesktopLifecycleEvent.LOCK,
                DesktopLifecycleEvent.RESUME,
            ],
        )


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

    def test_source_loss_revokes_suspends_and_surfaces_failure(self) -> None:
        """Unexpected provider loss keeps the privacy fence and becomes visible.

        Args:
            None

        Returns:
            None
        """
        order: list[str] = []
        coordinator = LifecycleCoordinator(
            lambda: order.append('revoke'),
            lambda: order.append('suspend'),
            lambda: order.append('resume'),
            lambda: order.append('refresh'),
            lambda: order.append('failure'),
        )

        coordinator.apply(DesktopLifecycleEvent.SOURCE_LOST)

        self.assertEqual(order, ['revoke', 'suspend', 'failure', 'refresh'])


if __name__ == '__main__':
    unittest.main()
