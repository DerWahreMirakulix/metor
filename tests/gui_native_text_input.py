"""Exercise composer Enter and local Shift+Enter on actual Kivy widgets.

This explicit native fixture uses synthetic key/pointer input and inert IPC;
it does not establish physical keyboard, Core delivery, or audio acceptance.
"""

# ruff: noqa: E402

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.app import App
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.uix.boxlayout import BoxLayout

from metor.client import FrontendLaunchContext, FrontendProfileState
from metor.core.api import Delivery, DropQueuedEvent
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.views.input import InputDock
from metor.ui.gui.views.peer.composer import Composer
from metor.ui.gui.widgets import SecretInput, TextField
from metor.ui.gui.widgets.keyboard import KeyboardKey

if TYPE_CHECKING:
    from metor.ui.gui.app import MetorApp


class TextInputHarness(App):
    """Drive physical-key callbacks and touch keys while retaining the composer owner."""

    def __init__(self, result: Path, **kwargs: object) -> None:
        """Bind the output path without creating a profile or external connection."""
        super().__init__(**kwargs)
        self.result = result
        self.completed = False

    def build(self) -> BoxLayout:
        """Create a real focused composer and the application's local input dock."""
        Window.size = (360, 640)
        self.controller = GuiController(
            FrontendLaunchContext(
                'text-fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'text-fixture', True, False, False
                    )
                ),
            ),
            simulator=True,
        )
        self.controller.client = Mock()
        self.controller.command = Mock(return_value=True)
        self.controller.state.covered = False
        self.controller.state.route = Route('V08', 'peer', Delivery.DROP)
        self.configuration = SimpleNamespace(touch=True)
        self.shell = None
        self.panel = BoxLayout(orientation='vertical')
        self.composer = Composer(
            self.controller, self.controller.state.route, self.refresh
        )
        self.panel.add_widget(self.composer)
        self.dock = InputDock(cast('MetorApp', self), self.panel)
        TextField.keyboard_owner = self.dock
        self.refresh()
        Clock.schedule_once(self.exercise, 0.3)
        return self.panel

    def refresh(self) -> None:
        """Apply current drafts to the same concrete composer instance."""
        self.composer.update()

    def accept(self) -> None:
        """Confirm the one captured send without implying remote delivery."""
        action = next(iter(self.controller.text.operations))
        self.controller.text.install(Update(0, action, DropQueuedEvent('Peer', 'peer')))
        self.refresh()

    def touch_key(self, label: str) -> None:
        """Activate one actual keyboard key through native synthetic pointer dispatch."""
        keyboard = self.dock.keyboard
        assert keyboard is not None
        key = next(
            widget
            for widget in keyboard.walk()
            if isinstance(widget, KeyboardKey) and widget.label.text == label
        )
        x, y = key.to_window(*key.center)
        touch = MouseMotionEvent(
            'mouse', label, (x / Window.width, y / Window.height, 'left'), is_touch=True
        )
        touch.scale_for_screen(Window.width, Window.height)
        EventLoop.post_dispatch_input('begin', touch)
        EventLoop.post_dispatch_input('end', touch)

    def exercise(self, _elapsed: float) -> None:
        """Check Enter, held repeats, Shift+Enter and confirmed-only draft clearing."""
        field = self.composer.entry
        field.text = 'physical message'
        field.focus = True
        Window.dispatch('on_key_down', 13, 40, '\r', [])
        Window.dispatch('on_key_down', 13, 40, '\r', [])
        Window.dispatch('on_key_up', 13, 40)
        assert self.controller.command.call_count == 1
        assert field.text == 'physical message' and field.focus
        self.accept()
        assert field.text == '' and field.focus
        field.text = 'line one'
        Window.dispatch('on_key_down', 13, 40, '\r', ['shift'])
        Window.dispatch('on_key_up', 13, 40)
        assert '\n' in field.text
        assert self.controller.command.call_count == 1
        Window.dispatch('on_key_down', 13, 40, '\r', [])
        Window.dispatch('on_key_up', 13, 40)
        assert self.controller.command.call_count == 2
        self.accept()
        field.text = 'local message'
        Clock.schedule_once(self.local_keys, 0.1)

    def local_keys(self, _elapsed: float) -> None:
        """Check the real touch dock's Enter policy and single-use Shift modifier."""
        self.touch_key('⇧')
        Clock.schedule_once(self.local_newline, 0.1)

    def local_newline(self, _elapsed: float) -> None:
        """Insert a local Shift+Enter newline and preserve the pending draft."""
        field = self.composer.entry
        self.touch_key('↵')
        assert '\n' in field.text
        assert self.controller.command.call_count == 2
        assert self.dock.keyboard is not None and not self.dock.keyboard.shift
        assert field.focus
        Clock.schedule_once(self.local_send, 0.1)

    def local_send(self, _elapsed: float) -> None:
        """Send with touch Enter and retain focus through Core-local confirmation."""
        field = self.composer.entry
        self.touch_key('↵')
        assert self.controller.command.call_count == 3
        assert field.text and field.focus
        self.accept()
        assert field.text == '' and field.focus
        secret = SecretInput()
        validate = Mock()
        secret.bind(on_text_validate=validate)
        secret.enter()
        validate.assert_called_once()
        ordinary = TextField(multiline=True, text='notes')
        ordinary.enter()
        assert '\n' in ordinary.text
        self.result.write_text(
            json.dumps(
                {
                    'physical_enter_sends_once_until_release': 'pass',
                    'physical_shift_enter_newline': 'pass',
                    'local_shift_enter_newline_then_enter_sends': 'pass',
                    'draft_clears_only_after_confirmed_acceptance': 'pass',
                    'composer_focus_survives_send_and_acceptance': 'pass',
                    'credential_and_generic_multiline_policy_preserved': 'pass',
                    'input': 'synthetic native callbacks and pointer input',
                    'window_provider': type(Window).__name__,
                    'video_driver': os.environ.get(
                        'SDL_VIDEODRIVER', 'platform default'
                    ),
                    'window_size': list(Window.size),
                    'core': False,
                    'physical_hardware': False,
                },
                indent=2,
            )
            + '\n'
        )
        self.completed = True
        self.stop()

    def on_stop(self) -> None:
        """Release the field-to-dock owner and inert GUI state after the fixture."""
        TextField.keyboard_owner = None
        self.dock.hide()
        self.controller.close()


def main() -> None:
    """Run one explicit native fixture and require all scheduled checks to finish."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    app = TextInputHarness(args.result)
    app.run()
    if not app.completed:
        raise RuntimeError('Native text-input fixture did not complete')


if __name__ == '__main__':
    main()
