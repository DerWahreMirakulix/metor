"""Exercises actual native contextual gestures with synthetic input, without Core or hardware IO."""

# ruff: noqa: E402

import argparse
import json
import os
from pathlib import Path

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.app import App
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.metrics import dp
from kivy.uix.floatlayout import FloatLayout

from metor.ui.gui.widgets.context import ContextAction


class GestureHarness(App):
    """Runs deterministic gesture sequences through the native window event dispatcher."""

    def build(self) -> FloatLayout:
        """Creates one concrete hit target without a profile, audio route or mock widget.

        Args:
            None
        Returns:
            FloatLayout: Native target container.
        """
        self.primary: list[bool] = []
        self.completed = False
        self.contexts: list[bool] = []
        self.panel = FloatLayout()
        self.action = ContextAction(
            'Notification',
            lambda: self.primary.append(True),
            lambda: self.contexts.append(True),
            size_hint=(None, None),
            width=dp(240),
            pos=(dp(40), dp(200)),
        )
        self.panel.add_widget(self.action)
        Clock.schedule_once(self.keyboard, 0.3)
        return self.panel

    def touch(self, button: str, identity: str) -> MouseMotionEvent:
        """Constructs a synthetic pointer at the actual native target center.

        Args:
            button: Native button identity.
            identity: Stable pointer ownership token.
        Returns:
            MouseMotionEvent: Dispatchable normalized native pointer.
        """
        touch = MouseMotionEvent(
            'mouse',
            identity,
            (
                self.action.center_x / Window.width,
                self.action.center_y / Window.height,
                button,
            ),
            is_touch=True,
        )
        touch.scale_for_screen(Window.width, Window.height)
        return touch

    def keyboard(self, _elapsed: float) -> None:
        """Verifies repeated Shift+F10 invokes one context action and no ordinary action.

        Args:
            _elapsed: Native scheduler delay.
        Returns:
            None
        """
        self.action.focus = True
        Window.dispatch('on_key_down', 291, 67, '', ['shift'])
        Window.dispatch('on_key_down', 291, 67, '', ['shift'])
        Window.dispatch('on_key_up', 291, 67)
        assert len(self.contexts) == 1 and not self.primary
        touch = self.touch('right', 'right-click')
        EventLoop.post_dispatch_input('begin', touch)
        EventLoop.post_dispatch_input('end', touch)
        assert len(self.contexts) == 2 and not self.primary
        self.held = self.touch('left', 'long-press')
        EventLoop.post_dispatch_input('begin', self.held)
        Clock.schedule_once(self.held_finished, 0.65)

    def held_finished(self, _elapsed: float) -> None:
        """Checks actual clock-based hold dispatch and release suppression.

        Args:
            _elapsed: Native scheduler delay.
        Returns:
            None
        """
        assert len(self.contexts) == 3 and not self.primary
        EventLoop.post_dispatch_input('end', self.held)
        assert not self.primary
        self.moved = self.touch('left', 'moved-hold')
        EventLoop.post_dispatch_input('begin', self.moved)
        self.moved.move(
            (
                (self.action.center_x + dp(9)) / Window.width,
                self.action.center_y / Window.height,
                'left',
            )
        )
        self.moved.scale_for_screen(Window.width, Window.height)
        EventLoop.post_dispatch_input('update', self.moved)
        Clock.schedule_once(self.moved_finished, 0.65)

    def moved_finished(self, _elapsed: float) -> None:
        """Confirms excess movement cancels the hold without inventing a context action.

        Args:
            _elapsed: Native scheduler delay.
        Returns:
            None
        """
        assert len(self.contexts) == 3
        EventLoop.post_dispatch_input('end', self.moved)
        assert self.primary == [True]
        self.removed = self.touch('left', 'removed-hold')
        EventLoop.post_dispatch_input('begin', self.removed)
        self.panel.remove_widget(self.action)
        Clock.schedule_once(self.finished, 0.65)

    def finished(self, _elapsed: float) -> None:
        """Verifies detached targets forget a press before the next real click.

        Args:
            _elapsed: Native scheduler delay.
        Returns:
            None
        """
        assert len(self.contexts) == 3 and self.primary == [True]
        EventLoop.post_dispatch_input('end', self.removed)
        self.panel.add_widget(self.action)
        pressed = self.touch('left', 'after-reattach')
        EventLoop.post_dispatch_input('begin', pressed)
        EventLoop.post_dispatch_input('end', pressed)
        assert self.primary == [True, True], (
            len(self.primary),
            self.action._pointer_identity,
            self.action.state,
        )
        self.completed = True
        self.stop()


def main() -> None:
    """Runs the native fixture and writes a truthful synthetic-input evidence record.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    harness = GestureHarness()
    harness.run()
    assert harness.completed
    args.result.write_text(
        json.dumps(
            {
                'kind': 'native window and widgets with synthetic input',
                'core': False,
                'physical_hardware': False,
                'shift_f10_repeat': 'pass',
                'right_click': 'pass',
                'hold_500ms': 'pass',
                'travel_over_8_units': 'pass',
                'detached_target_cancellation': 'pass',
                'reattached_first_click': 'pass',
            },
            indent=2,
        )
        + '\n'
    )


if __name__ == '__main__':
    main()
