"""Native settings editor focus and captured-expectation probes with synthetic Core metadata."""

from collections.abc import Callable
from dataclasses import replace
from unittest.mock import patch

from kivy.clock import Clock
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.metrics import dp

from metor.core.api import SettingSnapshotEntry
from metor.ui.gui.app import MetorApp
from metor.ui.gui.views.settings.editor import SettingEditor
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.keyboard import KeyboardKey


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
