"""Native settings editor focus and captured-expectation probes with synthetic Core metadata."""

from collections.abc import Callable
from dataclasses import replace
import threading
import time
from unittest.mock import Mock, patch

from kivy.clock import Clock
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView

from metor.client.platform import (
    DeviceSettingDescriptor,
    DeviceSettingKind,
    DeviceSettingResult,
    DeviceSettingStatus,
)
from metor.core.api import ConfigListDataEvent, SettingSnapshotEntry
from metor.ui.gui.app import MetorApp
from metor.ui.gui.runtime.device.settings import DeviceSettings
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.views.settings.editor import SettingEditor
from metor.ui.gui.widgets import Action, Label, SettingRow
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.keyboard import KeyboardKey


def exercise_settings_loading(app: MetorApp, complete: Callable[[], None]) -> None:
    """Publishes delayed settings together and preserves focus/scroll on readback.

    This fixture uses the native event loop and a controlled device worker, with
    synthetic public Core metadata and no real profile or hardware writes.

    Args:
        app: Running native settings fixture with protected preferences.
        complete: Continuation after initial layout and refreshed-focus checks.
    Returns:
        None
    """
    assert app.shell is not None
    shell, controller = app.shell, app.controller
    state = controller.state
    assert state.preferences is not None
    state.capabilities = state.capabilities | {'safe_setting_descriptors'}
    core = controller.core_settings
    core.initial_read_complete = True
    core.loaded = True
    core.error = 'This setting changed elsewhere.'
    core.cover()
    assert not core.initial_read_complete and not core.loaded and core.error
    assert not controller.device.settings.available
    shell.render()
    assert any(
        isinstance(widget, Label) and widget.text == 'Loading settings…'
        for widget in shell.walk()
    )
    assert not any(isinstance(widget, SettingRow) for widget in shell.walk())
    release = threading.Event()
    descriptor = DeviceSettingDescriptor(
        'haptic_feedback', 'Haptic feedback', DeviceSettingKind.BOOLEAN
    )

    def device_read(_key: str) -> DeviceSettingResult:
        """Holds one synthetic metadata read until the visible loading probe."""
        if not release.wait(5):
            raise TimeoutError('Synthetic device read was not released')
        return DeviceSettingResult(DeviceSettingStatus.APPLIED, True)

    controller.device.settings.close()
    device = DeviceSettings(Mock(describe=lambda: (descriptor,), read=device_read))
    controller.device.settings = device
    assert device.refresh()
    shell.render()
    assert any(
        isinstance(widget, Label) and widget.text == 'Loading settings…'
        for widget in shell.walk()
    )
    assert not any(isinstance(widget, SettingRow) for widget in shell.walk())
    event = ConfigListDataEvent(
        'daemon',
        'synthetic-instance',
        [
            SettingSnapshotEntry(
                'daemon.auto_reconnect',
                'True',
                'global',
                'Core Daemon',
                value_type='bool',
                display_name='Automatically reconnect Live',
                display_group='Live',
                editable=True,
                scope='profile',
            )
        ],
    )
    controller.core_settings.install(
        Update(state.generation, 'core-settings:read', event)
    )
    assert (
        core.initial_read_complete and core.error == 'This setting changed elsewhere.'
    )
    shell.render()
    assert not any(isinstance(widget, SettingRow) for widget in shell.walk())
    release.set()
    deadline = time.monotonic() + 5

    def after_layout(callback: Callable[[float], None], frames: int = 5) -> None:
        """Lets nested native measurements settle before comparing focus/geometry."""
        if frames:
            Clock.schedule_once(lambda _elapsed: after_layout(callback, frames - 1), 0)
        else:
            callback(0)

    def ready(_elapsed: float) -> None:
        """Waits for the real device worker result and displays both sources once."""
        device.poll()
        if not device.loaded:
            assert time.monotonic() < deadline, 'Synthetic device read did not settle'
            Clock.schedule_once(ready, 0)
            return
        shell.render()
        rows = [widget for widget in shell.walk() if isinstance(widget, SettingRow)]
        assert any(row.focus_key == ('setting', 'Haptic feedback') for row in rows)
        assert any(
            row.focus_key == ('setting', 'Automatically reconnect Live') for row in rows
        )
        assert not any(
            isinstance(widget, Label) and widget.text == 'Loading settings…'
            for widget in shell.walk()
        )
        after_layout(refresh)

    def refresh(_elapsed: float) -> None:
        """Changes a displayed value while preserving the focused row identity."""
        timeout = next(
            widget
            for widget in shell.walk()
            if isinstance(widget, SettingRow)
            and widget.focus_key == ('setting', 'Application timeout')
        )
        timeout.focus = True
        scroll = next(
            widget for widget in shell._detail.walk() if isinstance(widget, ScrollView)
        )
        scroll.scroll_y = 0.4
        current = state.preferences
        assert current is not None
        state.preferences = replace(
            current,
            preferences_revision=current.preferences_revision + 1,
            preferences=replace(current.preferences, idle_seconds=120),
        )
        controller.core_settings.reload()
        shell.render()
        assert not any(
            isinstance(widget, Label) and widget.text == 'Loading settings…'
            for widget in shell.walk()
        )
        after_layout(verify)

    def verify(_elapsed: float) -> None:
        """Checks restored native focus and normalized viewport after repaint."""
        timeout = next(
            widget
            for widget in shell.walk()
            if isinstance(widget, SettingRow)
            and widget.focus_key == ('setting', 'Application timeout')
        )
        scroll = next(
            widget for widget in shell._detail.walk() if isinstance(widget, ScrollView)
        )
        assert timeout.focus and '120 s' in timeout.accessible_name
        assert abs(scroll.scroll_y - 0.4) < 0.001
        timeout.focus = False
        complete()

    Clock.schedule_once(ready, 0)


