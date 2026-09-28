"""Native DPI-only and breakpoint reflow checks without Core communication."""

from __future__ import annotations

# ruff: noqa: E402

import argparse
import ctypes
import os
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path
from typing import cast

os.environ['KIVY_NO_ARGS'] = '1'
if os.name == 'nt':
    os.environ['KCFG_GRAPHICS_WINDOW_STATE'] = 'hidden'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.config import Config

# SDL's offscreen drawable needs its first native dimensions before Window import.
Config.set('graphics', 'width', '1180')
Config.set('graphics', 'height', '984')

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics, dp
from kivy.uix.scrollview import ScrollView

from metor.client import FrontendHost, FrontendLaunchContext
from metor.core.api import (
    ContactEntry,
    ClientRestrictedEvent,
    ClientUnlockMethod,
    Delivery,
    DropConversationSummaryEntry,
    RuntimeSnapshotEvent,
    SettingSnapshotEntry,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.constants import Geometry
from metor.ui.gui.platform import DeviceConfiguration
from metor.ui.gui.state import Route
from metor.ui.gui.state.notifications import NoticeKind
from metor.ui.gui.runtime.voice.press import PressPhase
from metor.ui.gui.widgets import Action, Label, SecretInput, TextField
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.views.settings.editor import SettingEditor
from metor.ui.gui.views.security import security_view


def move_between_monitors(
    app: MetorApp, complete: Callable[[], None], target_output: Path
) -> None:
    """Moves this fixture's own HWND between different-DPI Windows monitors.

    Args:
        app: Running native simulator window.
        complete: Continuation after the original monitor is restored.
        target_output: Native render capture while on the second monitor.
    Returns:
        None
    """
    if os.name != 'nt':
        raise RuntimeError('Physical monitor move requires Windows')
    user32 = ctypes.windll.user32
    shcore = ctypes.windll.shcore
    handle = int(Window.get_window_info().window)
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )
    monitors: list[tuple[int, tuple[int, int, int, int], int]] = []
    shcore.GetDpiForMonitor.argtypes = [
        wintypes.HMONITOR,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
    ]

    def collect(
        monitor: int,
        _device: int,
        bounds: ctypes.POINTER[wintypes.RECT],
        _data: int,
    ) -> int:
        """Captures current native monitor bounds and effective DPI.

        Args:
            monitor: Native monitor handle.
            _device: Unused native device context.
            bounds: Monitor rectangle in this process's coordinate space.
            _data: Unused callback data.
        Returns:
            int: Nonzero to continue enumeration.
        """
        x_dpi, y_dpi = ctypes.c_uint(), ctypes.c_uint()
        result = shcore.GetDpiForMonitor(
            monitor, 0, ctypes.byref(x_dpi), ctypes.byref(y_dpi)
        )
        assert result == 0 and x_dpi.value == y_dpi.value
        rect = bounds.contents
        monitors.append(
            (
                monitor,
                (rect.left, rect.top, rect.right, rect.bottom),
                x_dpi.value,
            )
        )
        return 1

    callback = callback_type(collect)
    user32.EnumDisplayMonitors.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        callback_type,
        wintypes.LPARAM,
    ]
    assert user32.EnumDisplayMonitors(None, None, callback, 0)
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    current = user32.MonitorFromWindow(handle, 2)
    current_dpi = next(dpi for monitor, _bounds, dpi in monitors if monitor == current)
    target = next(
        (
            (bounds, dpi)
            for monitor, bounds, dpi in monitors
            if monitor != current and dpi != current_dpi
        ),
        None,
    )
    if target is None:
        print('NATIVE_GUI_DIFFERENT_DPI_MONITOR_UNAVAILABLE')
        complete()
        return
    original = wintypes.RECT()
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    assert user32.GetWindowRect(handle, ctypes.byref(original))
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    left, top, _right, _bottom = target[0]
    assert user32.SetWindowPos(handle, None, left + 32, top + 32, 0, 0, 0x5)

    def on_target(_elapsed: float) -> None:
        """Checks a real display transition before returning to the original monitor.

        Args:
            _elapsed: Native move settlement delay.
        Returns:
            None
        """
        assert app.shell is not None
        assert user32.MonitorFromWindow(handle, 2) != current
        assert Window.dpi == target[1], (Window.dpi, target[1])
        assert app.shell._pixel_scale == dp(1)
        assert app.controller.state.route.view == 'V06'
        assert app.shell._root_panel is not None
        assert (
            abs(app.shell._root_panel.tabs[Delivery.DROP].height - dp(Geometry.TARGET))
            <= 1
        )
        assert Window.minimum_width == Geometry.MIN_WIDTH
        target_output.parent.mkdir(parents=True, exist_ok=True)
        assert app.root is not None
        app.root.export_to_png(str(target_output))
        assert user32.SetWindowPos(
            handle,
            None,
            original.left,
            original.top,
            original.right - original.left,
            original.bottom - original.top,
            0x4,
        )

        def restored(_elapsed: float) -> None:
            """Checks the return display and resumes deterministic DPI tests.

            Args:
                _elapsed: Native return-move settlement delay.
            Returns:
                None
            """
            assert app.shell is not None
            assert user32.MonitorFromWindow(handle, 2) == current
            assert Window.dpi == current_dpi, (Window.dpi, current_dpi)
            assert app.shell._pixel_scale == dp(1)
            print(f'NATIVE_GUI_PHYSICAL_MONITOR_MOVE_OK {current_dpi}->{target[1]}')
            complete()

        Clock.schedule_once(restored, 0.5)

    Clock.schedule_once(on_target, 0.5)


