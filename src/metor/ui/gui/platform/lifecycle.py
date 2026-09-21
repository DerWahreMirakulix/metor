"""Bounded native desktop lock, suspend and resume integration."""

from collections import deque
from collections.abc import Callable
from enum import Enum
import asyncio
import importlib
import platform
import threading
from typing import Any, Protocol


class DesktopLifecycleEvent(str, Enum):
    """Security-relevant native desktop lifecycle transitions."""

    LOCK = 'lock'
    SUSPEND = 'suspend'
    RESUME = 'resume'


class LifecycleInbox:
    """Small synchronized handoff that preserves departures under overload."""

    def __init__(self, limit: int = 4) -> None:
        """Create an inbox with a fixed positive record limit."""
        if limit < 1:
            raise ValueError('Lifecycle inbox limit must be positive')
        self._limit = limit
        self._records: deque[DesktopLifecycleEvent] = deque()
        self._lock = threading.Lock()

    def put(self, event: DesktopLifecycleEvent) -> bool:
        """Coalesce duplicates and prefer a privacy departure over resume."""
        with self._lock:
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
            return True

    def take_all(self) -> tuple[DesktopLifecycleEvent, ...]:
        """Atomically drain the finite event sequence on the GUI thread."""
        with self._lock:
            records = tuple(self._records)
            self._records.clear()
            return records


class LifecycleCoordinator:
    """Apply native events in a privacy-first order on the GUI thread."""

    def __init__(
        self,
        revoke: Callable[[], None],
        suspend: Callable[[], None],
        resume: Callable[[], None],
        refresh: Callable[[], None],
    ) -> None:
        """Bind the sole UI-thread lifecycle actions."""
        self._revoke = revoke
        self._suspend = suspend
        self._resume = resume
        self._refresh = refresh

    def apply(self, event: DesktopLifecycleEvent) -> None:
        """Fence departures before controller work and never reveal on resume."""
        if event in {DesktopLifecycleEvent.LOCK, DesktopLifecycleEvent.SUSPEND}:
            self._revoke()
            self._suspend()
        else:
            self._resume()
        self._refresh()


