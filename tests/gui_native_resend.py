"""Native resend menu eviction and keyboard checks with synthetic sources and no Core IO."""

# ruff: noqa: E402

import argparse
import json
import os
import struct
from pathlib import Path
from unittest.mock import Mock, patch

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.config import Config

Config.set('graphics', 'width', '360')
Config.set('graphics', 'height', '664')

from kivy.app import App
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.uix.boxlayout import BoxLayout

from metor.client import FrontendLaunchContext
from metor.core.api import (
    Delivery,
    MessageDirectionCode,
    MessageStatusCode,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.transcript import TranscriptItem
from metor.ui.gui.state import Route
from metor.ui.gui.views.actions.messages import message_menu
from metor.ui.gui.views.shell import Shell
from metor.ui.gui.views.peer.timeline import Timeline
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.sheet import ActionSheet
from gui_native_render import capture_viewport


class ResendHarness(App):
    """Exercises real native controls with explicit synthetic admission only."""

    def build(self) -> BoxLayout:
        """Creates an inert source-only GUI with no client, host activation or audio.

        Args:
            None
        Returns:
            BoxLayout: Native window content.
        """
        Window.size = (360, 640)
        Metrics.fontscale = 1.5
        self.gui = GuiController(FrontendLaunchContext('fixture', Mock()))
        self.gui.state.covered = False
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', '', epoch='epoch', profile_instance_id='instance'
        )
        self.gui.state.root_delivery = Delivery.LIVE
        self.gui.state.route = Route('V09', 'peer', Delivery.LIVE)
        self.gui.transcript.admit(
            TranscriptItem(
                'peer',
                Delivery.LIVE,
                MessageDirectionCode.OUT,
                'source',
                codec=PcmVoice.CODEC,
                size_bytes=64000,
                finalized=True,
                status=MessageStatusCode.DELIVERED,
            )
        )
        self.target = self.gui.playback.target(
            'peer', Delivery.LIVE, MessageDirectionCode.OUT, 'source'
        )
        payload = b''.join(
            struct.pack('<h', (index % 16000) * 4 - 32000) for index in range(32000)
        )
        self.gui.playback.cache.append(self.target, 0, payload, complete=True)
        self.gui.playback.audio = Mock()
        self.gui.transcript.admit(
            TranscriptItem(
                'peer',
                Delivery.LIVE,
                MessageDirectionCode.OUT,
                'text-source',
                text='Retained own text',
                finalized=True,
                status=MessageStatusCode.READ,
            )
        )
        self.timeline = Timeline(self.gui, self.gui.state.route, lambda: None)
        self.timeline.update(active=True)
        self.completed = False
        Clock.schedule_once(self.settle, 0)
        root = BoxLayout()
        root.add_widget(self.timeline)
        return root

    def settle(self, _elapsed: float) -> None:
        """Waits a native frame after initial attachment before testing and capturing layout.

        Args:
            _elapsed: Native frame interval.
        Returns:
            None
        """
        Clock.schedule_once(self.open_menu, 0.3)

    def open_menu(self, _elapsed: float) -> None:
        """Opens the exact outgoing source's native contextual menu.

        Args:
            _elapsed: Native frame interval.
        Returns:
            None
        """
        for identity in ('source', 'text-source'):
            row = self.timeline._widgets[(MessageDirectionCode.OUT, identity)]
            assert any(
                isinstance(widget, Action)
                and widget.accessible_name == 'Message actions'
                for widget in row.walk()
            )
        row = self.timeline._widgets[(MessageDirectionCode.OUT, 'source')]
        with patch.object(self.gui.playback, 'play', return_value=True) as play:
            row.seek.focus = True
            Window.dispatch('on_key_down', 275, 79, '', [])
            Window.dispatch('on_key_up', 275, 79)
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            play.assert_called_once_with(self.target, offset=3200)
        assert row.seek.height >= 48
        assert row.seek.right <= row.right and row.seek.x >= row.play.right
        with patch.object(self.gui.playback, 'play', return_value=True) as play:
            for control in (
                row.seek,
                row.play,
                self.timeline._widgets[
                    (MessageDirectionCode.OUT, 'text-source')
                ]._bubble,
            ):
                control.focus = True
                Window.dispatch('on_key_down', 291, 67, '', ['shift'])
                Window.dispatch('on_key_down', 291, 67, '', ['shift'])
                Window.dispatch('on_key_up', 291, 67)
                assert ActionSheet.current is not None
                assert self.action().label.text == 'Resend as Drop'
                ActionSheet.current.dismiss(animation=False)
            touch = MouseMotionEvent(
                'mouse',
                'waveform-context',
                (
                    row.seek.center_x / Window.width,
                    row.seek.center_y / Window.height,
                    'right',
                ),
                is_touch=True,
            )
            touch.scale_for_screen(Window.width, Window.height)
            EventLoop.post_dispatch_input('begin', touch)
            EventLoop.post_dispatch_input('end', touch)
            assert ActionSheet.current is not None
            ActionSheet.current.dismiss(animation=False)
            play.assert_not_called()
        capture_viewport(
            self.root, self.output.with_name(self.output.stem + '-waveform.png')
        )
        more = next(
            widget
            for widget in row.walk()
            if isinstance(widget, Action)
            and widget.accessible_name == 'Message actions'
        )
        more.focus = True
        Window.dispatch('on_key_down', 13, 40, '\r', [])
        Window.dispatch('on_key_up', 13, 40)
        assert ActionSheet.current is not None
        Clock.schedule_once(self.activate, 0.3)

    def action(self) -> Action:
        """Finds the current real resend control after native reconciliation.

        Args:
            None
        Returns:
            Action: Exact labeled resend action.
        """
        return next(
            widget
            for widget in ActionSheet.current.walk()
            if isinstance(widget, Action) and widget.label.text == 'Resend as Drop'
        )

    def activate(self, _elapsed: float) -> None:
        """Checks Enter dispatch once, then revokes the source while the menu is open.

        Args:
            _elapsed: Native layout interval.
        Returns:
            None
        """
        assert ActionSheet.current.cancel.focus
        action = self.action()
        assert not action.disabled
        with patch.object(self.gui.resend, 'start', return_value=True) as start:
            action.focus = True
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_down', 13, 40, '\r', [])
            Window.dispatch('on_key_up', 13, 40)
            start.assert_called_once_with('peer', 'source')
        self.gui.playback.cache.discard(self.target)
        ActionSheet.reconcile()
        assert self.action().disabled
        Clock.schedule_once(self.finish, 0.3)

    def finish(self, _elapsed: float) -> None:
        """Checks eviction, inbound exclusion, and same-count root invalidation before export.

        Args:
            _elapsed: Native layout interval.
        Returns:
            None
        """
        capture_viewport(self.root, self.output)
        ActionSheet.current.dismiss(animation=False)
        message_menu(
            self.gui,
            Route('V09', 'peer', Delivery.LIVE),
            MessageDirectionCode.IN,
            'source',
            lambda: MessageStatusCode.READ,
        )
        assert not any(
            isinstance(widget, Action) and widget.label.text == 'Resend as Drop'
            for widget in ActionSheet.current.walk()
        )
        ActionSheet.current.dismiss(animation=False)
        shell = Shell(self.gui, lambda: None)
        original = shell._root_key()
        self.gui.transcript.discard('peer', Delivery.LIVE)
        self.gui.transcript.admit(
            TranscriptItem(
                'replacement',
                Delivery.LIVE,
                MessageDirectionCode.IN,
                'replacement',
                'retained',
            )
        )
        assert shell._root_key() != original
        assert self.gui.client is None
        self.completed = True
        self.gui.close()
        self.stop()


def main() -> None:
    """Writes native evidence with synthetic input and no media or credential export.

    Args:
        None
    Returns:
        None
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    harness = ResendHarness()
    harness.output = args.output
    harness.run()
    assert harness.completed
    args.output.with_suffix('.json').write_text(
        json.dumps(
            {
                'kind': 'native SDL widgets with synthetic input and source descriptors',
                'core': False,
                'physical_hardware': False,
                'audio': False,
                'logical_size': [360, 640],
                'font_scale': 1.5,
                'keyboard_exact_target_once': 'pass',
                'open_menu_eviction': 'pass',
                'received_live_no_resend': 'pass',
                'same_count_root_invalidation': 'pass',
                'delivered_voice_and_text_timeline_more': 'pass',
                'native_keyboard_seek_exact_pcm_boundary': 'pass',
                'text_play_waveform_context_keyboard': 'pass',
                'waveform_right_click_never_plays': 'pass',
            },
            indent=2,
        )
        + '\n'
    )


if __name__ == '__main__':
    main()
