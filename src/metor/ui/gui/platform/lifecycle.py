"""Bounded native desktop lock, suspend and resume integration."""

from collections import deque
from collections.abc import Callable
from enum import Enum
import asyncio
import importlib
import platform
import threading
from typing import Any, Protocol

from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.linux_lifecycle import LinuxLifecycleBinding


class DesktopLifecycleEvent(str, Enum):
    """Security-relevant native desktop lifecycle transitions."""

    LOCK = 'lock'
    SUSPEND = 'suspend'
    RESUME = 'resume'
    SOURCE_LOST = 'source_lost'


class LifecycleInbox:
    """Small synchronized handoff that preserves departures under overload."""

    def __init__(self, limit: int = 4) -> None:
        """Create an inbox with a fixed positive record limit.

        Args:
            limit (int): The limit input.

        Returns:
            None
        """
        if limit < 1:
            raise ValueError('Lifecycle inbox limit must be positive')
        self._limit = limit
        self._records: deque[DesktopLifecycleEvent] = deque()
        self._lock = threading.Lock()
        self._wakeup_pending = False
        self._closed = False

    def put(self, event: DesktopLifecycleEvent) -> bool:
        """Coalesce records and request at most one pending GUI wakeup.

        Args:
            event (DesktopLifecycleEvent): The event input.

        Returns:
            bool: Whether the caller must schedule the sole GUI wakeup.
        """
        with self._lock:
            if self._closed:
                return False
            if self._records and self._records[-1] is event:
                return False
            if len(self._records) >= self._limit:
                if event is DesktopLifecycleEvent.RESUME:
                    return False
                try:
                    self._records.remove(DesktopLifecycleEvent.RESUME)
                except ValueError:
                    self._records.popleft()
            self._records.append(event)
            if self._wakeup_pending:
                return False
            self._wakeup_pending = True
            return True

    def take_all(self) -> tuple[DesktopLifecycleEvent, ...]:
        """Atomically drain the finite event sequence on the GUI thread.

        Args:
            None

        Returns:
            tuple[DesktopLifecycleEvent, ...]: The resulting value.
        """
        with self._lock:
            records = tuple(self._records)
            self._records.clear()
            self._wakeup_pending = False
            return records

    def close(self) -> None:
        """Reject future publication and discard queued native transitions.

        Args:
            None

        Returns:
            None
        """
        with self._lock:
            self._closed = True
            self._records.clear()
            self._wakeup_pending = False


class LifecycleHandoff:
    """Own one coalesced GUI wakeup around the bounded lifecycle inbox."""

    def __init__(
        self,
        schedule: Callable[[Callable[[float], None]], None],
        apply: Callable[[DesktopLifecycleEvent], None],
    ) -> None:
        """Bind toolkit scheduling and GUI-thread event application.

        Args:
            schedule (Callable[[Callable[[float], None]], None]): Toolkit wakeup adapter.
            apply (Callable[[DesktopLifecycleEvent], None]): GUI-thread event consumer.

        Returns:
            None
        """
        self._schedule = schedule
        self._apply = apply
        self._inbox = LifecycleInbox()

    def publish(self, event: DesktopLifecycleEvent) -> None:
        """Admit a native-thread event and schedule only the first pending wakeup.

        Args:
            event (DesktopLifecycleEvent): Native lifecycle transition.

        Returns:
            None
        """
        if self._inbox.put(event):
            self._schedule(self.drain)

    def drain(self, _elapsed: float) -> None:
        """Apply one atomic inbox snapshot on the GUI thread.

        Args:
            _elapsed (float): Toolkit scheduling delta.

        Returns:
            None
        """
        for event in self._inbox.take_all():
            self._apply(event)

    def close(self) -> None:
        """Reject late source events and discard pending records.

        Args:
            None

        Returns:
            None
        """
        self._inbox.close()


class LifecycleCoordinator:
    """Apply native events in a privacy-first order on the GUI thread."""

    def __init__(
        self,
        revoke: Callable[[], None],
        suspend: Callable[[], None],
        resume: Callable[[], None],
        refresh: Callable[[], None],
        failure: Callable[[], None] | None = None,
    ) -> None:
        """Bind the sole UI-thread lifecycle actions.

        Args:
            revoke (Callable[[], None]): The revoke input.
            suspend (Callable[[], None]): The suspend input.
            resume (Callable[[], None]): The resume input.
            refresh (Callable[[], None]): The refresh input.
            failure (Callable[[], None] | None): Visible source-failure callback.

        Returns:
            None
        """
        self._revoke = revoke
        self._suspend = suspend
        self._resume = resume
        self._refresh = refresh
        self._failure = failure

    def apply(self, event: DesktopLifecycleEvent) -> None:
        """Fence departures before controller work and never reveal on resume.

        Args:
            event (DesktopLifecycleEvent): The event input.

        Returns:
            None
        """
        if event in {
            DesktopLifecycleEvent.LOCK,
            DesktopLifecycleEvent.SUSPEND,
            DesktopLifecycleEvent.SOURCE_LOST,
        }:
            self._revoke()
            self._suspend()
            if event is DesktopLifecycleEvent.SOURCE_LOST and self._failure is not None:
                self._failure()
        else:
            self._resume()
        self._refresh()