class DesktopLifecycleSource(Protocol):
    """Lifecycle source owned by one GUI process."""

    def start(self) -> None:
        """Begin native event delivery or fail explicitly."""

    def close(self) -> None:
        """Stop native event delivery within a fixed bound."""


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
        """Create an inert native source with no Kivy-window subclass ownership."""
        self._publish = publish
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._closing = threading.Event()
        self._window: int | None = None
        self._startup_error: BaseException | None = None
        self._win32gui: Any = None
        self._win32ts: Any = None

    def start(self) -> None:
        """Register WTS and power delivery, failing closed if unavailable."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name='metor-windows-lifecycle',
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(2.0):
            self.close()
            raise RuntimeError('Windows lifecycle integration timed out')
        if self._startup_error is not None:
            error = self._startup_error
            self.close()
            raise RuntimeError(
                'Windows lifecycle integration is unavailable'
            ) from error

    def _run(self) -> None:
        """Own the hidden window and its message loop on one native thread."""
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
            window = win32gui.CreateWindowEx(
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
            win32ts.WTSRegisterSessionNotification(
                window, self._NOTIFY_FOR_THIS_SESSION
            )
            self._window = int(window)
            self._ready.set()
            if self._closing.is_set():
                win32gui.DestroyWindow(window)
                return
            win32gui.PumpMessages()
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            self._window = None

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        """Map only native session/power transitions and retain default handling."""
        if not self._closing.is_set():
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
            if self._win32ts is not None:
                self._win32ts.WTSUnRegisterSessionNotification(hwnd)
            self._win32gui.PostQuitMessage(0)
            return 0
        return self._default_window_proc(hwnd, message, wparam, lparam)

    def _default_window_proc(
        self, hwnd: int, message: int, wparam: int, lparam: int
    ) -> int:
        """Delegate unowned messages to Win32."""
        if self._win32gui is None:
            win32gui = importlib.import_module('win32gui')
            return int(win32gui.DefWindowProc(hwnd, message, wparam, lparam))
        return int(self._win32gui.DefWindowProc(hwnd, message, wparam, lparam))

    def close(self) -> None:
        """Stop publication and request bounded native-window teardown."""
        self._closing.set()
        thread, window = self._thread, self._window
        if thread is None:
            return
        if window is not None and self._win32gui is not None:
            self._win32gui.PostMessage(window, self._WM_CLOSE, 0, 0)
        thread.join(2.0)
        if not thread.is_alive():
            self._thread = None


class LinuxLifecycleSource:
    """Receive logind and desktop lock signals over native D-Bus buses."""

    _SYSTEM_RULES = (
        "type='signal',sender='org.freedesktop.login1',"
        "interface='org.freedesktop.login1.Manager',member='PrepareForSleep'",
        "type='signal',sender='org.freedesktop.login1',"
        "interface='org.freedesktop.login1.Session',member='Lock'",
        "type='signal',sender='org.freedesktop.login1',"
        "interface='org.freedesktop.login1.Session',member='Unlock'",
    )
    _SESSION_RULES = tuple(
        "type='signal',interface='" + interface + "',member='ActiveChanged'"
        for interface in (
            'org.freedesktop.ScreenSaver',
            'org.gnome.ScreenSaver',
            'org.cinnamon.ScreenSaver',
        )
    )

    def __init__(self, publish: Callable[[DesktopLifecycleEvent], None]) -> None:
        """Create an inert source; D-Bus imports remain Linux-runtime-only."""
        self._publish = publish
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._closing = threading.Event()
        self._startup_error: BaseException | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None

    def start(self) -> None:
        """Subscribe at least one native bus or reject unsupported sessions."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name='metor-linux-lifecycle',
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(3.0):
            self.close()
            raise RuntimeError('Linux lifecycle integration timed out')
        if self._startup_error is not None:
            error = self._startup_error
            self.close()
            raise RuntimeError('Linux lifecycle integration is unavailable') from error

    def _run(self) -> None:
        """Own asyncio and every D-Bus connection on one bounded thread."""
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._listen())
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            self._loop = None
            loop.close()

    async def _listen(self) -> None:
        """Install low-level matches without relying on desktop proxy objects."""
        aio = importlib.import_module('dbus_next.aio')
        constants = importlib.import_module('dbus_next.constants')
        message_module = importlib.import_module('dbus_next.message')
        buses: list[Any] = []
        for bus_type, rules in (
            (constants.BusType.SYSTEM, self._SYSTEM_RULES),
            (constants.BusType.SESSION, self._SESSION_RULES),
        ):
            bus = None
            try:
                bus = await aio.MessageBus(bus_type=bus_type).connect()
                for rule in rules:
                    reply = await bus.call(
                        message_module.Message(
                            destination='org.freedesktop.DBus',
                            path='/org/freedesktop/DBus',
                            interface='org.freedesktop.DBus',
                            member='AddMatch',
                            signature='s',
                            body=[rule],
                        )
                    )
                    if reply.message_type == constants.MessageType.ERROR:
                        raise OSError('D-Bus AddMatch was rejected')
                bus.add_message_handler(self._message)
                buses.append(bus)
            except Exception:
                if bus is not None:
                    bus.disconnect()
        if not buses:
            raise OSError('No supported Linux lifecycle D-Bus is available')
        self._stop = asyncio.Event()
        self._ready.set()
        if self._closing.is_set():
            self._stop.set()
        try:
            await self._stop.wait()
        finally:
            for bus in buses:
                bus.disconnect()
            self._stop = None

    def _message(self, message: Any) -> None:
        """Extract only the finite signal fields used by the lifecycle mapper."""
        interface = message.interface
        member = message.member
        body = message.body
        if isinstance(interface, str) and isinstance(member, str):
            self._dispatch(interface, member, body if isinstance(body, list) else [])

    def _dispatch(self, interface: str, member: str, body: list[Any]) -> None:
        """Map supported D-Bus signals; ordinary focus is intentionally absent."""
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
        """Stop publication and wake the owned asyncio loop within a fixed bound."""
        self._closing.set()
        thread, loop, stop = self._thread, self._loop, self._stop
        if thread is None:
            return
        if loop is not None and stop is not None:
            loop.call_soon_threadsafe(stop.set)
        thread.join(2.0)
        if not thread.is_alive():
            self._thread = None


def create_desktop_lifecycle_source(
    publish: Callable[[DesktopLifecycleEvent], None],
) -> DesktopLifecycleSource | None:
    """Construct the active supported platform source without emulation."""
    if platform.system() == 'Windows':
        return WindowsLifecycleSource(publish)
    if platform.system() == 'Linux':
        return LinuxLifecycleSource(publish)
    return None
