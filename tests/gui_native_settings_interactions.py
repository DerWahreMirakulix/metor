"""Native settings wheel coverage and localized inert audio enumeration."""

from collections.abc import Callable
import threading
import time
from unittest.mock import patch

from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView

from metor.client.platform import AudioEndpoint
from metor.ui.gui.app import MetorApp
from metor.ui.gui.constants import Geometry
from metor.ui.gui.platform.audio import HeadsetAudio
from metor.ui.gui.views.audio import show_audio_routes
from metor.ui.gui.widgets import Action, SettingRow
from metor.ui.gui.widgets.sheet import ActionSheet


def exercise_settings_interactions(app: MetorApp, complete: Callable[[], None]) -> None:
    """Exercise real window input and held synthetic endpoint reads without hardware IO."""
    assert app.shell is not None and app.shell._detail is not None
    shell, controller = app.shell, app.controller
    detail = shell._detail
    scroll = next(item for item in detail.walk() if isinstance(item, ScrollView))
    rows = tuple(item for item in detail.walk() if isinstance(item, SettingRow))
    assert abs(scroll.width - detail.width) < 1 and abs(scroll.right - detail.right) < 1
    assert abs(scroll.x - detail.x) < 1
    limit = (
        Geometry.WIDE_MAX
        if shell.width >= dp(Geometry.BREAKPOINT)
        else Geometry.COMPACT_MAX
    )
    assert all(row.width <= dp(limit) + 1 for row in rows)
    assert scroll.children[0].height > scroll.height
    left, bottom = detail.to_window(*detail.pos)
    points = [
        (left + dp(4), bottom + detail.height / 2),
        (left + detail.width - dp(4), bottom + detail.height / 2),
        (left + detail.width / 2, bottom + detail.height - dp(4)),
        (left + detail.width / 2, bottom + dp(4)),
    ]

    def settled(callback: Callable[[], None], frames: int = 6) -> None:
        """Wait through measured layout and the real native input dispatch frames."""
        if frames:
            Clock.schedule_once(lambda _dt: settled(callback, frames - 1), 0)
        else:
            callback()

    def wheel(index: int) -> None:
        """Send a vertical wheel event in each gutter and outer padding region."""
        if index == len(points):
            audio()
            return
        scroll.scroll_y = 0.5
        x, y = points[index]
        touch = MouseMotionEvent(
            'mouse',
            f'settings-wheel-{index}',
            (x / Window.width, y / Window.height, 'scrollup'),
            is_touch=True,
        )
        touch.scale_for_screen(Window.width, Window.height)
        EventLoop.post_dispatch_input('begin', touch)
        EventLoop.post_dispatch_input('end', touch)

        def check() -> None:
            assert scroll.scroll_y < 0.49, (index, scroll.scroll_y, points[index])
            wheel(index + 1)

        settled(check)

    def audio() -> None:
        """Hold a real scheduler worker at a synthetic read-only audio boundary."""
        original = controller.simulator, controller.native_audio
        controller.simulator, controller.native_audio = False, True
        routes = controller.voice.routes
        routes.scanned = True
        routes.endpoints = ()
        expected = (AudioEndpoint(4, 'Synthetic USB headset', True, True),)
        release, started = threading.Event(), threading.Event()
        position = scroll.scroll_y

        def enumerate_devices() -> tuple[AudioEndpoint, ...]:
            started.set()
            if not release.wait(5):
                raise TimeoutError('Synthetic endpoint enumeration was not released')
            return expected

        enumeration = patch.object(HeadsetAudio, 'endpoints', enumerate_devices)
        enumeration.start()

        def cleanup(*_args: object) -> None:
            release.set()
            enumeration.stop()
            controller.simulator, controller.native_audio = original

        app.bind(on_stop=cleanup)
        show_audio_routes(controller, app.refresh)

        def unchanged() -> None:
            assert shell._detail is detail
            assert scroll in detail.walk() and rows == tuple(
                item for item in detail.walk() if isinstance(item, SettingRow)
            )
            assert abs(scroll.scroll_y - position) < 0.001
            assert not controller.state.busy

        def begin() -> None:
            sheet = ActionSheet.current
            assert sheet is not None
            unchanged()
            refresh = next(
                item
                for item in sheet.walk()
                if isinstance(item, Action)
                and item.accessible_name == 'Refresh audio devices'
            )
            refresh.dispatch('on_release')
            assert started.wait(1) and routes.scanning
            settled(pending)

        def pending() -> None:
            unchanged()
            sheet = ActionSheet.current
            assert sheet is not None
            assert any(
                isinstance(item, Action)
                and item.disabled
                and item.accessible_name == 'Finding audio devices…'
                for item in sheet.walk()
            )
            release.set()
            deadline = time.monotonic() + 5

            def delivered(_dt: float) -> None:
                unchanged()
                if routes.scanning:
                    assert time.monotonic() < deadline, 'Audio worker did not finish'
                    Clock.schedule_once(delivered, 0)
                    return
                assert routes.endpoints == expected and not routes.status
                settled(finish)

            Clock.schedule_once(delivered, 0)

        def finish() -> None:
            unchanged()
            sheet = ActionSheet.current
            assert sheet is not None
            assert any(
                isinstance(item, Action)
                and not item.disabled
                and item.accessible_name == 'Choose microphone'
                for item in sheet.walk()
            )
            sheet.dismiss()
            cleanup()
            app.unbind(on_stop=cleanup)
            print('NATIVE_SETTINGS_FULL_PANE_WHEEL_AND_LOCAL_AUDIO_REFRESH_OK')
            complete()

        settled(begin)

    wheel(0)
