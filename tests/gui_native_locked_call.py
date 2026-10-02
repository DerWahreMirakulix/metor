"""Reduced locked Call controls at 360×640 and 1.5 font scale with synthetic input."""

# ruff: noqa: E402

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import time
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
from kivy.metrics import Metrics, dp
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.client import FrontendLaunchContext
from metor.core.api import (
    CallInfo,
    CallState,
    CallStateEvent,
    ClientRestrictedEvent,
    ClientUnlockMethod,
    NotificationPrivacy,
)
from metor.ui.gui.constants import Geometry
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.views.calls import CallOverlay
from metor.ui.gui.views.shell import Shell
from metor.ui.gui.widgets import Action, Label, SecretInput
from metor.ui.gui.widgets.keyboard import LocalKeyboard


class LockedCallHarness(App):
    """Uses concrete shell, auth scroll and Call widgets without Core or hardware."""

    def __init__(self, images: Path, **kwargs: object) -> None:
        """Keeps only output paths and content-free synthetic acceptance records."""
        super().__init__(**kwargs)
        self.images = images
        self.methods = iter(
            [(method, False) for method in ClientUnlockMethod]
            + [
                (method, True)
                for method in ClientUnlockMethod
                if method is not ClientUnlockMethod.NONE
            ]
        )
        self.results: list[dict[str, object]] = []
        self.completed = False

    def build(self) -> FloatLayout:
        """Creates the native compact viewport with intentionally enlarged text."""
        Window.size = (360, 640)
        Metrics.fontscale = 1.5
        self.stage = FloatLayout()
        Clock.schedule_once(self.next_method, 0.3)
        return self.stage

    def next_method(self, _elapsed: float) -> None:
        """Rebuilds one exact lock method with an already accepted synthetic Call."""
        scenario = next(self.methods, None)
        if scenario is None:
            self.completed = True
            self.stop()
            return
        method, self.keyboard_visible = scenario
        self.method = method
        self.image_name = method.value + ('-keyboard' if self.keyboard_visible else '')
        self.stage.clear_widgets()
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        self.gui.state.covered = True
        self.gui.state.route = Route('V05')
        self.gui.security.restriction = ClientRestrictedEvent(method)
        self.gui.security.unlock = Mock(return_value=True)
        self.gui.security._policy = replace(
            self.gui.security._policy,
            notifications_locked=NotificationPrivacy.ANONYMIZE,
        )
        self.call = CallInfo(
            'phone',
            'private-peer',
            'Private Alias',
            CallState.ACTIVE,
            started_at=time.time() - 83,
            owned=True,
        )
        self.gui.calls.observe(CallStateEvent(self.call))
        self.shell = Shell(self.gui, lambda: None)
        self.overlay = CallOverlay(self.gui, lambda: None)
        self.viewport = BoxLayout(orientation='vertical')
        self.viewport.add_widget(self.shell)
        if self.keyboard_visible:
            self.keyboard = LocalKeyboard(
                lambda _value: None, lambda: None, pin=method is ClientUnlockMethod.PIN
            )
            self.shell.set_input_inset(dp(Geometry.KEYBOARD))
            self.viewport.add_widget(self.keyboard)
            self.overlay.bottom_inset = dp(Geometry.KEYBOARD)
        self.stage.add_widget(self.viewport)
        self.stage.add_widget(self.overlay)
        Clock.schedule_once(self.paint, 0.1)
        Clock.schedule_once(self.paint, 0.2)
        Clock.schedule_once(self.controls, 0.4)

    def paint(self, _elapsed: float) -> None:
        """Reserves the measured reduced Call area above the real auth ScrollView."""
        self.shell.render()
        self.overlay.render()
        self.shell.inset_locked_call(self.overlay.occupied_height)

    @staticmethod
    def action(root: FloatLayout | Shell, label: str) -> Action:
        """Selects a concrete native control by its displayed synthetic intent."""
        return next(
            widget
            for widget in root.walk()
            if isinstance(widget, Action) and widget.label.text == label
        )

    @staticmethod
    def click(widget: Action, identity: str) -> None:
        """Dispatches a touch at actual window coordinates after checking bounds."""
        x, y = widget.to_window(*widget.center)
        assert 0 < x < Window.width and 0 < y < Window.height
        touch = MouseMotionEvent(
            'mouse',
            identity,
            (x / Window.width, y / Window.height, 'left'),
            is_touch=True,
        )
        touch.scale_for_screen(Window.width, Window.height)
        EventLoop.post_dispatch_input('begin', touch)
        EventLoop.post_dispatch_input('end', touch)

    def controls(self, _elapsed: float) -> None:
        """Checks reduced actions, status, duration and exact mute hit targets."""
        mute, hangup = (
            self.action(self.overlay, 'Mute'),
            self.action(self.overlay, 'Hang up'),
        )
        assert mute.height >= dp(48) and hangup.height >= dp(48)
        assert mute.y == hangup.y and mute.right <= hangup.x
        assert (
            self.overlay._duration is not None
            and self.overlay._duration.text.startswith('01:')
        )
        assert not any(
            isinstance(widget, Label) and 'Private Alias' in widget.text
            for widget in self.overlay.walk()
        )
        title = next(
            widget
            for widget in self.overlay.walk()
            if isinstance(widget, Label)
            and (widget.text == 'Phone call' or widget.text.startswith('Call ·'))
        )
        assert title.parent.height >= title.texture_size[1]
        self.stage.export_to_png(
            str(self.images / f'locked-call-{self.image_name}.png')
        )
        self.click(mute, 'mute-' + self.method.value)
        assert self.gui.calls._operation is not None
        self.gui.calls.install(
            Update(
                0,
                self.gui.calls._operation[0],
                CallStateEvent(replace(self.call, muted=True)),
            )
        )
        self.paint(0)
        self.scroll = next(
            widget for widget in self.shell.walk() if isinstance(widget, ScrollView)
        )
        if self.method is not ClientUnlockMethod.NONE:
            secret = next(
                widget
                for widget in self.shell.walk()
                if isinstance(widget, SecretInput)
            )
            assert secret.parent is not None and not secret.disabled
            secret.text = (
                '1234'
                if self.method is ClientUnlockMethod.PIN
                else 'synthetic-password'
            )
            self.secret = secret
            self.scroll.scroll_to(secret, padding=dp(24), animate=False)
            Clock.schedule_once(self.input_visible, 0.1)
        else:
            self.scroll.scroll_y = 0
            Clock.schedule_once(self.unlock, 0.2)

    def input_visible(self, _elapsed: float) -> None:
        """Verifies the secret field remains reachable above Call and keyboard controls."""
        x, y = self.secret.to_window(*self.secret.center)
        sx, sy = self.scroll.to_window(*self.scroll.pos)
        assert sx <= x <= sx + self.scroll.width and sy <= y <= sy + self.scroll.height
        self.scroll.scroll_y = 0
        Clock.schedule_once(self.unlock, 0.2)

    def unlock(self, _elapsed: float) -> None:
        """Shows and activates unlock through the real bounded auth scroll region."""
        unlock = self.action(self.shell, 'Unlock')
        x, y = unlock.to_window(*unlock.center)
        sx, sy = self.scroll.to_window(*self.scroll.pos)
        assert sx <= x <= sx + self.scroll.width
        assert sy <= y <= sy + self.scroll.height
        assert y - unlock.height / 2 >= self.overlay.occupied_height - dp(24)
        self.stage.export_to_png(
            str(self.images / f'locked-call-{self.image_name}-unlock.png')
        )
        self.click(unlock, 'unlock-' + self.method.value)
        self.gui.security.unlock.assert_called_once()
        assert self.gui.state.covered
        self.click(self.action(self.overlay, 'Hang up'), 'hangup-' + self.method.value)
        assert self.gui.calls._operation is not None
        assert self.gui.calls._operation[0].startswith('call:end:')
        self.results.append(
            {
                'unlock_method': self.method.value,
                'touch_keyboard': self.keyboard_visible,
                'status_duration_visible': True,
                'mute_hangup_clickable': True,
                'unlock_scroll_clickable': True,
                'private_identity_hidden': True,
            }
        )
        Clock.schedule_once(self.next_method, 0.1)


def main() -> None:
    """Runs layout-only native evidence and stores no real credentials or audio."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--images', type=Path, required=True)
    args = parser.parse_args()
    args.images.mkdir(parents=True, exist_ok=True)
    harness = LockedCallHarness(args.images)
    harness.run()
    assert harness.completed
    args.result.write_text(
        json.dumps(
            {
                'kind': 'native Kivy widgets with synthetic input and public Call DTOs',
                'viewport': [360, 640],
                'font_scale': 1.5,
                'core': False,
                'physical_hardware': False,
                'checks': harness.results,
            },
            indent=2,
        )
        + '\n'
    )


if __name__ == '__main__':
    main()
