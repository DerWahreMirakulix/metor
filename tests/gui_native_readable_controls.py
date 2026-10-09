"""Native full-label controls, default modal headings and same-peer Call presentation."""

# ruff: noqa: E402

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.config import Config

# Size SDL's drawable before importing the first native Window.
geometry_parser = argparse.ArgumentParser(add_help=False)
geometry_parser.add_argument('--width', type=int, default=360)
geometry_parser.add_argument('--height', type=int, default=640)
initial_geometry, _remaining_arguments = geometry_parser.parse_known_args()
Config.set('graphics', 'width', str(initial_geometry.width))
Config.set('graphics', 'height', str(initial_geometry.height))

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics, dp
from kivy.uix.boxlayout import BoxLayout

from metor.client import FrontendLaunchContext
from metor.core.api import (
    CallInfo,
    CallState,
    ContactEntry,
    Delivery,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.views.peer.header import PeerHeader
from metor.ui.gui.widgets import Action, ActionRow, Label
from metor.ui.gui.widgets.sheet import ActionSheet

from gui_native_render import capture_viewport

LAYOUT_FRAMES = 8
FIXTURE_DEADLINE_SECONDS = 30.0
GEOMETRY_TOLERANCE = 1.0
PEER = 'readable-fixture-peer'
ALIAS = 'A contact name with several readable words'


class ReadableControlHarness(App):
    """Exercises actual packaged font and layout measurements without Core or audio."""

    def __init__(self, output: Path, width: int, height: int) -> None:
        """Retains the capture destination and chosen compact or desktop viewport."""
        super().__init__()
        self.output, self.viewport = output, (width, height)
        self.completed = False

    def build(self) -> BoxLayout:
        """Attaches a long contact heading, visible current Call and measured controls."""
        Window.size = self.viewport
        Metrics.fontscale = 1.5
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.gui.state.covered = False
        self.gui.state.route = Route('V08', PEER, Delivery.DROP)
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', '', contacts=[ContactEntry(ALIAS, PEER)]
        )
        self.gui.calls.current = CallInfo(
            'call', PEER, ALIAS, CallState.ACTIVE, owned=True
        )
        self.open_call = Mock()
        self.header = PeerHeader(
            self.gui,
            self.gui.state.route,
            back=lambda: None,
            call=self.open_call,
            more=lambda: None,
            start=lambda: None,
            end=lambda _generation, _attempt: None,
        )
        self.header.name.text = ALIAS
        self.header.update()
        self.row = ActionRow(spacing=dp(12))
        self.row.add_widget(Action('Send all pending as Drops', lambda: None))
        self.row.add_widget(Action('Recheck recording', lambda: None))
        root = BoxLayout(orientation='vertical', padding=dp(24), spacing=dp(16))
        root.add_widget(self.header)
        root.add_widget(self.row)
        root.add_widget(
            Label('Native layout fixture · no Core or audio', role='support')
        )
        root.add_widget(BoxLayout())
        self.settled(self.inspect_header)
        Clock.schedule_once(self.deadline, FIXTURE_DEADLINE_SECONDS)
        return root

    def settled(
        self, callback: Callable[[], None], frames: int = LAYOUT_FRAMES
    ) -> None:
        """Waits for nested native text and parent geometry to settle."""
        if frames:
            Clock.schedule_once(lambda _elapsed: self.settled(callback, frames - 1), 0)
        else:
            callback()

    def deadline(self, _elapsed: float) -> None:
        """Fails a stalled native fixture within its own acceptance bound."""
        assert self.completed, 'Readable controls fixture did not finish'

    @staticmethod
    def readable(action: Action) -> None:
        """Requires the whole visible button label within its measured target."""
        assert not action.label.shorten
        assert action.label.text
        assert action.label.height + action.padding[1] + action.padding[3] <= (
            action.height + GEOMETRY_TOLERANCE
        )
        assert action.label.texture_size[1] <= action.label.height + GEOMETRY_TOLERANCE

    def inspect_header(self) -> None:
        """Requires full title and In call controls on the same contact row."""
        self.readable(self.header.call)
        self.readable(self.header.connect)
        assert self.header.call.label.text == 'In call'
        assert self.header.call.accessible_name == 'Open call controls'
        assert self.header.call.label.parent is self.header.call
        if self.header.expanded_title:
            assert self.header.name.parent is self.header
            assert self.header.call.parent is self.header.more.parent
            assert self.header.name.y >= self.header.title_row.top
        else:
            assert (
                self.header.name.parent
                is self.header.call.parent
                is self.header.more.parent
            )
        assert not self.header.name.shorten
        assert self.header.name.height <= self.header.height
        assert self.header.call.height <= self.header.title_row.height
        assert self.header.connect.height <= self.header.controls.height
        if not self.header.expanded_title:
            assert self.header.name.right <= self.header.call.x + GEOMETRY_TOLERANCE
        assert self.header.call.right <= self.header.more.x + GEOMETRY_TOLERANCE
        self.header.call._activate()
        self.open_call.assert_called_once_with()
        for widget in self.row.children:
            assert isinstance(widget, Action)
            self.readable(widget)
            assert widget.height <= self.row.height
        if self.viewport[0] == 360:
            assert self.header.expanded_title
            assert self.header.height < dp(220)
            assert self.header.name.height > dp(48)
            assert any(widget.height > dp(48) for widget in self.row.children)
        assert self.root is not None
        capture_viewport(self.root, self.output.with_stem(self.output.stem + '-header'))
        self.sheet = ActionSheet(
            self.gui,
            lambda body: body.add_widget(
                Label('Choose how to handle the retained messages.')
            ),
            title='Remove ended Live conversation?',
            primary=('Discard pending messages', lambda: None),
        )
        self.sheet.show()
        self.settled(self.inspect_sheet)

    def inspect_sheet(self) -> None:
        """Checks default headings and stacked actions without an opt-in wrapping flag."""
        sheet = self.sheet
        assert not sheet.title_label.shorten
        assert sheet.title_label.height <= sheet.header.height
        assert sheet.title_label.texture_size[1] <= sheet.title_label.height
        assert sheet.title_label.right <= sheet.close_action.x + GEOMETRY_TOLERANCE
        self.readable(sheet.cancel)
        assert sheet.primary_action is not None
        self.readable(sheet.primary_action)
        if self.viewport[0] == 360:
            assert sheet.header.height > dp(48)
            assert sheet.actions.orientation == 'vertical'
        assert sheet.actions.height >= sheet.primary_action.height
        assert sheet.actions.y >= sheet.y
        assert self.root is not None
        capture_viewport(self.root, self.output.with_stem(self.output.stem + '-modal'))
        sheet.set_keyboard_top(dp(264))
        self.settled(self.inspect_keyboard)

    def inspect_keyboard(self) -> None:
        """Keeps full default modal controls above a compact local keyboard reservation."""
        sheet = self.sheet
        assert sheet.y >= dp(264)
        assert sheet.cancel.y >= sheet.y
        assert sheet.primary_action is not None
        assert sheet.primary_action.y >= sheet.y
        assert sheet.close_action.top <= sheet.top + GEOMETRY_TOLERANCE
        assert sheet.header.top <= Window.height
        assert sheet.scroll.height >= dp(48) - GEOMETRY_TOLERANCE
        assert sheet.title_viewport.do_scroll_y == (
            sheet.title_label.height > sheet.title_viewport.height
        )
        self.readable(sheet.cancel)
        self.readable(sheet.primary_action)
        assert self.root is not None
        capture_viewport(
            self.root, self.output.with_stem(self.output.stem + '-keyboard')
        )
        sheet.dismiss(animation=False)
        self.completed = True
        self.stop()

    def on_stop(self) -> None:
        """Releases current native modal ownership without Core detach operations."""
        if ActionSheet.current is not None:
            ActionSheet.current.dismiss(animation=False)


def main() -> None:
    """Runs the explicit native viewport and emits software-only geometry evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--width', type=int, default=360)
    parser.add_argument('--height', type=int, default=640)
    args = parser.parse_args()
    harness = ReadableControlHarness(args.output, args.width, args.height)
    harness.run()
    assert harness.completed
    print('NATIVE_READABLE_CONTROLS_OK')


if __name__ == '__main__':
    main()
