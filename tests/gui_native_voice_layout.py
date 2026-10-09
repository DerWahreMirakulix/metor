"""Native Voice waveform geometry across arriving messages and viewport changes."""

# ruff: noqa: E402

import argparse
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_NO_CONFIG'] = '1'
os.environ['KIVY_NO_FILELOG'] = '1'
os.environ['MESA_SHADER_CACHE_DISABLE'] = 'true'

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Line
from kivy.metrics import Metrics
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
from metor.ui.gui.views.peer.timeline import Timeline
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.voice import VoiceCard

from gui_native_render import capture_viewport

LAYOUT_FRAMES = 8
GEOMETRY_TOLERANCE = 1.0
SOURCE_BYTES = 32000
FIXTURE_DEADLINE_SECONDS = 30.0


class VoiceLayoutHarness(App):
    """Exercises the native layout loop with synthetic media and no audio output."""

    def __init__(self, output: Path) -> None:
        """Retains the explicit screenshot destination and completion evidence."""
        super().__init__()
        self.output = output
        self.completed = False

    def build(self) -> BoxLayout:
        """Attaches a real timeline with one loaded waveform and enlarged text."""
        Window.size = (360, 640)
        Metrics.fontscale = 1.5
        self.gui = GuiController(FrontendLaunchContext('fixture', Mock()))
        self.gui.state.covered = False
        self.gui.state.route = Route('V09', 'peer', Delivery.LIVE)
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture', '', epoch='epoch', profile_instance_id='instance'
        )
        self.gui.transcript.admit(
            TranscriptItem(
                'peer',
                Delivery.LIVE,
                MessageDirectionCode.IN,
                'voice',
                codec=PcmVoice.CODEC,
                size_bytes=SOURCE_BYTES,
                finalized=True,
            )
        )
        target = self.gui.playback.target(
            'peer', Delivery.LIVE, MessageDirectionCode.IN, 'voice'
        )
        assert target is not None
        self.gui.playback.cache.append(
            target,
            0,
            b'\x00\x40' * (SOURCE_BYTES // PcmVoice.SAMPLE_BYTES),
            complete=True,
        )
        self.gui.playback.audio = Mock()
        self.timeline = Timeline(self.gui, self.gui.state.route, lambda: None)
        self.timeline.update(active=True)
        root = BoxLayout()
        root.add_widget(self.timeline)
        self.settled(self.inspect_initial)
        Clock.schedule_once(self.deadline, FIXTURE_DEADLINE_SECONDS)
        return root

    def deadline(self, _elapsed: float) -> None:
        """Fails a stalled fixture within its explicit native acceptance bound."""
        assert self.completed, 'Voice waveform layout did not complete in time'

    def settled(
        self, callback: Callable[[], None], frames: int = LAYOUT_FRAMES
    ) -> None:
        """Waits actual native frames so nested layout property changes finish."""
        Clock.schedule_once(
            lambda _elapsed: (
                callback() if frames == 0 else self.settled(callback, frames - 1)
            ),
            0,
        )

    def waveform(self) -> VoiceCard:
        """Checks the drawn waveform against its final native message geometry."""
        row = self.timeline._widgets[(MessageDirectionCode.IN, 'voice')]
        assert isinstance(row, VoiceCard)
        assert not any(
            isinstance(widget, Action) and widget.accessible_name == 'Message actions'
            for widget in row.walk(restrict=True)
        )
        lines = [
            instruction
            for instruction in row.seek._wave.children
            if isinstance(instruction, Line)
        ]
        assert lines
        for line in lines:
            left, lower, right, upper = line.points
            assert abs(left - right) <= GEOMETRY_TOLERANCE
            assert row.seek.x <= left <= row.seek.right
            assert row.seek.y <= lower <= upper <= row.seek.top
            assert (
                abs((lower + upper) / 2 - row.seek.hint.center_y) <= GEOMETRY_TOLERANCE
            )
        return row

    def inspect_initial(self) -> None:
        """Records the original waveform before an arriving message shifts its row."""
        self.original = self.waveform()
        self.original_y = self.original.seek.hint.center_y
        self.gui.transcript.admit(
            TranscriptItem(
                'peer',
                Delivery.LIVE,
                MessageDirectionCode.IN,
                'after',
                text='A text message arrives after this received voice message. ' * 4,
            )
        )
        self.timeline.update(active=True)
        self.settled(self.inspect_arrival)

    def inspect_arrival(self) -> None:
        """Keeps the same Voice widget and moves its drawing with the shifted track."""
        row = self.waveform()
        assert row is self.original
        assert abs(row.seek.hint.center_y - self.original_y) > GEOMETRY_TOLERANCE
        following = self.timeline._widgets[(MessageDirectionCode.IN, 'after')]
        assert following.top <= row.y
        capture_viewport(self.root, self.output)
        Window.size = (1040, 640)
        self.settled(self.inspect_resize)

    def inspect_resize(self) -> None:
        """Verifies resized layout without fetching, playing or replacing the source."""
        assert self.waveform() is self.original
        self.gui.playback.audio.play_frame.assert_not_called()
        self.unfinished = TranscriptItem(
            'peer',
            Delivery.LIVE,
            MessageDirectionCode.OUT,
            'unfinished',
            codec=PcmVoice.CODEC,
            size_bytes=SOURCE_BYTES,
            finalized=False,
            status=MessageStatusCode.PENDING,
        )
        self.gui.transcript.admit(self.unfinished)
        self.timeline.update(active=True)
        self.settled(self.inspect_unfinished)

    def inspect_unfinished(self) -> None:
        """Hides empty message menus until an own LIVE source has a valid action."""
        row = self.timeline._widgets[(MessageDirectionCode.OUT, 'unfinished')]
        assert not any(
            isinstance(widget, Action) and widget.accessible_name == 'Message actions'
            for widget in row.walk(restrict=True)
        )
        self.gui.transcript.admit(replace(self.unfinished, finalized=True))
        self.timeline.update(active=True)
        self.settled(self.inspect_finalized)

    def inspect_finalized(self) -> None:
        """Restores explicit message actions when Core confirms a finalized pending item."""
        row = self.timeline._widgets[(MessageDirectionCode.OUT, 'unfinished')]
        assert any(
            isinstance(widget, Action) and widget.accessible_name == 'Message actions'
            for widget in row.walk(restrict=True)
        )
        self.waveform()
        self.completed = True
        self.gui.close()
        print('NATIVE_GUI_VOICE_LAYOUT_OK')
        self.stop()


def main() -> None:
    """Runs the explicit native rendering fixture and requires completion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    harness = VoiceLayoutHarness(args.output)
    harness.run()
    assert harness.completed


if __name__ == '__main__':
    main()
