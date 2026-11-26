"""Check a single actual Windows activation click against an isolated SDL window."""

# ruff: noqa: E402

import argparse
import ctypes
import os
from ctypes import wintypes

assert os.name == 'nt', 'This fixture requires the native Windows desktop'
user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
previous = user32.GetForegroundWindow()
pointer = wintypes.POINT()
assert user32.GetCursorPos(ctypes.byref(pointer))

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'

from kivy.config import Config

Config.set('graphics', 'width', '640')
Config.set('graphics', 'height', '480')
Config.set('graphics', 'position', 'custom')
Config.set('graphics', 'left', '100')
Config.set('graphics', 'top', '100')

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.floatlayout import FloatLayout

from metor.ui.gui.widgets import Action


class ReactivationProbe(App):
    """Owns both test windows and verifies OS events reach one ordinary action."""

    def build(self) -> FloatLayout:
        """Creates a single large target and records the native focus transitions."""
        self.calls = 0
        self.completed = False
        self.other = None
        self.departed = False
        self.returned = False
        self.hwnd = Window.get_window_info().window
        root = FloatLayout()
        self.action = Action(
            'Single activation click',
            self.activated,
            size_hint=(None, None),
            width=300,
            pos_hint={'center_x': 0.5, 'center_y': 0.5},
        )
        root.add_widget(self.action)
        Window.bind(focus=self.focus_changed)
        Clock.schedule_once(self.prime, 0.4)
        Clock.schedule_once(self.timed_out, 8)
        return root

    def activated(self) -> None:
        """Counts actual action releases delivered by SDL's native input provider."""
        self.calls += 1

    def focus_changed(self, _window: object, focused: bool) -> None:
        """Records native departure and return without assigning Window.focus."""
        self.departed |= not focused
        self.returned |= focused and self.departed

    def prime(self, _elapsed: float) -> None:
        """Activates only the test window with a harmless click on its empty space."""
        target = wintypes.POINT(20, 20)
        assert user32.ClientToScreen(self.hwnd, ctypes.byref(target))
        assert user32.SetCursorPos(target.x, target.y)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        Clock.schedule_once(self.leave, 0.3)

    def leave(self, _elapsed: float) -> None:
        """Moves focus to a disposable window beside the unobstructed target."""
        assert Window.focus and user32.GetForegroundWindow() == self.hwnd
        self.departed = self.returned = False
        self.other = user32.CreateWindowExW(
            0,
            'STATIC',
            'Metor disposable focus target',
            0x10CF0000,
            760,
            100,
            280,
            160,
            None,
            None,
            None,
            None,
        )
        assert self.other
        target = wintypes.POINT(100, 60)
        assert user32.ClientToScreen(self.other, ctypes.byref(target))
        assert user32.SetCursorPos(target.x, target.y)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        Clock.schedule_once(self.click, 0.3)

    def click(self, _elapsed: float) -> None:
        """Sends one real mouse click, allowing Windows itself to reactivate SDL."""
        assert self.departed and not Window.focus
        assert user32.GetForegroundWindow() == self.other
        target = wintypes.POINT(
            round(self.action.center_x), round(Window.height - self.action.center_y)
        )
        assert user32.ClientToScreen(self.hwnd, ctypes.byref(target))
        assert user32.SetCursorPos(target.x, target.y)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        Clock.schedule_once(self.release, 0.08)

    def release(self, _elapsed: float) -> None:
        """Releases the same click after the native queue has processed its down event."""
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        Clock.schedule_once(self.inspect, 0.3)

    def inspect(self, _elapsed: float) -> None:
        """Requires actual focus restoration and reports the action count."""
        assert self.returned and Window.focus
        assert user32.GetForegroundWindow() == self.hwnd
        self.completed = True
        self.stop()

    def timed_out(self, _elapsed: float) -> None:
        """Fails boundedly if the native OS transitions never complete."""
        raise AssertionError('Native focus test did not complete')


def main() -> None:
    """Runs the native probe and restores the original foreground and cursor."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-clicks', type=int, choices=(0, 1), default=1)
    arguments = parser.parse_args()
    app = ReactivationProbe()
    try:
        app.run()
        assert app.completed and app.calls == arguments.expected_clicks
        print(f'NATIVE_REACTIVATION_OK clicks={app.calls}')
    finally:
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        if app.other:
            user32.DestroyWindow(app.other)
        user32.SetCursorPos(pointer.x, pointer.y)
        user32.SetForegroundWindow(previous)


if __name__ == '__main__':
    main()
