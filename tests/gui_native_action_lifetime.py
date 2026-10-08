"""Native input regression for actions whose containing route leaves the window."""

from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.metrics import dp
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView

from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.symbol import IconAction


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
