"""Native lock feedback and Settings method selection with synthetic authorization events."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from kivy.clock import Clock
from kivy.uix.scrollview import ScrollView

from metor.core.api import (
    ClientRestrictedEvent,
    ClientUnlockMethod,
    LocalAuthRateLimitedEvent,
    QuickUnlockFailedEvent,
)
from metor.ui.gui.app import MetorApp
from metor.ui.gui.views.security import LockedView
from metor.ui.gui.widgets import Action, SettingRow
from metor.ui.gui.widgets.sheet import ActionSheet

from gui_native_render import capture_viewport


def settled(callback: Callable[[], None], frames: int = 8) -> None:
    """Wait for native font and layout callbacks to finish."""
    if frames:
        Clock.schedule_once(lambda _elapsed: settled(callback, frames - 1), 0)
    else:
        callback()


def exercise_lock_feedback(
    app: MetorApp, output: Path, complete: Callable[[], None]
) -> None:
    """Check stable failure geometry and a real elapsed countdown without authenticating."""
    assert app.shell is not None
    shell, controller = app.shell, app.controller
    security, state = controller.security, controller.state
    original = security.restriction
    security.restriction = ClientRestrictedEvent(
        ClientUnlockMethod.PROFILE_PASSWORD, '11' * 32, '22' * 16
    )
    state.status = ''
    shell.render()
    panel = shell._security_panel
    assert isinstance(panel, LockedView)
    field = panel.secret
    bounds: list[float] = []

    def initial() -> None:
        assert panel.activity.height == 0
        bounds.extend((panel.card.y, panel.card.height, field.y))
        field.focus = True
        with patch.object(security, 'unlock', return_value=True) as unlock:
            field.dispatch('on_text_validate')
            unlock.assert_called_once_with('')
        security.install(
            'security:unlock',
            QuickUnlockFailedEvent(challenge='33' * 32, salt='22' * 16),
        )
        shell.render()
        settled(failed)

    def failed() -> None:
        assert shell._security_panel is panel
        assert panel.secret is field and field.focus
        assert panel.activity.height == 0
        assert (
            max(
                abs(before - after)
                for before, after in zip(
                    bounds, (panel.card.y, panel.card.height, field.y), strict=True
                )
            )
            <= 1
        ), (bounds, (panel.card.y, panel.card.height, field.y))
        assert 'Could not unlock' in panel.feedback.text
        assert app.viewport is not None
        capture_viewport(
            app.viewport, output.with_stem(output.stem + '-password-error')
        )
        field.text = 'wrong synthetic password'
        with patch.object(security, 'unlock', return_value=True) as unlock:
            field.dispatch('on_text_validate')
            unlock.assert_called_once_with('wrong synthetic password')
            assert field.text == ''
        security.install('security:unlock', LocalAuthRateLimitedEvent(3))
        shell.render()
        field.text = 'kept while waiting'
        settled(cooling)

    def cooling() -> None:
        assert shell._security_panel is panel
        assert panel.feedback.text == 'Try again in 3 seconds'
        button = next(
            item
            for item in panel.walk()
            if isinstance(item, Action) and item.accessible_name == 'Unlock'
        )
        assert button.disabled
        with patch.object(security, 'unlock') as unlock:
            button.dispatch('on_release')
            field.dispatch('on_text_validate')
            unlock.assert_not_called()
        assert field.text == 'kept while waiting' and field.focus
        Clock.schedule_once(lambda _elapsed: decreasing(), 1.1)

    def decreasing() -> None:
        assert panel.feedback.text in {
            'Try again in 2 seconds',
            'Try again in 1 second',
        }
        assert panel.activity.height == 0 and shell._security_panel is panel
        assert app.viewport is not None
        capture_viewport(app.viewport, output.with_stem(output.stem + '-cooldown'))
        Clock.schedule_once(lambda _elapsed: resumed(), 2.1)

    def resumed() -> None:
        controller.poll()
        shell.render()
        assert security.retry_seconds == 0 and panel.feedback.text == ''
        assert field.text == 'kept while waiting' and field.focus
        assert all(
            not item.disabled
            for item in panel.walk()
            if isinstance(item, Action) and item is not panel.activity
        )
        assert state.covered
        security.restriction = original
        shell.render()
        assert not field.text and not field.focus and field.disabled
        print('NATIVE_UNLOCK_GEOMETRY_AND_COUNTDOWN_OK')
        complete()

    settled(initial)


def exercise_unlock_modal(app: MetorApp, complete: Callable[[], None]) -> None:
    """Keep the exact settings pane, route and scroll through method selection and Later."""
    assert app.shell is not None and app.shell._detail is not None
    shell, state = app.shell, app.controller.state
    detail, route = shell._detail, state.route
    scroll = next(item for item in detail.walk() if isinstance(item, ScrollView))
    position = scroll.scroll_y
    unlock = next(
        row
        for row in detail.walk()
        if isinstance(row, SettingRow) and row.focus_key == ('setting', 'Unlock method')
    )
    unlock.dispatch('on_release')

    def opened() -> None:
        sheet = ActionSheet.current
        assert sheet is not None
        assert state.route == route and shell._detail is detail
        assert abs(scroll.scroll_y - position) < 0.001
        later = next(
            item
            for item in sheet.walk()
            if isinstance(item, Action) and item.accessible_name == 'Later'
        )
        assert later is sheet.cancel and later.parent is sheet.actions
        assert sheet.y <= later.to_window(*later.pos)[1]
        assert later.to_window(*later.pos)[1] + later.height <= sheet.top
        later.dispatch('on_release')
        settled(closed)

    def closed() -> None:
        assert ActionSheet.current is None
        assert state.route == route and shell._detail is detail
        assert abs(scroll.scroll_y - position) < 0.001
        print('NATIVE_SETTINGS_UNLOCK_MODAL_RETURN_OK')
        complete()

    settled(opened)
