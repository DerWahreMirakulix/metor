"""Native input regression for actions whose containing route leaves the window."""

from collections.abc import Callable

from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.metrics import dp
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, TextField
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.symbol import IconAction


def verify_modal_input(
    panel: FloatLayout, controller: GuiController, complete: Callable[[], None]
) -> None:
    """Checks native modal hover, idle keyboard entry and safe invoker restoration."""
    calls: list[str] = []
    backdrop = ScrollView(do_scroll_x=False)
    backdrop.add_widget(FloatLayout(size_hint_y=None, height=dp(2000)))
    panel.add_widget(backdrop, index=len(panel.children))
    background = IconAction(
        'ellipsis',
        'Background action',
        lambda: calls.append('background'),
        pos=(dp(10), dp(10)),
    )
    panel.add_widget(background)
    background.focus = True
    Window.mouse_pos = background.to_window(*background.center)
    assert background._hovered
    field = TextField(multiline=False)
    inside_scroll = ScrollView(do_scroll_x=False, size_hint_y=None, height=dp(120))
    inside_scroll.add_widget(FloatLayout(size_hint_y=None, height=dp(1000)))

    def build(body: BoxLayout) -> None:
        """Adds a field and a native scrolling surface to exercise wheel ownership."""
        body.add_widget(field)
        body.add_widget(inside_scroll)

    sheet = ActionSheet(
        controller,
        build,
        title='Modal keyboard ownership',
        primary=('Commit', lambda: calls.append('commit')),
        rebuild_on_snapshot=False,
    )
    sheet.show()

    def key(code: int, shift: bool = False) -> None:
        """Delivers a complete native key event through the window's normal bindings."""
        Window.dispatch('on_key_down', code, 0, '', ['shift'] if shift else [])
        Window.dispatch('on_key_up', code, 0)

    def click(point: tuple[float, float], identity: str, button: str = 'left') -> None:
        """Delivers a pointer press and release through the real event-loop dispatch."""
        touch = MouseMotionEvent(
            'mouse',
            identity,
            (point[0] / (Window.width - 1), point[1] / (Window.height - 1), button),
            is_touch=True,
        )
        touch.scale_for_screen(Window.width, Window.height)
        EventLoop.post_dispatch_input('begin', touch)
        EventLoop.post_dispatch_input('end', touch)

    def inspect(_elapsed: float) -> None:
        """Exercises focus transitions once the actual modal geometry has settled."""
        choices = [item for item in sheet.walk() if isinstance(item, FocusBehavior)]
        assert not any(item.focus for item in choices) and not background.focus
        assert not background._hovered and background.tooltip._pending is None
        key(13)
        assert not calls and ActionSheet.current is sheet
        key(9)
        assert choices[0].focus
        for item in choices[1:] + choices[:1]:
            key(9)
            assert item.focus
        key(9, shift=True)
        assert choices[-1].focus
        click((sheet.x + dp(2), sheet.center_y), 'empty-modal-space')
        assert not any(item.focus for item in choices)
        key(9, shift=True)
        assert choices[-1].focus
        click((sheet.x + dp(2), sheet.center_y), 'empty-modal-space-again')
        key(9)
        assert choices[0].focus
        field.focus = True
        Window.mouse_pos = sheet.close_action.to_window(*sheet.close_action.center)
        assert sheet.close_action._hovered and not background._hovered
        Window.mouse_pos = background.to_window(*background.center)
        assert not background._hovered
        field.text = 'Retain this modal input'
        backdrop.scroll_y = inside_scroll.scroll_y = 0.5
        for button in ('scrollup', 'scrolldown', 'scrollleft', 'scrollright'):
            click((dp(4), dp(4)), 'outside-modal-' + button, button)
            assert ActionSheet.current is sheet
            assert field.text == 'Retain this modal input' and field.focus
            assert backdrop.scroll_y == 0.5
        click(
            inside_scroll.to_window(*inside_scroll.center), 'inside-wheel', 'scrollup'
        )
        Clock.schedule_once(finish, 0.2)

    def finish(_elapsed: float) -> None:
        """Checks wheel scrolling remains local before deliberately dismissing by click."""
        assert ActionSheet.current is sheet and backdrop.scroll_y == 0.5
        assert inside_scroll.scroll_y != 0.5
        assert field.text == 'Retain this modal input' and field.focus
        click(Window.mouse_pos, 'outside-modal')
        assert ActionSheet.current is None and background.focus
        assert not calls and background._hovered
        click(Window.mouse_pos, 'after-modal')
        assert calls == ['background']
        background.cancel_input()
        background.tooltip.cancel()
        pointer_sheet = ActionSheet(controller, lambda _body: None)
        pointer_sheet.show()
        pointer_sheet.dismiss()
        assert not background.focus
        panel.remove_widget(background)
        panel.remove_widget(backdrop)
        complete()

    Clock.schedule_once(inspect, 0.2)


