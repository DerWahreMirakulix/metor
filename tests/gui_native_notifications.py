"""Native notification actions and centered conversation metadata without Core IO."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.metrics import dp

from metor.core.api import (
    ContactEntry,
    Delivery,
    DropConversationSummaryEntry,
    GuiPreferences,
    GuiPreferencesEvent,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.context import ContextAction
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.symbol import IconAction


PEER = 'a4dqobyha4dqobyha4dqobyha4dqobyha4dqobyha4dqobyha4dwc6ad'


def exercise_notification_actions(
    app: MetorApp, output: Path, complete: Callable[[], None]
) -> None:
    """Uses native pointer and keyboard input to verify contained per-entry actions.

    Args:
        app: Running renderer fixture without a Core client or physical media.
        output: Existing capture whose directory also receives native entry frames.
        complete: Continuation after local dismissal and pin geometry are checked.
    """
    controller, state = app.controller, app.controller.state
    assert app.shell is not None
    shell = app.shell
    state.covered = False
    state.snapshot = RuntimeSnapshotEvent(
        'Simulator',
        '',
        epoch='notification-actions',
        profile_instance_id='notification-instance',
        contacts=[ContactEntry('Pinned notification contact', PEER)],
        conversations=[
            DropConversationSummaryEntry('Pinned notification contact', PEER, 2)
        ],
    )
    state.preferences = GuiPreferencesEvent(
        'notification-instance', preferences=GuiPreferences(pins=[PEER])
    )
    controller.notifications.store.abandon()
    controller.notifications.poll()
    state.route = Route('V06')
    state.root_delivery = Delivery.DROP
    state.back_stack.clear()
    state.navigate(Route('V16'))
    shell.render()

    def settled(callback: Callable[[], None], frames: int = 8) -> None:
        """Waits for nested toolkit layout before input or final native measurements."""
        if frames:
            Clock.schedule_once(lambda _elapsed: settled(callback, frames - 1), 0)
        else:
            callback()

    def target(key: str) -> Action:
        """Finds the current displayed target by its stable presentation identity."""
        return next(
            widget
            for widget in shell.walk()
            if isinstance(widget, Action) and widget.focus_key[:1] == (key,)
        )

    def click(action: Action) -> None:
        """Hits the actual native tree with a pointer rather than invoking callbacks."""
        x, y = action.to_window(*action.center)
        assert action.get_root_window() is not None and not action.disabled
        assert action.width >= dp(48) and action.height >= dp(48)
        touch = MouseMotionEvent(
            'mouse',
            'notification-action',
            (x / Window.width, y / Window.height, 'left'),
            is_touch=True,
        )
        touch.scale_for_screen(Window.width, Window.height)
        EventLoop.post_dispatch_input('begin', touch)
        EventLoop.post_dispatch_input('end', touch)

    def inspect_more() -> None:
        """Requires a visible contained menu button that does not open its notification."""
        more, notice = target('notice_more'), target('notice')
        assert isinstance(more, IconAction) and isinstance(notice, ContextAction)
        assert more.accessible_name == 'Notification actions'
        assert more.x >= notice.x and more.right <= notice.right
        assert more.y >= notice.y and more.top <= notice.top
        assert abs(more.center_y - notice.center_y) <= dp(1)
        assert app.root is not None
        app.root.export_to_png(str(output.with_stem(output.stem + '-notifications')))
        click(more)
        assert state.route.view == 'V16'
        assert ActionSheet.current is not None
        settled(select_entries)

    def select_entries() -> None:
        """Enters local selection through the menu while preserving its primary route."""
        sheet = ActionSheet.current
        assert sheet is not None and sheet.heading == 'Notification actions'
        select = next(
            widget
            for widget in sheet.walk()
            if isinstance(widget, Action)
            and widget.accessible_name == 'Select notifications'
        )
        click(select)
        assert ActionSheet.current is None
        shell.render()
        settled(select_exact_entry)

    def select_exact_entry() -> None:
        """Uses the contained checkbox as an exact selection action without navigation."""
        select = target('notice_select')
        assert select.accessible_name == 'Select notification'
        click(select)
        shell.render()
        assert len(controller.notifications.store.selected) == 1
        assert state.route.view == 'V16'
        controller.back()
        assert not controller.notifications.store.selecting
        assert state.route.view == 'V06'
        state.navigate(Route('V16'))
        shell.render()
        settled(keyboard_more)

    def keyboard_more() -> None:
        """Opens equivalent contextual actions through focused Shift+F10."""
        notice = target('notice')
        notice.focus = True
        Window.dispatch('on_key_down', 291, 67, '', ['shift'])
        Window.dispatch('on_key_up', 291, 67)
        assert state.route.view == 'V16' and ActionSheet.current is not None
        settled(dismiss_entry)

    def dismiss_entry() -> None:
        """Dismisses one presentation entry while leaving Core unread state untouched."""
        sheet = ActionSheet.current
        assert sheet is not None
        dismiss = next(
            widget
            for widget in sheet.walk()
            if isinstance(widget, Action) and widget.accessible_name == 'Dismiss'
        )
        click(dismiss)
        assert ActionSheet.current is None and not controller.notifications.store.items
        assert state.snapshot is not None
        assert state.snapshot.conversations[0].unread_count == 2
        controller.notifications.poll()
        assert not controller.notifications.store.items
        state.navigate(Route('V06'))
        shell.render()
        settled(inspect_pin)

    def inspect_pin() -> None:
        """Keeps pin, unread badge and menu centered inside one conversation surface."""
        root = shell._root_panel
        assert root is not None
        row = root.rows[PEER]
        assert row.pin.parent is row.group
        assert abs(row.pin.center_y - row.more.center_y) <= dp(1)
        assert row.pin.right <= row.more.x
        assert row.badge.right <= row.more.x
        assert row.more.right <= row.action.right
        assert app.root is not None
        app.root.export_to_png(str(output.with_stem(output.stem + '-pinned-row')))
        row.update(replace(row.entry, pinned=False, unseen=0))
        assert row.pin.parent is None and row.badge.parent is None
        assert controller.client is None
        print('NATIVE_GUI_NOTIFICATION_MORE_SELECTION_DISMISS_PIN_ALIGNMENT_OK')
        complete()

    settled(inspect_more)
