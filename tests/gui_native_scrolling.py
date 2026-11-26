"""Native wheel boundaries and drag movement on actual secondary GUI pages."""

# ruff: noqa: E402

import argparse
import ctypes
import os
import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.config import Config

Config.set('graphics', 'width', '1180')
Config.set('graphics', 'height', '760')
Config.set('graphics', 'maxfps', '20')

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics, dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from metor.client import FrontendLaunchContext, FrontendProfileCatalog
from metor.core.api import GuiPreferencesEvent
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.views.secondary import secondary_view
from metor.ui.gui.widgets import Action

from gui_native_render import capture_viewport
from gui_native_x11 import NativeX11Input, rectangle


DEADLINE_SECONDS = 30.0
POLL_SECONDS = 0.05
SETTLE_SECONDS = 0.3
LAYOUT_FRAMES = 6
WHEEL_STEPS = 12
DRAG_STEPS = 6
DRAG_PIXELS = 180
GEOMETRY_TOLERANCE = 1.0


class ScrollingHarness(App):
    """Drive real XTest input through SDL at a deliberately limited frame rate."""

    def __init__(self, output: Path) -> None:
        """Retain only synthetic presentation evidence and completion state."""
        super().__init__()
        self.title = 'Metor'
        self.output = output
        self.completed = False
        self.closed = False
        self.native = NativeX11Input()

    def build(self) -> BoxLayout:
        """Use production settings and profile pages in their wide detail allocation."""
        Window.size = (1180, 760)
        Metrics.fontscale = 1.5
        self.gui = GuiController(
            FrontendLaunchContext('scroll-fixture', Mock()), simulator=True
        )
        self.gui.state.covered = False
        self.gui.state.preferences = GuiPreferencesEvent('scroll-fixture')
        self.gui.state.route = Route('V17')
        # Exercise the real restored-position path near the end of a long page.
        self.gui.state.secondary_scroll[self.gui.state.route] = 0.01
        root = BoxLayout()
        root.add_widget(Widget(size_hint_x=None, width=dp(361)))
        self.detail = BoxLayout(padding=dp(24))
        root.add_widget(self.detail)
        self.install_page()
        return root

    def install_page(self) -> None:
        """Attach an actual secondary page without a native effect override."""
        self.detail.clear_widgets()
        self.panel = secondary_view(self.gui, lambda: None)
        self.detail.add_widget(self.panel)
        self.scroll = next(
            item
            for item in self.panel.walk(restrict=True)
            if isinstance(item, ScrollView)
        )

    def on_start(self) -> None:
        """Arm native input only after the real window is attached."""
        Clock.schedule_once(self.deadline, DEADLINE_SECONDS)
        self.after_layout(self.begin_wheel)

    def deadline(self, _elapsed: float) -> None:
        """Fail a missing callback or incomplete interaction within a fixed budget."""
        assert self.completed, 'Native secondary scrolling did not complete'

    def after_layout(
        self, callback: Callable[[], None], frames: int = LAYOUT_FRAMES
    ) -> None:
        """Allow nested texture/layout work to finish without assigning geometry."""
        if frames:
            Clock.schedule_once(lambda _dt: self.after_layout(callback, frames - 1), 0)
        else:
            callback()

    def settled(self, callback: Callable[[], None]) -> None:
        """Wait for delivered wheel input and actual kinetic motion to stop."""
        stable_since: float | None = None

        def poll(_elapsed: float) -> bool:
            nonlocal stable_since
            effect = self.scroll.effect_y
            idle = not self.native._wheel and (
                effect is None or (effect.velocity == 0 and effect.overscroll == 0)
            )
            if not idle:
                stable_since = None
            elif stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= SETTLE_SECONDS:
                callback()
                return False
            return True

        Clock.schedule_interval(poll, POLL_SECONDS)

    def footer(self) -> Action:
        """Locate the complete production Exit action, not a synthetic target."""
        return next(
            item
            for item in self.panel.walk(restrict=True)
            if isinstance(item, Action) and item.accessible_name == 'Exit Metor'
        )

    def begin_wheel(self) -> None:
        """Cross the lower boundary using one actual native wheel burst."""
        self.native.activate()
        assert self.scroll.children[0].height > self.scroll.height
        self.native.scroll(self.scroll, downward=True, steps=WHEEL_STEPS)
        self.settled(self.check_footer)

    def check_footer(self) -> None:
        """Require the entire footer after the slow-frame wheel bounce has ended."""
        action = rectangle(self.footer())
        viewport = rectangle(self.scroll)
        assert action[1] >= viewport[1] - GEOMETRY_TOLERANCE, (
            'Settled wheel input left the footer clipped',
            action,
            viewport,
        )
        assert action[1] + action[3] <= viewport[1] + viewport[3] + GEOMETRY_TOLERANCE
        assert self.root is not None
        capture_viewport(self.root, self.output)
        self.before_drag = rectangle(self.scroll.children[0])
        self.drag(self.check_long_drag)

    def drag(self, complete: Callable[[], None]) -> None:
        """Press, move, and release the native pointer across separate SDL frames."""
        native = self.native
        assert native.window is not None
        left, bottom, width, height = rectangle(self.scroll)
        x, y, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
        assert native.x11.XTranslateCoordinates(
            native.display,
            native.window,
            native.root,
            0,
            0,
            ctypes.byref(x),
            ctypes.byref(y),
            ctypes.byref(child),
        )
        point_x = x.value + int(left + width / 2)
        point_y = y.value + int(Window.height - bottom - height * 0.6)

        def move(distance: int) -> None:
            native.xtest.XTestFakeMotionEvent(
                native.display, -1, point_x, point_y + distance, 0
            )
            native.x11.XFlush(native.display)

        def press(_elapsed: float) -> None:
            native.xtest.XTestFakeButtonEvent(native.display, 1, 1, 0)
            native.x11.XFlush(native.display)
            advance(1)

        def advance(step: int) -> None:
            def frame(_elapsed: float) -> None:
                move(step * DRAG_PIXELS // DRAG_STEPS)
                if step < DRAG_STEPS:
                    advance(step + 1)
                else:
                    Clock.schedule_once(release, POLL_SECONDS)

            Clock.schedule_once(frame, POLL_SECONDS)

        def release(_elapsed: float) -> None:
            native.xtest.XTestFakeButtonEvent(native.display, 1, 0, 0)
            native.x11.XFlush(native.display)
            self.settled(complete)

        move(0)
        Clock.schedule_once(press, POLL_SECONDS)

    def check_long_drag(self) -> None:
        """Long content remains draggable after the wheel boundary is reached."""
        current = rectangle(self.scroll.children[0])
        assert self.gui.state.route == Route('V17')
        assert current[1] < self.before_drag[1] - dp(48), (self.before_drag, current)
        print('NATIVE_GUI_LONG_PAGE_WHEEL_AND_DRAG_OK', flush=True)
        self.gui.state.route = Route('V20')
        self.gui.profiles.page = FrontendProfileCatalog((), None, None)
        self.install_page()
        self.after_layout(self.begin_short_wheel)

    def begin_short_wheel(self) -> None:
        """Apply the same physical input to a profile page that fits completely."""
        assert self.scroll.children[0].height <= self.scroll.height
        self.short_geometry = rectangle(self.scroll.children[0])
        self.native.scroll(self.scroll, downward=True, steps=WHEEL_STEPS)
        self.settled(self.check_short_wheel)

    def check_short_wheel(self) -> None:
        """A fitting page remains stable after native wheel delivery."""
        self.check_short_position()
        self.drag(self.check_short_drag)

    def check_short_position(self) -> None:
        """Compare actual content bounds rather than checking policy flags."""
        current = rectangle(self.scroll.children[0])
        assert all(
            abs(a - b) <= GEOMETRY_TOLERANCE
            for a, b in zip(current, self.short_geometry, strict=True)
        )

    def check_short_drag(self) -> None:
        """A drag on a fitting page leaves the visible controls in place."""
        self.check_short_position()
        assert self.gui.state.route == Route('V20')
        self.completed = True
        self.stop()

    def on_stop(self) -> None:
        """Release the synthetic pointer and isolated controller on every exit."""
        if self.closed:
            return
        self.closed = True
        self.native.close()
        if hasattr(self, 'gui'):
            self.gui.close()


def main() -> None:
    """Run the actual native interaction gate with an explicit completion check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    app = ScrollingHarness(args.output)
    try:
        app.run()
        assert app.completed, 'Native scrolling window closed before verification'
    finally:
        app.on_stop()
    print('NATIVE_GUI_SCROLLING_OK', flush=True)


if __name__ == '__main__':
    main()