class DesktopLifecycleSource(Protocol):
    """Lifecycle source owned by one GUI process."""

    def start(self) -> None:
        """Begin native event delivery or fail explicitly.

        Args:
            None

        Returns:
            None
        """

    def close(self) -> None:
        """Stop native event delivery within a fixed bound.

        Args:
            None

        Returns:
            None
        """


class WindowsLifecycleSource:
    """Receive Windows lifecycle broadcasts on one private hidden window."""

    _WM_CLOSE = 0x0010
    _WM_DESTROY = 0x0002
    _WM_POWERBROADCAST = 0x0218
    _WM_WTSSESSION_CHANGE = 0x02B1
    _PBT_APMSUSPEND = 0x0004
    _PBT_APMRESUMESUSPEND = 0x0007
    _PBT_APMRESUMEAUTOMATIC = 0x0012
    _WTS_SESSION_LOCK = 0x0007
    _WTS_SESSION_UNLOCK = 0x0008
    _NOTIFY_FOR_THIS_SESSION = 0

    def __init__(self, publish: Callable[[DesktopLifecycleEvent], None]) -> None:
        """Create an inert native source with no Kivy-window subclass ownership.

        Args:
            publish (Callable[[DesktopLifecycleEvent], None]): The publish input.

        Returns:
            None
        """
        self._publish = publish
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._closing = threading.Event()
        self._window: int | None = None
        self._startup_error: BaseException | None = None
        self._win32gui: Any = None
        self._win32ts: Any = None
        self._notification_registered = False
        self._source_failed = threading.Event()

    def start(self) -> None:
        """Register WTS and power delivery, failing closed if unavailable.

        Args:
            None

        Returns:
            None
        """
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name='metor-windows-lifecycle',
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(GuiLimits.LIFECYCLE_CLOSE_SECONDS):
            self.close()
            raise RuntimeError('Windows lifecycle integration timed out')
        if self._startup_error is not None:
            error = self._startup_error
            self.close()
            raise RuntimeError(
                'Windows lifecycle integration is unavailable'
            ) from error

    def _run(self) -> None:
        """Own the hidden window and its message loop on one native thread.

        Args:
            None

        Returns:
            None
        """
        window: int | None = None
        try:
            win32api = importlib.import_module('win32api')
            win32gui = importlib.import_module('win32gui')
            win32ts = importlib.import_module('win32ts')

            self._win32gui = win32gui
            self._win32ts = win32ts
            instance = win32api.GetModuleHandle(None)
            class_name = f'MetorLifecycle_{id(self):x}'
            window_class = win32gui.WNDCLASS()
            window_class.hInstance = instance
            window_class.lpszClassName = class_name
            window_class.lpfnWndProc = self._window_proc
            win32gui.RegisterClass(window_class)
            window = int(
                win32gui.CreateWindowEx(
                    0,
                    class_name,
                    'Metor lifecycle',
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    instance,
                    None,
                )
            )
            self._window = window
            win32ts.WTSRegisterSessionNotification(
                window, self._NOTIFY_FOR_THIS_SESSION
            )
            self._notification_registered = True
            self._ready.set()
            if self._closing.is_set():
                win32gui.DestroyWindow(window)
                return
            win32gui.PumpMessages()
            if not self._closing.is_set():
                self._publish_source_loss()
        except BaseException as exc:
            self._startup_error = exc
            if self._ready.is_set():
                self._publish_source_loss()
            self._ready.set()
        finally:
            if window is not None and self._window is not None:
                try:
                    if self._notification_registered and self._win32ts is not None:
                        self._win32ts.WTSUnRegisterSessionNotification(window)
                        self._notification_registered = False
                    if self._win32gui is not None:
                        self._win32gui.DestroyWindow(window)
                except Exception:
                    pass
            self._window = None

    def _publish_source_loss(self) -> None:
        """Publish one fail-safe departure after native worker loss.

        Args:
            None

        Returns:
            None
        """
        if self._closing.is_set() or self._source_failed.is_set():
            return
        self._source_failed.set()
        self._publish(DesktopLifecycleEvent.SOURCE_LOST)

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        """Map only native session/power transitions and retain default handling.

        Args:
            hwnd (int): The hwnd input.
            message (int): The message input.
            wparam (int): The wparam input.
            lparam (int): The lparam input.

        Returns:
            int: The resulting integer value.
        """
        if not self._closing.is_set() and not self._source_failed.is_set():
            event = None
            if (
                message == self._WM_WTSSESSION_CHANGE
                and wparam == self._WTS_SESSION_LOCK
            ):
                event = DesktopLifecycleEvent.LOCK
            elif message == self._WM_POWERBROADCAST and wparam == self._PBT_APMSUSPEND:
                event = DesktopLifecycleEvent.SUSPEND
            elif (
                message == self._WM_WTSSESSION_CHANGE
                and wparam == self._WTS_SESSION_UNLOCK
            ):
                event = DesktopLifecycleEvent.RESUME
            elif message == self._WM_POWERBROADCAST and wparam in {
                self._PBT_APMRESUMESUSPEND,
                self._PBT_APMRESUMEAUTOMATIC,
            }:
                event = DesktopLifecycleEvent.RESUME
            if event is not None:
                self._publish(event)
        if message == self._WM_CLOSE and self._win32gui is not None:
            self._win32gui.DestroyWindow(hwnd)
            return 0
        if message == self._WM_DESTROY and self._win32gui is not None:
            if self._notification_registered and self._win32ts is not None:
                self._win32ts.WTSUnRegisterSessionNotification(hwnd)
                self._notification_registered = False
            self._window = None
            self._win32gui.PostQuitMessage(0)
            return 0
        return self._default_window_proc(hwnd, message, wparam, lparam)

    def _default_window_proc(
        self, hwnd: int, message: int, wparam: int, lparam: int
    ) -> int:
        """Delegate unowned messages to Win32.

        Args:
            hwnd (int): The hwnd input.
            message (int): The message input.
            wparam (int): The wparam input.
            lparam (int): The lparam input.

        Returns:
            int: The resulting integer value.
        """
        if self._win32gui is None:
            win32gui = importlib.import_module('win32gui')
            return int(win32gui.DefWindowProc(hwnd, message, wparam, lparam))
        return int(self._win32gui.DefWindowProc(hwnd, message, wparam, lparam))

    def close(self) -> None:
        """Stop publication and request bounded native-window teardown.

        Args:
            None

        Returns:
            None
        """
        self._closing.set()
        thread, window = self._thread, self._window
        if thread is None:
            return
        if window is not None and self._win32gui is not None:
            self._win32gui.PostMessage(window, self._WM_CLOSE, 0, 0)
        thread.join(GuiLimits.LIFECYCLE_CLOSE_SECONDS)
        if not thread.is_alive():
            self._thread = None


