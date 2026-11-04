"""Synthetic OS input for an explicitly selected virtual X11 acceptance display.

XTest delivers mouse and keyboard events through the native SDL provider. This
does not establish physical input-device, desktop accessibility or audio support.
"""

import ctypes
import json
from collections import deque
from ctypes.util import find_library

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.widget import Widget


INPUT_RELEASE_SECONDS = 0.06
INPUT_CHARACTER_SECONDS = 0.03
INPUT_SCROLL_SECONDS = 0.03


class XTextProperty(ctypes.Structure):
    """Represents the encoding-qualified native X11 window name property."""

    _fields_ = [
        ('value', ctypes.c_void_p),
        ('encoding', ctypes.c_ulong),
        ('format', ctypes.c_int),
        ('nitems', ctypes.c_ulong),
    ]


def rectangle(widget: Widget) -> tuple[float, float, float, float]:
    """Returns actual window geometry with ancestor scrolling transforms applied."""
    left, bottom = widget.to_window(widget.x, widget.y)
    return float(left), float(bottom), float(widget.width), float(widget.height)


class NativeX11Input:
    """Owns one X11 connection and sends OS events to the actual Metor window."""

    def __init__(self) -> None:
        """Connects to the caller-selected display and validates native libraries."""
        x11_path, xtest_path = find_library('X11'), find_library('Xtst')
        assert x11_path and xtest_path, 'X11 and XTest are required'
        self.x11 = ctypes.CDLL(x11_path)
        self.xtest = ctypes.CDLL(xtest_path)
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x11.XQueryTree.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self.x11.XFetchName.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.x11.XGetWMName.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(XTextProperty),
        ]
        self.x11.XFree.argtypes = [ctypes.c_void_p]
        self.x11.XTranslateCoordinates.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self.x11.XSetInputFocus.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.x11.XStringToKeysym.restype = ctypes.c_ulong
        self.x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x11.XKeysymToKeycode.restype = ctypes.c_uint
        self.x11.XFlush.argtypes = [ctypes.c_void_p]
        self.x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.x11.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x11.XMoveWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
        ]
        self.x11.XGetGeometry.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self.xtest.XTestFakeMotionEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.xtest.XTestFakeButtonEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.xtest.XTestFakeKeyEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        self.display = self.x11.XOpenDisplay(None)
        assert self.display, 'Native X11 display is unavailable'
        self.root = self.x11.XDefaultRootWindow(self.display)
        self.window: int | None = None
        self.events = 0
        self._typing: deque[str] = deque()
        self._wheel: deque[int] = deque()

    def close(self) -> None:
        """Releases this fixture's X11 connection without affecting other clients."""
        if self.display:
            self._typing.clear()
            self._wheel.clear()
            self.xtest.XTestFakeButtonEvent(self.display, 1, 0, 0)
            self.x11.XSync(self.display, 0)
            self.x11.XCloseDisplay(self.display)
            self.display = None

    def activate(self) -> None:
        """Finds the actual SDL window and gives it native keyboard ownership."""
        root, parent, count = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_uint()
        children = ctypes.POINTER(ctypes.c_ulong)()
        assert self.x11.XQueryTree(
            self.display,
            self.root,
            ctypes.byref(root),
            ctypes.byref(parent),
            ctypes.byref(children),
            ctypes.byref(count),
        )
        observed: list[str] = []
        try:
            for index in range(count.value):
                name = XTextProperty()
                if (
                    self.x11.XGetWMName(
                        self.display, children[index], ctypes.byref(name)
                    )
                    and name.value
                ):
                    try:
                        title = ctypes.string_at(name.value, name.nitems).decode(
                            'utf-8'
                        )
                        observed.append(title)
                        if title == Window.title or title == 'Metor':
                            self.window = int(children[index])
                            break
                    finally:
                        self.x11.XFree(name.value)
        finally:
            if children:
                self.x11.XFree(children)
        assert self.window is not None, (
            'The native Metor window was not created',
            Window.title,
            observed,
        )
        self.x11.XSetInputFocus(self.display, self.window, 1, 0)
        self.xtest.XTestFakeButtonEvent(self.display, 1, 0, 0)
        # The virtual display has no window manager to place resized windows.
        self.x11.XMoveWindow(self.display, self.window, 0, 0)
        self.x11.XRaiseWindow(self.display, self.window)
        self.x11.XSync(self.display, 0)

    def click(self, widget: Widget, *, allow_disabled: bool = False) -> None:
        """Presses and releases a reachable native control across two event-loop frames.

        Args:
            widget: Attached native control with a reachable window rectangle.
            allow_disabled: Allows deliberate negative-input acceptance checks;
                it does not enable the control or alter native dispatch.
        """
        assert self.window is not None
        actual_size = self.size()
        assert actual_size == tuple(Window.system_size), (
            'Native SDL surface size has not settled',
            actual_size,
            Window.system_size,
        )
        left, bottom, width, height = rectangle(widget)
        assert (
            allow_disabled or not widget.disabled
        ) and widget.get_root_window() is not None
        assert left >= -1 and bottom >= -1 and width > 0 and height > 0
        assert left + width <= Window.width + 1 and bottom + height <= Window.height + 1
        x, y, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
        assert self.x11.XTranslateCoordinates(
            self.display,
            self.window,
            self.root,
            0,
            0,
            ctypes.byref(x),
            ctypes.byref(y),
            ctypes.byref(child),
        )
        if self.events == 0:
            print(
                'NATIVE_GUI_INITIAL_POINTER '
                + json.dumps(
                    {
                        'widget': [left, bottom, width, height],
                        'window': [Window.width, Window.height],
                        'native_origin': [x.value, y.value],
                        'native_size': actual_size,
                        'disabled': widget.disabled,
                    }
                ),
                flush=True,
            )
        self.xtest.XTestFakeMotionEvent(
            self.display,
            -1,
            x.value + int(left + width / 2),
            y.value + int(Window.height - bottom - height / 2),
            0,
        )
        self.x11.XFlush(self.display)
        Clock.schedule_once(self._press, INPUT_SCROLL_SECONDS)
        self.events += 1

    def size(self) -> tuple[int, int]:
        """Reads the actual X11 client extent independently of Kivy's resize properties."""
        assert self.window is not None
        root = ctypes.c_ulong()
        left, top = ctypes.c_int(), ctypes.c_int()
        width, height, border, depth = (ctypes.c_uint() for _ in range(4))
        assert self.x11.XGetGeometry(
            self.display,
            self.window,
            ctypes.byref(root),
            ctypes.byref(left),
            ctypes.byref(top),
            ctypes.byref(width),
            ctypes.byref(height),
            ctypes.byref(border),
            ctypes.byref(depth),
        )
        return width.value, height.value

    def _press(self, _elapsed: float) -> None:
        """Lets the native pointer motion settle before beginning the mouse press."""
        if self.display is None:
            return
        self.xtest.XTestFakeButtonEvent(self.display, 1, 1, 0)
        self.x11.XFlush(self.display)
        Clock.schedule_once(self._release, INPUT_RELEASE_SECONDS)

    def _release(self, _elapsed: float) -> None:
        """Lets the actual SDL provider deliver the release to its captured target."""
        if self.display is None:
            return
        self.xtest.XTestFakeButtonEvent(self.display, 1, 0, 0)
        self.x11.XFlush(self.display)

    def scroll(self, widget: Widget, *, downward: bool, steps: int = 3) -> None:
        """Delivers native wheel input over a real scroll viewport."""
        assert self.window is not None
        left, bottom, width, height = rectangle(widget)
        x, y, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
        assert self.x11.XTranslateCoordinates(
            self.display,
            self.window,
            self.root,
            0,
            0,
            ctypes.byref(x),
            ctypes.byref(y),
            ctypes.byref(child),
        )
        self.xtest.XTestFakeMotionEvent(
            self.display,
            -1,
            x.value + int(left + width / 2),
            y.value + int(Window.height - bottom - height / 2),
            0,
        )
        self.x11.XFlush(self.display)
        idle = not self._wheel
        self._wheel.extend([5 if downward else 4] * steps)
        if idle:
            Clock.schedule_once(self._scroll_step, INPUT_SCROLL_SECONDS)

    def _scroll_step(self, _elapsed: float) -> None:
        """Keeps actual wheel ticks distinct when SDL coalesces same-frame bursts."""
        if not self._wheel:
            return
        button = self._wheel.popleft()
        self.xtest.XTestFakeButtonEvent(self.display, button, 1, 0)
        self.xtest.XTestFakeButtonEvent(self.display, button, 0, 0)
        self.x11.XFlush(self.display)
        self.events += 1
        if self._wheel:
            Clock.schedule_once(self._scroll_step, INPUT_SCROLL_SECONDS)

    def key(self, symbol: str, *, modifiers: tuple[str, ...] = ()) -> None:
        """Delivers one native key chord through XTest with ordered modifier release."""
        codes = [self._code(item) for item in (*modifiers, symbol)]
        for code in codes:
            self.xtest.XTestFakeKeyEvent(self.display, code, 1, 0)
        for code in reversed(codes):
            self.xtest.XTestFakeKeyEvent(self.display, code, 0, 0)
        self.x11.XFlush(self.display)
        self.events += 1

    def type(self, value: str) -> None:
        """Types fixture text across native frames rather than flooding one SDL poll."""
        assert not self._typing, 'Native typing already owns a pending sequence'
        self._typing.extend(value)
        self._type_character(0)

    def _type_character(self, _elapsed: float) -> None:
        """Keeps physical-style key ordering through multiline native text layout."""
        if not self._typing:
            return
        character = self._typing.popleft()
        if character == '\n':
            self.key('Return', modifiers=('Shift_L',))
        elif character == ' ':
            self.key('space')
        elif character == '-':
            self.key('minus')
        elif character.isascii() and character.isalnum():
            self.key(
                character.lower(), modifiers=('Shift_L',) if character.isupper() else ()
            )
        else:
            raise ValueError('The native text fixture supports explicit ASCII input')
        if self._typing:
            Clock.schedule_once(self._type_character, INPUT_CHARACTER_SECONDS)

    def _code(self, symbol: str) -> int:
        """Resolves a key through the actual display's keyboard map."""
        keysym = self.x11.XStringToKeysym(symbol.encode('ascii'))
        code = int(self.x11.XKeysymToKeycode(self.display, keysym))
        assert code, 'The selected display cannot resolve an input key'
        return code