def after_layout(callback: Callable[[], None], frames: int = 5) -> None:
    """Runs an assertion after nested native layouts and focus restoration settle.

    Args:
        callback: Zero-argument assertion or next action.
        frames: Remaining native layout frames.
    Returns:
        None
    """
    if frames:
        Clock.schedule_once(lambda _elapsed: after_layout(callback, frames - 1), 0)
    else:
        callback()


def main() -> None:
    """Exercises a fixed-size DPI event, breakpoint transition and covered state.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--move-monitors', action='store_true')
    args = parser.parse_args()
    app = MetorApp(
        FrontendLaunchContext('Simulator', cast(FrontendHost, object())),
        DeviceConfiguration(mode='simulator', width_px=1180, height_px=960),
    )
    controller = app.controller
    controller.open_profile()
    controller.state.snapshot = RuntimeSnapshotEvent(
        profile='Simulator',
        onion='',
        epoch='simulator',
        profile_instance_id='dpi-fixture',
        contacts=[ContactEntry('Rhea', 'rhea')],
        conversations=[DropConversationSummaryEntry('Rhea', 'rhea', 1)],
    )
    controller.state.covered = False
    controller.state.route = Route('V06')
    original_dpi = 0.0
    original_density = 0.0
    original_metrics_density = 0.0
    started = time.monotonic()

    def verify_peer(expected_wide: bool) -> None:
        """Checks route, draft, focus and current-scale native dimensions.

        Args:
            expected_wide: Whether the current pixel scale permits the master pane.
        Returns:
            None
        """
        assert app.shell is not None
        shell, state = app.shell, controller.state
        assert state.route == Route('V08', 'rhea', Delivery.DROP)
        assert state.drafts[('rhea', Delivery.DROP)] == 'DPI draft'
        peer = shell._peer_panel
        assert peer is not None and peer.route == state.route
        assert peer.composer.entry.text == 'DPI draft'
        assert peer.composer.entry.focus
        assert abs(peer.header.height - dp(Geometry.TARGET)) <= 1
        assert Window.minimum_width == Geometry.MIN_WIDTH
        assert Window.minimum_height == Geometry.MIN_HEIGHT + 24
        assert (shell._master is not None) is expected_wide
        if expected_wide:
            assert shell._root_panel is not None and shell._master is not None
            assert abs(shell._master.width - dp(Geometry.MASTER)) <= 1
        assert controller.client is None

    def start() -> None:
        """Places a focused draft in the wide peer view before any metric change.

        Args:
            None
        Returns:
            None
        """
        nonlocal original_dpi, original_density, original_metrics_density
        assert app.shell is not None
        original_dpi, original_density = Window.dpi, Window._density
        original_metrics_density = Metrics.density
        if app.shell.width < dp(Geometry.BREAKPOINT):
            assert time.monotonic() - started < 30, 'Native layout did not settle'
            Clock.schedule_once(lambda _elapsed: start(), 0.1)
            return
        assert app.shell.width >= dp(Geometry.BREAKPOINT), (
            app.shell.width,
            Window.size,
            Window.system_size,
            app.root.size if app.root is not None else None,
            app.viewport.size if app.viewport is not None else None,
            [(type(widget).__name__, widget.size) for widget in app.root.children]
            if app.root is not None
            else None,
            [
                (
                    type(widget).__name__,
                    widget.size_hint,
                    widget.size_hint_min,
                    widget.size_hint_max,
                )
                for widget in app.root.children
            ]
            if app.root is not None
            else None,
            [type(widget).__name__ for widget in Window.children],
            Window.dpi,
            Window._density,
            Metrics.density,
            dp(Geometry.BREAKPOINT),
        )
        controller.navigate(Route('V08', 'rhea', Delivery.DROP), from_root=True)
        controller.state.set_draft('rhea', Delivery.DROP, 'DPI draft')
        app.shell.render()
        assert app.shell._peer_panel is not None
        entry = app.shell._peer_panel.composer.entry
        entry.focus = True
        entry.cursor = (len('DPI draft'), 0)
        before = app.shell.width, Window.size
        first_peer = app.shell._peer_panel
        Window.dpi = original_dpi * 1.1
        Metrics.density = original_metrics_density * 1.1

        def fixed_size() -> None:
            """Proves DPI alone causes reflow without a shell-size notification.

            Args:
                None
            Returns:
                None
            """
            assert app.shell is not None
            assert abs(app.shell.width - before[0]) <= 1
            assert Window.size == before[1]
            assert abs(app.shell.height - (Window.height - dp(24))) <= 1
            assert app.shell._peer_panel is not first_peer
            verify_peer(True)
            held_ptt()

        after_layout(fixed_size)

    def held_ptt() -> None:
        """Keeps a pressed native PTT owner attached while pixels rescale."""
        assert app.shell is not None and app.shell._peer_panel is not None
        peer = app.shell._peer_panel
        press = controller.voice.press
        press.phase = PressPhase.RECORDING
        press.stop_requested = False
        peer.update()
        ptt = peer.composer.ptt
        assert ptt.parent is not None
        ptt._key_identity = '32'
        ptt.focus = True
        assert ptt.held
        Window.dpi = original_dpi * 1.2
        Metrics.density = original_metrics_density * 1.2

        def verify_held() -> None:
            """Checks that reflow did not stop or replace the active capture."""
            assert app.shell is not None
            assert app.shell._peer_panel is peer
            assert ptt.parent is not None and ptt.focus
            assert press.phase is PressPhase.RECORDING
            assert not press.stop_requested
            ptt._key_identity = None
            ptt.focus = False
            press.phase = PressPhase.IDLE
            press.held.clear()
            peer.update()
            peer.composer.entry.focus = True
            app.refresh()

            def released() -> None:
                """Reflows to current DPI once the original PTT target is released."""
                assert app.shell is not None
                assert app.shell._peer_panel is not peer
                verify_peer(True)
                Window.dpi = original_dpi * 1.4
                Window._density = original_density * 1.4
                Metrics.density = original_metrics_density * 1.4
                after_layout(breakpoint)

            after_layout(released)

        after_layout(verify_held)

    def breakpoint() -> None:
        """Proves the same route becomes compact without losing the active draft.

        Args:
            None
        Returns:
            None
        """
        verify_peer(False)
        Window.dpi = original_dpi
        Window._density = original_density
        Metrics.density = original_metrics_density
        after_layout(contacts)

    def contacts() -> None:
        """Checks the returning wide layout and prepares selected contact search.

        Args:
            None
        Returns:
            None
        """
        verify_peer(True)
        assert app.shell is not None and app.shell._root_panel is not None
        app.shell._root_panel.header_actions['V12'].dispatch('on_release')
        app.shell.render()
        controller.contacts.book.selecting = True
        controller.contacts.book.selected.add('rhea')
        assert app.shell._contacts_panel is not None
        contact = app.shell._contacts_panel
        contact.search.text = 'Rh'
        contact.search.cursor = (2, 0)
        contact.search.focus = True
        contact.update()
        Window.dpi = original_dpi * 1.1
        Metrics.density = original_metrics_density * 1.1

        def verify_contacts() -> None:
            """Checks query and selection across the replacement contact panel.

            Args:
                None
            Returns:
                None
            """
            assert app.shell is not None and app.shell._contacts_panel is not None
            replacement = app.shell._contacts_panel
            assert replacement is not contact
            assert controller.state.route.view == 'V12'
            assert controller.contacts.query == 'Rh'
            assert controller.contacts.book.selected == {'rhea'}
            assert replacement.search.text == 'Rh' and replacement.search.focus
            assert replacement.search.cursor == (2, 0)
            assert abs(replacement.search.height - dp(52)) <= 1
            form_reflow()

        after_layout(verify_contacts)

    def form_reflow() -> None:
        """Checks a nonsecret contact form retains its model values and native cursor.

        Args:
            None
        Returns:
            None
        """
        controller.contacts.begin('save')
        assert app.shell is not None
        app.shell.render()
        assert controller.state.route.view == 'V13'
        assert app.shell._detail is not None
        prior = app.shell._detail
        fields = [
            item for item in prior.walk(restrict=True) if isinstance(item, TextField)
        ]
        assert len(fields) == 2
        fields[0].text = 'contact-data'
        fields[1].text = 'Local Alias'
        fields[1].focus = True

        def change_metrics() -> None:
            """Moves an already settled caret before triggering secondary rebuild."""
            fields[1].cursor = (5, 0)
            Window.dpi = original_dpi * 1.2
            Metrics.density = original_metrics_density * 1.2
            after_layout(verify_form)

        def verify_form() -> None:
            """Confirms the replacement form preserved both content and focus.

            Args:
                None
            Returns:
                None
            """
            assert app.shell is not None and app.shell._detail is not None
            assert app.shell._detail is not prior
            assert controller.contacts.form is not None
            assert controller.contacts.form.raw == 'contact-data'
            assert controller.contacts.form.alias == 'Local Alias'
            replacement = [
                item
                for item in app.shell._detail.walk(restrict=True)
                if isinstance(item, TextField)
            ]
            assert [item.text for item in replacement] == [
                'contact-data',
                'Local Alias',
            ]
            assert replacement[1].focus
            settings_editor()

        after_layout(change_metrics)

    def settings_editor() -> None:
        """Checks an open Settings modal keeps its unsaved input on DPI change.

        Args:
            None
        Returns:
            None
        """
        controller.navigate(Route('V17'), from_root=True)
        assert app.shell is not None
        app.shell.render()
        editor = SettingEditor(
            controller,
            SettingSnapshotEntry(
                'daemon.test_limit',
                '10',
                'default',
                'Test',
                value_type='int',
                display_name='Test limit',
                constraints='Finite number',
                editable=True,
            ),
        )
        editor.show()
        editor.field.text = '77'
        editor.field.cursor = (2, 0)
        editor.field.focus = True
        Window.dpi = original_dpi * 1.1
        Metrics.density = original_metrics_density * 1.1

        def verify_editor() -> None:
            """Confirms modal identity, input, focus and current-scale centering.

            Args:
                None
            Returns:
                None
            """
            assert app.shell is not None
            assert controller.state.route.view == 'V17'
            assert ActionSheet.current is editor
            assert editor.field.text == '77'
            assert editor.field.focus
            assert abs(editor.field.height - dp(52)) <= 1
            assert abs(editor.actions.height - dp(48)) <= 1
            close = next(
                item
                for item in editor.header.children
                if getattr(item, 'accessible_name', None) == 'Close'
            )
            assert abs(close.width - dp(48)) <= 1
            assert abs(editor.center_x - Window.center[0]) <= 1
            assert abs(editor.width - min(dp(480), Window.width - dp(48))) <= 1
            editor.dismiss(animation=False)
            duplicate_alias_notifications()

        after_layout(verify_editor)

    def duplicate_alias_notifications() -> None:
        """Keeps the exact notice focused when two peers share a visible alias."""
        snapshot = controller.state.snapshot
        assert snapshot is not None
        controller.state.snapshot = replace(
            snapshot,
            contacts=[ContactEntry('Rhea', 'rhea'), ContactEntry('Rhea', 'mira')],
            conversations=[
                DropConversationSummaryEntry('Rhea', 'rhea', 1),
                DropConversationSummaryEntry('Rhea', 'mira', 1),
            ],
        )
        controller.notifications.poll()
        controller.navigate(Route('V16'), from_root=True)
        assert app.shell is not None
        app.shell.render()
        assert app.shell._detail is not None
        prior = app.shell._detail
        rows = [
            item
            for item in prior.walk(restrict=True)
            if isinstance(item, Action) and item.focus_key[:1] == ('notice',)
        ]
        assert len(rows) == 2
        assert rows[0].accessible_name == rows[1].accessible_name
        target = next(row for row in rows if row.focus_key[2] == 'mira')
        target.focus = True
        Window.dpi = original_dpi * 1.2
        Metrics.density = original_metrics_density * 1.2

        def verify_notice() -> None:
            """Confirms alias collision did not move focus to the other callback."""
            assert app.shell is not None and app.shell._detail is not None
            assert app.shell._detail is not prior
            focused = [
                item
                for item in app.shell._detail.walk(restrict=True)
                if isinstance(item, Action)
                and item.focus_key[:1] == ('notice',)
                and item.focus
            ]
            assert len(focused) == 1
            assert focused[0].focus_key == (
                'notice',
                NoticeKind.DROP.value,
                'mira',
            )
            cover()

        after_layout(verify_notice)

    def cover() -> None:
        """Checks DPI changes cannot uncover or resurrect private peer text.

        Args:
            None
        Returns:
            None
        """
        controller.security.restriction = ClientRestrictedEvent(
            ClientUnlockMethod.PROFILE_PASSWORD, '11' * 32, '22' * 16
        )
        controller.state.covered = True
        controller.state.route = Route('V05')
        app.refresh()
        assert app.shell is not None
        app.shell.render()
        prior_cover = app.shell._security_panel
        assert prior_cover is not None
        secret = next(
            item for item in prior_cover.walk() if isinstance(item, SecretInput)
        )
        secret.text = 'DPI secret input'
        secret.focus = True
        narrow_cover = security_view(controller, app.refresh)
        narrow_cover.width = dp(360)
        narrow_scroll = next(
            item for item in narrow_cover.walk() if isinstance(item, ScrollView)
        )
        prior_scroll_width = narrow_scroll.width
        Window.dpi = original_dpi * 1.3
        Metrics.density = original_metrics_density * 1.3

        def finish() -> None:
            """Captures the still-covered screen and restores process-local metrics.

            Args:
                None
            Returns:
                None
            """
            assert app.shell is not None
            assert controller.state.covered
            assert controller.state.route.view == 'V05'
            assert not any(
                isinstance(widget, Label) and 'DPI draft' in widget.text
                for widget in app.shell.walk()
            )
            assert app.shell._root_panel is None
            assert app.shell._security_panel is not None
            assert app.shell._security_panel is prior_cover
            assert app.shell._security_panel.get_root_window() is not None
            assert secret.get_root_window() is not None
            assert secret.text == 'DPI secret input' and secret.focus
            assert abs(secret.height - dp(52)) <= 1
            assert narrow_scroll.width < prior_scroll_width
            assert narrow_scroll.width <= (
                narrow_cover.width
                - narrow_cover.padding[0]
                - narrow_cover.padding[2]
                + 1
            )
            assert Window.minimum_width == Geometry.MIN_WIDTH
            secret.text = ''
            args.output.parent.mkdir(parents=True, exist_ok=True)
            assert app.root is not None
            app.root.export_to_png(str(args.output))
            Window.dpi = original_dpi
            Window._density = original_density
            Metrics.density = original_metrics_density
            print('NATIVE_GUI_DPI_REFLOW_OK')
            app.stop()

        after_layout(finish)

    Clock.schedule_once(
        lambda _elapsed: (
            move_between_monitors(app, app.stop, args.output.with_suffix('.target.png'))
            if args.move_monitors
            else start()
        ),
        1.0,
    )
    app.run()


if __name__ == '__main__':
    main()