def verify_detached_action_input(panel: FloatLayout) -> None:
    """Requires interrupted keyboard and pointer releases to leave old routes inert.

    Args:
        panel: Attached native fixture container owning the temporary route.
    Returns:
        None.
    """
    calls: list[bool] = []
    route = FloatLayout()
    action = Action(
        'Temporary route action',
        lambda: calls.append(True),
        size_hint=(None, None),
        width=dp(240),
        pos=(dp(40), dp(280)),
    )
    route.add_widget(action)
    panel.add_widget(route)
    action.focus = True
    Window.dispatch('on_key_down', 13, 40, '', [])
    assert action.state == 'down'
    panel.remove_widget(route)
    assert action.parent is route and action.get_root_window() is None
    Window.dispatch('on_key_up', 13, 40)
    assert not calls and not action.focus and action.state == 'normal'
    assert not action._keyboard_armed

    def touch(identity: str) -> MouseMotionEvent:
        """Builds native pointer events at this exact attached action's center."""
        pointer = MouseMotionEvent(
            'mouse',
            identity,
            (
                action.center_x / Window.width,
                action.center_y / Window.height,
                'left',
            ),
            is_touch=True,
        )
        pointer.scale_for_screen(Window.width, Window.height)
        return pointer

    panel.add_widget(route)
    interrupted = touch('detached-ancestor-pointer')
    EventLoop.post_dispatch_input('begin', interrupted)
    assert action in interrupted.ud and action.state == 'down'
    panel.remove_widget(route)
    EventLoop.post_dispatch_input('end', interrupted)
    assert not calls and action.state == 'normal'

    panel.add_widget(route)
    fresh = touch('reattached-ancestor-pointer')
    EventLoop.post_dispatch_input('begin', fresh)
    EventLoop.post_dispatch_input('end', fresh)
    assert calls == [True]
    action.focus = True
    Window.dispatch('on_key_down', 13, 40, '', [])
    Window.dispatch('on_key_up', 13, 40)
    assert calls == [True, True]
    action.cancel_input()
    panel.remove_widget(route)


def verify_clipped_action_hover(panel: FloatLayout) -> None:
    """Keeps offscreen scrolling controls from showing hover or tooltip pixels.

    Args:
        panel: Attached native fixture container for the temporary viewport.
    Returns:
        None.
    """
    pointer = Window.mouse_pos
    scroll = ScrollView(
        size_hint=(None, None), size=(dp(320), dp(200)), pos=(dp(20), dp(20))
    )
    body = FloatLayout(size_hint_y=None, height=dp(600))
    icon = IconAction('ellipsis', 'Clipped action', lambda: None, pos=(dp(40), dp(300)))
    body.add_widget(icon)
    scroll.add_widget(body)
    panel.add_widget(scroll)
    scroll.scroll_y = 0
    scroll.update_from_scroll()
    Window.mouse_pos = icon.to_window(*icon.center)
    icon._pointer(Window, Window.mouse_pos)
    assert not icon._hovered and not icon.tooltip.visible
    assert icon.tooltip._pending is None

    icon.pos = (dp(40), dp(40))
    Window.mouse_pos = icon.to_window(*icon.center)
    icon._pointer(Window, Window.mouse_pos)
    assert icon._hovered
    icon.tooltip.cancel()
    icon.tooltip._show(0)
    assert icon.tooltip.visible
    icon.tooltip.cancel()

    scroll.scroll_y = 1
    scroll.update_from_scroll()
    icon.tooltip._show(0)
    assert not icon.tooltip.visible and icon.tooltip.label is None
    panel.remove_widget(scroll)
    Window.mouse_pos = pointer