class LinuxLifecycleSource:
    """Receive logind and desktop lock signals over native D-Bus buses."""

    def __init__(self, publish: Callable[[DesktopLifecycleEvent], None]) -> None:
        """Create an inert source; D-Bus imports remain Linux-runtime-only.

        Args:
            publish (Callable[[DesktopLifecycleEvent], None]): The publish input.

        Returns:
            None
        """
        self._publish = publish
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._closing = threading.Event()
        self._startup_error: BaseException | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._binding: LinuxLifecycleBinding | None = None
        self._source_failed = threading.Event()

    def start(self) -> None:
        """Subscribe at least one native bus or reject unsupported sessions.

        Args:
            None

        Returns:
            None
        """
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name='metor-linux-lifecycle',
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(GuiLimits.LIFECYCLE_START_SECONDS):
            self.close()
            raise RuntimeError('Linux lifecycle integration timed out')
        if self._startup_error is not None:
            error = self._startup_error
            self.close()
            raise RuntimeError('Linux lifecycle integration is unavailable') from error

    def _run(self) -> None:
        """Own asyncio and every D-Bus connection on one bounded thread.

        Args:
            None

        Returns:
            None
        """
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._listen())
        except BaseException as exc:
            self._startup_error = exc
            if self._ready.is_set():
                self._publish_source_loss()
            self._ready.set()
        finally:
            self._loop = None
            loop.close()

    def _publish_source_loss(self) -> None:
        """Publish one fail-safe departure after an unexpected provider loss.

        Args:
            None

        Returns:
            None
        """
        if self._closing.is_set() or self._source_failed.is_set():
            return
        self._source_failed.set()
        self._publish(DesktopLifecycleEvent.SOURCE_LOST)

    async def _listen(self) -> None:
        """Bind exact providers, current session, initial state, and disconnects.

        Args:
            None

        Returns:
            None
        """
        aio = importlib.import_module('dbus_next.aio')
        constants = importlib.import_module('dbus_next.constants')
        message_module = importlib.import_module('dbus_next.message')
        binding = LinuxLifecycleBinding(constants.MessageType.SIGNAL)
        self._binding = binding
        buses: list[Any] = []
        waiters: list[asyncio.Task[Any]] = []
        try:
            system_bus = await aio.MessageBus(
                bus_type=constants.BusType.SYSTEM
            ).connect()
            try:
                locked = await binding.configure_logind(
                    system_bus,
                    constants,
                    message_module.Message,
                )
            except BaseException:
                system_bus.disconnect()
                raise
            buses.append(system_bus)

            session_bus = None
            try:
                session_bus = await aio.MessageBus(
                    bus_type=constants.BusType.SESSION
                ).connect()
                providers = await binding.configure_screen_savers(
                    session_bus,
                    constants,
                    message_module.Message,
                )
                if providers:
                    buses.append(session_bus)
                else:
                    session_bus.disconnect()
            except Exception:
                if session_bus is not None:
                    session_bus.disconnect()

            for bus in buses:
                bus.add_message_handler(self._message)
            if locked:
                self._publish(DesktopLifecycleEvent.LOCK)

            self._stop = asyncio.Event()
            self._ready.set()
            if self._closing.is_set():
                self._stop.set()

            waiters.append(asyncio.create_task(self._stop.wait()))
            for bus in buses:
                wait_for_disconnect = getattr(bus, 'wait_for_disconnect', None)
                if callable(wait_for_disconnect):
                    waiters.append(asyncio.create_task(wait_for_disconnect()))
            done, pending = await asyncio.wait(
                waiters,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if waiters[0] not in done and not self._closing.is_set():
                raise OSError('Linux lifecycle D-Bus disconnected unexpectedly')
        finally:
            cancelled: list[asyncio.Task[Any]] = []
            for waiter in waiters:
                if not waiter.done():
                    waiter.cancel()
                    cancelled.append(waiter)
            if cancelled:
                await asyncio.gather(*cancelled, return_exceptions=True)
            for bus in buses:
                bus.disconnect()
            self._stop = None

    def _message(self, message: Any) -> None:
        """Accept only exact signals from the bound provider generations.

        Args:
            message (Any): The message input.

        Returns:
            None
        """
        if self._source_failed.is_set():
            return
        binding = self._binding
        if binding is None:
            return
        signal = binding.inspect(message)
        if signal is None:
            return
        if signal.source_lost:
            self._publish_source_loss()
            if self._stop is not None:
                self._stop.set()
            return
        if signal.interface is None or signal.member is None or signal.body is None:
            return
        self._dispatch(signal.interface, signal.member, signal.body)

    def _dispatch(self, interface: str, member: str, body: list[Any]) -> None:
        """Map supported D-Bus signals; ordinary focus is intentionally absent.

        Args:
            interface (str): The interface input.
            member (str): The member input.
            body (list[Any]): The body input.

        Returns:
            None
        """
        event = None
        if (
            interface == 'org.freedesktop.login1.Manager'
            and member == 'PrepareForSleep'
            and len(body) == 1
            and type(body[0]) is bool
        ):
            event = (
                DesktopLifecycleEvent.SUSPEND
                if body[0]
                else DesktopLifecycleEvent.RESUME
            )
        elif interface == 'org.freedesktop.login1.Session' and not body:
            if member == 'Lock':
                event = DesktopLifecycleEvent.LOCK
            elif member == 'Unlock':
                event = DesktopLifecycleEvent.RESUME
        elif (
            interface
            in {
                'org.freedesktop.ScreenSaver',
                'org.gnome.ScreenSaver',
                'org.cinnamon.ScreenSaver',
            }
            and member == 'ActiveChanged'
            and len(body) == 1
            and type(body[0]) is bool
        ):
            event = (
                DesktopLifecycleEvent.LOCK if body[0] else DesktopLifecycleEvent.RESUME
            )
        if event is not None and not self._closing.is_set():
            self._publish(event)

    def close(self) -> None:
        """Stop publication and wake the owned asyncio loop within a fixed bound.

        Args:
            None

        Returns:
            None
        """
        self._closing.set()
        thread, loop, stop = self._thread, self._loop, self._stop
        if thread is None:
            return
        if loop is not None and stop is not None:
            loop.call_soon_threadsafe(stop.set)
        thread.join(GuiLimits.LIFECYCLE_CLOSE_SECONDS)
        if not thread.is_alive():
            self._thread = None


def create_desktop_lifecycle_source(
    publish: Callable[[DesktopLifecycleEvent], None],
) -> DesktopLifecycleSource | None:
    """Construct the active supported platform source without emulation.

    Args:
        publish (Callable[[DesktopLifecycleEvent], None]): The publish input.

    Returns:
        DesktopLifecycleSource | None: The resulting value.
    """
    if platform.system() == 'Windows':
        return WindowsLifecycleSource(publish)
    if platform.system() == 'Linux':
        return LinuxLifecycleSource(publish)
    return None