def exercise_setting_editor(app: MetorApp, complete: Callable[[], None]) -> None:
    """Keeps typed input and native focus through a background snapshot change.

    Args:
        app: Running synthetic settings fixture; no real config writes are allowed.
        complete: Continuation after successful native interaction checks.
    Returns:
        None
    """
    entry = SettingSnapshotEntry(
        'daemon.max_pending_live_msgs',
        '100',
        'global',
        'Core Daemon',
        value_type='int',
        display_name='Pending Live limit',
        display_group='Advanced',
        description='Maximum retained pending Live messages for this profile.',
        constraints='Integer >= -1.',
        security_note='Existing pending messages remain preserved when the limit is lowered.',
        min_value=-1,
        editable=True,
        scope='profile',
    )
    sheet = SettingEditor(app.controller, entry)
    sheet.show()

    def check(_elapsed: float) -> None:
        """Dispatches native Save keys after snapshot reconciliation and validates its target.

        Args:
            _elapsed: Native focus/layout settling delay.
        Returns:
            None
        """
        state = app.controller.state
        assert state.snapshot is not None
        field = sheet.field
        field.text = '7'
        field.focus = True
        if not app.configuration.touch:
            assert app.input_dock.keyboard is None
        state.snapshot = replace(
            state.snapshot, revision=(state.snapshot.revision or 0) + 1
        )
        ActionSheet.reconcile()
        assert sheet.field is field and field.focus and field.text == '7'
        save = next(
            widget
            for widget in sheet.actions.children
            if isinstance(widget, Action) and widget.accessible_name == 'Save'
        )
        with patch.object(
            app.controller.core_settings, 'save', return_value=None
        ) as submit:
            field.text = '7.5'
            field.focus = False
            save.focus = True
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            submit.assert_not_called()
            assert 'Integer' in sheet.feedback.text
            field.text = '7'
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            submit.assert_called_once()
            assert submit.call_args.args[0].value == '100'
            assert submit.call_args.args[1] == 7
        save.focus = False
        sheet.feedback.text = ''
        complete()

    Clock.schedule_once(check, 0.2)


def exercise_setting_keyboard(app: MetorApp, complete: Callable[[], None]) -> None:
    """Types through the ordinary native modal veil and checks essential geometry.

    Args:
        app: Synthetic native settings application without any actual Core writes.
        complete: Continuation after the modal keyboard probe.
    Returns:
        None
    """

    def key(label: str) -> None:
        """Sends a synthetic touch through native hit testing and grabbed release.

        Args:
            label: Current visible software key.
        Returns:
            None
        """
        keyboard = app.input_dock.keyboard
        assert keyboard is not None
        button = next(
            widget
            for widget in keyboard.walk()
            if isinstance(widget, KeyboardKey) and widget.label.text == label
        )
        x, y = button.to_window(*button.center)
        touch = MouseMotionEvent(
            'mouse',
            'modal-' + label,
            (x / Window.width, y / Window.height, 'left'),
            is_touch=True,
        )
        touch.scale_for_screen(Window.width, Window.height)
        EventLoop.post_dispatch_input('begin', touch)
        EventLoop.post_dispatch_input('end', touch)

    def typed(_elapsed: float) -> None:
        """Verifies actual typing and reachable actions above the keyboard.

        Args:
            _elapsed: Native key-page layout delay.
        Returns:
            None
        """
        sheet = ActionSheet.current
        assert isinstance(sheet, SettingEditor)
        keyboard = app.input_dock.keyboard
        assert keyboard is not None
        key('7')
        assert sheet.field.text == '7' and sheet.field.focus
        assert sheet.y >= keyboard.top + dp(8)
        for action in sheet.actions.children:
            assert action.height >= dp(48)
            assert action.to_window(*action.pos)[1] >= keyboard.top + dp(8)
        assert sheet.field.to_window(*sheet.field.pos)[1] >= sheet.actions.top
        complete()

    def numbers(_elapsed: float) -> None:
        """Chooses the native numeric page above an already visible modal.

        Args:
            _elapsed: Native keyboard settling delay.
        Returns:
            None
        """
        key('123')
        Clock.schedule_once(typed, 0.3)

    def show() -> None:
        """Focuses a declared touch field to open its software keyboard.

        Args:
            None
        Returns:
            None
        """
        sheet = ActionSheet.current
        assert isinstance(sheet, SettingEditor)
        sheet.field.text = ''
        sheet.field.focus = True
        assert app.input_dock.keyboard is not None
        Clock.schedule_once(numbers, 0.3)

    exercise_setting_editor(app, show)
