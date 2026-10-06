"""Native conversation UX acceptance with synthetic DTOs, input and inert audio routes."""

# ruff: noqa: E402

import argparse
from contextlib import ExitStack
from dataclasses import replace
import json
import os
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

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
from kivy.uix.widget import Widget

from metor.client import FrontendHost, FrontendLaunchContext
from metor.client.platform import AudioEndpoint
from metor.core.api import (
    ContactEntry,
    Delivery,
    DropConversationSummaryEntry,
    DropQueuedEvent,
    LiveContextEntry,
    MessageDirectionCode,
    MessageEntry,
    MessagesDataEvent,
    MessageStatusCode,
    RuntimeSnapshotEvent,
    SendMessageCommand,
    TextContent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.views.feedback import FeedbackOverlay
from metor.ui.gui.views.peer import PeerView
from metor.ui.gui.views.shell import Shell
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.symbol import IconAction

PEER = 'conversation-fixture-peer'
ALIAS = 'MiXeD Case Contact'
RESULT_TEXT = 'Contact saved instantly'
FRAME_SETTLE_SECONDS = 0.3
GEOMETRY_TOLERANCE = 1.0
FIXTURE_DEADLINE_SECONDS = 60.0


def rectangle(widget: Widget) -> tuple[float, float, float, float]:
    """Returns drawable window geometry, including nested scroll transforms."""
    left, bottom = widget.to_window(widget.x, widget.y)
    return float(left), float(bottom), float(widget.width), float(widget.height)


class ConversationHarness(App):
    """Exercises actual shell widgets without a Core process or physical audio."""

    def __init__(self, output: Path, width: int, height: int) -> None:
        """Keeps evidence paths and explicit simulated SDK admission boundaries."""
        super().__init__()
        self.output, self.viewport = output, (width, height)
        self.completed = False
        self.patches = ExitStack()
        self.records: dict[str, object] = {}
        self.images: dict[str, str] = {}
        self.first_geometry: dict[str, tuple[float, float, float, float]] | None = None
        self._flip_pending = True
        self._press = 0

    def build(self) -> FloatLayout:
        """Creates concrete compact or desktop composition with enlarged native text."""
        Window.size = self.viewport
        Metrics.fontscale = 1.5
        self.controller = GuiController(
            FrontendLaunchContext('fixture', cast(FrontendHost, object())),
            simulator=True,
        )
        self.controller.state.covered = False
        self.controller.state.capabilities = frozenset({'qualified_live_control'})
        self.controller.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            '',
            epoch='fixture-epoch',
            profile_instance_id='fixture-instance',
            contacts=[ContactEntry(ALIAS, PEER)],
            conversations=[DropConversationSummaryEntry(ALIAS, PEER)],
        )
        messages = MessagesDataEvent(
            [
                MessageEntry(
                    MessageDirectionCode.IN,
                    MessageStatusCode.READ,
                    Delivery.DROP,
                    TextContent('A short Drop starts at the correct position.'),
                    '10:32',
                    'initial-drop',
                )
            ],
            ALIAS,
            PEER,
        )
        self.controller.client = Mock()
        self.admission = self.patches.enter_context(
            patch.object(self.controller, 'command', Mock(return_value=True))
        )
        self.patches.enter_context(
            patch.object(self.controller, 'submit', Mock(return_value=True))
        )
        self.start_live = self.patches.enter_context(
            patch.object(self.controller.live, 'start', Mock())
        )
        self.end_live = self.patches.enter_context(
            patch.object(self.controller.live, 'end', Mock())
        )
        self.capture_admission = self.patches.enter_context(
            patch.object(self.controller.voice, 'down', Mock(return_value=False))
        )
        self.controller.state.route = Route('V06')
        self.controller.navigate(Route('V08', PEER), from_root=True)
        self.controller.messages = messages
        self.stage = FloatLayout()
        self.render_trigger = Clock.create_trigger(self.render, -1)
        self.shell = Shell(self.controller, self.refresh)
        self.feedback = FeedbackOverlay(self.controller, self.refresh)
        self.controller.state.privacy_fence = self.feedback.revoke
        self.stage.add_widget(self.shell)
        self.stage.add_widget(self.feedback)
        self.shell.bind(size=lambda *_args: self.refresh())
        Window.bind(on_key_down=self.key_down, on_key_up=self.key_up)
        self.refresh()
        Clock.schedule_once(self.deadline, FIXTURE_DEADLINE_SECONDS)
        return self.stage

    def deadline(self, _elapsed: float) -> None:
        """Fails a stalled native interaction instead of leaving an unbounded GUI process."""
        assert self.completed, (
            'Conversation acceptance did not finish before its deadline'
        )

    def refresh(self) -> None:
        """Coalesces user interaction into a normal before-draw native repaint."""
        self.render_trigger()

    def key_down(self, _window: object, key: int, *_args: object) -> bool:
        """Observes native key ownership as the real app does before focused dispatch."""
        self.controller.inputs.observe_key_down(str(key))
        return False

    def key_up(self, _window: object, key: int, *_args: object) -> bool:
        """Clears global held-key observation without taking a focused widget's event."""
        self.controller.inputs.observe_key_up(str(key))
        return False

    def render(self, _elapsed: float) -> None:
        """Projects public fixture state without forcing nested layout settlement."""
        ActionSheet.reconcile()
        self.shell.render()
        self.feedback.render()
        if self._flip_pending and self.shell._peer_panel is not None:
            self._flip_pending = False
            Window.bind(on_flip=self.first_frame)

    def peer(self) -> PeerView:
        """Finds the displayed native conversation rather than detached old controls."""
        return next(
            widget for widget in self.shell.walk() if isinstance(widget, PeerView)
        )

    def geometry(self) -> dict[str, tuple[float, float, float, float]]:
        """Captures actual short-message, timeline and composer geometry."""
        peer = self.peer()
        message = next(iter(peer.timeline._widgets.values()))
        return {
            'message': rectangle(message),
            'timeline': rectangle(peer.timeline.scroll),
            'composer': rectangle(peer.composer),
        }

    def capture(self, suffix: str) -> None:
        """Captures native content and supplements Window-owned modals with an FBO export."""
        path = self.output.with_name(self.output.name + suffix + '.png')
        if ActionSheet.current is None:
            self.stage.export_to_png(str(path))
        else:
            saved = Window.screenshot(name=str(path))
            assert saved is not None
            Path(saved).replace(path)
            modal_path = path.with_name(path.stem + '-modal.png')
            ActionSheet.current.export_to_png(str(modal_path))
            self.images[suffix + '-modal'] = str(modal_path)
        self.images[suffix] = str(path)

    def first_frame(self, *_args: object) -> None:
        """Samples the first drawn message frame before asynchronous texture settling."""
        Window.unbind(on_flip=self.first_frame)
        self.first_geometry = self.geometry()
        self.capture('-first')
        Clock.schedule_once(self.settled, FRAME_SETTLE_SECONDS)

    def settled(self, _elapsed: float) -> None:
        """Requires first-frame positions to match the final native font/layout geometry."""
        final = self.geometry()
        assert self.first_geometry is not None
        for name, initial in self.first_geometry.items():
            assert all(
                abs(before - after) <= GEOMETRY_TOLERANCE
                for before, after in zip(initial, final[name], strict=True)
            ), (name, initial, final[name])
        message, timeline = final['message'], final['timeline']
        assert message[3] < timeline[3], 'Fixture must exercise a short timeline'
        assert abs(message[1] + message[3] - timeline[1] - timeline[3]) <= 1
        self.records['first_frame_geometry'] = self.first_geometry
        self.records['settled_geometry'] = final
        self.base_geometry = final
        self.controller.state.status = RESULT_TEXT
        self.refresh()
        Clock.schedule_once(self.feedback_visible, FRAME_SETTLE_SECONDS)

    def pointer(self, action: Action) -> MouseMotionEvent:
        """Creates a normalized physical-style pointer over a reachable native target."""
        left, bottom, width, height = rectangle(action)
        assert not action.disabled and action.parent is not None
        assert width >= dp(48) and height >= dp(48)
        assert left >= -1 and bottom >= -1
        assert left + width <= Window.width + 1 and bottom + height <= Window.height + 1
        self._press += 1
        touch = MouseMotionEvent(
            'mouse',
            f'conversation-{self._press}',
            (
                (left + width / 2) / Window.width,
                (bottom + height / 2) / Window.height,
                'left',
            ),
            is_touch=True,
        )
        touch.scale_for_screen(Window.width, Window.height)
        return touch

    def click(self, action: Action) -> None:
        """Dispatches a physical-style pointer through the actual native hit tree."""
        touch = self.pointer(action)
        EventLoop.post_dispatch_input('begin', touch)
        EventLoop.post_dispatch_input('end', touch)

    def feedback_visible(self, _elapsed: float) -> None:
        """Checks one result overlay without a persistent duplicate or content movement."""
        shown = [
            widget
            for widget in self.stage.walk()
            if isinstance(widget, Label) and widget.text == RESULT_TEXT
        ]
        assert len(shown) == 1
        assert self.geometry() == self.base_geometry
        assert not any(
            'Calls available' in str(getattr(widget, 'text', ''))
            for widget in self.stage.walk()
        )
        dismiss = next(
            widget
            for widget in self.feedback.walk()
            if isinstance(widget, IconAction)
            and widget.accessible_name == 'Dismiss message'
        )
        self.click(dismiss)
        self.refresh()
        Clock.schedule_once(self.feedback_dismissed, FRAME_SETTLE_SECONDS)

    def feedback_dismissed(self, _elapsed: float) -> None:
        """Verifies dismissal stays dismissed despite unchanged historic action text."""
        assert (
            not self.feedback.children and self.controller.state.status == RESULT_TEXT
        )
        self.controller.state.status = (
            'This feedback expires without another Core event'
        )
        self.feedback.render()
        self.feedback.dismiss.focus = True
        assert self.feedback.dismiss.focus and self.feedback.children
        self.refresh()
        Clock.schedule_once(self.feedback_expired, GuiLimits.FEEDBACK_SECONDS + 0.2)

    def feedback_expired(self, _elapsed: float) -> None:
        """Checks clock-driven expiry and immediate revocation when privacy is covered."""
        assert not self.feedback.children
        assert not self.feedback.dismiss.focus
        assert not Window.dispatch('on_key_down', 13, 40, '\r', [])
        assert not Window.dispatch('on_key_up', 13, 40)
        self.records['expired_feedback_does_not_consume_keyboard'] = 'pass'
        assert self.geometry() == self.base_geometry
        self.controller.state.status = 'Private action result'
        self.feedback.render()
        assert self.feedback.children
        self.feedback.dismiss.focus = True
        self.controller.state.covered = True
        assert not self.feedback.children and not self.feedback.message.text
        assert not self.feedback.dismiss.focus
        self.controller.state.covered = False
        self.records['feedback_single_expiring_dismissible_and_covered'] = 'pass'
        self.records['feedback_focus_revoked_on_expiry_and_synchronous_cover'] = 'pass'
        ptt = self.peer().composer.ptt
        assert ptt.label.text == 'Hold to talk' and not ptt.disabled
        touch = self.pointer(ptt)
        EventLoop.post_dispatch_input('begin', touch)
        assert ptt._touch_identity is not None, (rectangle(ptt), ptt.state, touch.pos)
        assert ActionSheet.current is None
        assert not self.capture_admission.called
        EventLoop.post_dispatch_input('end', touch)
        Clock.schedule_once(self.recording_help, FRAME_SETTLE_SECONDS)

    def recording_help(self, _elapsed: float) -> None:
        """Requires missing-route PTT help only after release, with no capture admission."""
        sheet = ActionSheet.current
        ptt = self.peer().composer.ptt
        assert sheet is not None and sheet.heading == 'Recording unavailable', (
            ptt._touch_identity,
            ptt._missing_audio,
            ptt.state,
            ptt.parent,
        )
        assert not self.capture_admission.called
        self.click(sheet.cancel)
        self.peer().composer.ptt.focus = True
        Clock.schedule_once(self.recording_keyboard, FRAME_SETTLE_SECONDS)

    def recording_keyboard(self, _elapsed: float) -> None:
        """Checks a held Space cannot open or activate the future recovery modal."""
        Window.dispatch('on_key_down', 32, 44, ' ', [])
        Window.dispatch('on_key_down', 32, 44, ' ', [])
        assert ActionSheet.current is None and not self.capture_admission.called
        Window.dispatch('on_key_up', 32, 44)
        Clock.schedule_once(self.recording_keyboard_released, FRAME_SETTLE_SECONDS)

    def recording_keyboard_released(self, _elapsed: float) -> None:
        """Returns from explicit keyboard recovery without retrying a microphone press."""
        sheet = ActionSheet.current
        assert sheet is not None and sheet.heading == 'Recording unavailable'
        assert not self.capture_admission.called
        self.click(sheet.cancel)
        self.records['unconfigured_ptt_help_after_pointer_and_space_release'] = 'pass'
        entry = self.peer().composer.entry
        entry.text = 'Enter sends one Drop'
        entry.focus = True
        self.refresh()
        Clock.schedule_once(self.enter_send, FRAME_SETTLE_SECONDS)

    def accept_text(self) -> None:
        """Supplies explicit synthetic durable acceptance through the real Text controller."""
        operation = next(iter(self.controller.text.operations))
        command = self.admission.call_args.args[1]
        assert isinstance(command, SendMessageCommand)
        assert command.delivery is Delivery.DROP and command.target == PEER
        assert self.controller.text.install(
            Update(
                self.controller.state.generation,
                operation,
                DropQueuedEvent(ALIAS, PEER),
            )
        )
        self.refresh()

    def enter_send(self, _elapsed: float) -> None:
        """Checks Enter repeat suppression and clearing only after typed acceptance."""
        entry = self.peer().composer.entry
        assert entry.focus
        Window.dispatch('on_key_down', 13, 40, '\r', [])
        Window.dispatch('on_key_down', 13, 40, '\r', [])
        Window.dispatch('on_key_up', 13, 40)
        assert self.admission.call_count == 1
        assert entry.text == 'Enter sends one Drop'
        self.accept_text()
        Clock.schedule_once(self.shift_enter, FRAME_SETTLE_SECONDS)

    def shift_enter(self, _elapsed: float) -> None:
        """Checks Shift+Enter inserts a newline without admitting a send."""
        entry = self.peer().composer.entry
        assert not entry.text and entry.focus
        assert any(
            isinstance(widget, Label) and widget.text == 'Enter sends one Drop'
            for widget in self.peer().timeline.walk()
        ), 'Accepted Drop did not appear without leaving the conversation'
        self.records['accepted_drop_visible_without_reentering'] = 'pass'
        entry.text = 'First line'
        entry.cursor = (len(entry.text), 0)
        Window.dispatch('on_key_down', 13, 40, '\r', ['shift'])
        Window.dispatch('on_key_up', 13, 40)
        assert entry.text == 'First line\n' and self.admission.call_count == 1
        entry.insert_text('Second line')
        self.refresh()
        Clock.schedule_once(self.pointer_send, FRAME_SETTLE_SECONDS)

    def pointer_send(self, _elapsed: float) -> None:
        """Sends a multiline draft with a genuine hit and preserves typing focus."""
        self.click(self.peer().composer.send)
        assert self.admission.call_count == 2 and self.peer().composer.entry.focus, (
            self.admission.call_count,
            self.peer().composer.entry.focus,
            rectangle(self.peer().composer.send),
            self.controller.state.status,
        )
        self.accept_text()
        self.records['enter_shift_enter_and_pointer_send'] = 'pass'
        live = next(
            widget
            for widget in self.peer().walk()
            if isinstance(widget, Action) and widget.label.text == 'LIVE'
        )
        self.click(live)
        self.refresh()
        Clock.schedule_once(self.live_start, FRAME_SETTLE_SECONDS)

    def live_start(self, _elapsed: float) -> None:
        """Requires one conversation Back entry and Start before Call and More."""
        peer = self.peer()
        assert peer.route.delivery is Delivery.LIVE
        assert self.controller.state.back_stack == [Route('V06')]
        self.header_order(peer.connect)
        self.click(peer.connect)
        self.start_live.assert_called_once_with(PEER)
        snapshot = self.controller.state.snapshot
        assert snapshot is not None
        self.controller.state.snapshot = replace(
            snapshot,
            live_contexts=[
                LiveContextEntry(
                    ALIAS, PEER, True, 'connecting', outbound_attempt_id='ab' * 16
                )
            ],
        )
        self.refresh()
        Clock.schedule_once(self.live_cancel, FRAME_SETTLE_SECONDS)

    def header_order(self, control: Action) -> None:
        """Checks stable action row ordering and real minimum-size hit targets."""
        peer = self.peer()
        boxes = [rectangle(widget) for widget in (control, peer.call, peer.more)]
        assert boxes[0][0] + boxes[0][2] <= boxes[1][0]
        assert boxes[1][0] + boxes[1][2] <= boxes[2][0]
        assert max(box[1] for box in boxes) - min(box[1] for box in boxes) <= 1

    def modal_title(self, sheet: ActionSheet, title: str) -> None:
        """Requires full measured audio headings instead of ellipsized recovery text."""
        heading = next(
            widget
            for widget in sheet.header.walk()
            if isinstance(widget, Label) and widget.text == title
        )
        assert not heading.shorten
        assert heading.texture_size[1] <= sheet.header.height + 1
        assert heading.texture_size[0] <= heading.width + 1

    def live_cancel(self, _elapsed: float) -> None:
        """Clicks qualified Cancel in the same header slot used for Start and End."""
        peer = self.peer()
        assert peer.end.accessible_name == 'Cancel Live'
        self.header_order(peer.end)
        self.click(peer.end)
        self.end_live.assert_called_once_with(PEER, None, 'ab' * 16)
        snapshot = self.controller.state.snapshot
        assert snapshot is not None
        self.controller.state.snapshot = replace(
            snapshot,
            live_contexts=[
                LiveContextEntry(ALIAS, PEER, True, 'connected', context_generation=7)
            ],
        )
        self.refresh()
        Clock.schedule_once(self.live_end, FRAME_SETTLE_SECONDS)

    def live_end(self, _elapsed: float) -> None:
        """Clicks End and then the Call target without changing the conversation mode."""
        peer = self.peer()
        assert peer.end.accessible_name == 'End Live'
        self.header_order(peer.end)
        self.click(peer.end)
        assert self.end_live.call_args.args == (PEER, 7, None)
        self.records['start_cancel_end_before_call_and_more'] = 'pass'
        self.controller.state.status = 'Feedback hidden by a deliberate modal'
        self.feedback.render()
        self.feedback.dismiss.focus = True
        self.click(peer.call)
        Clock.schedule_once(self.audio_unavailable, FRAME_SETTLE_SECONDS)

    def audio_unavailable(self, _elapsed: float) -> None:
        """Requires deliberate Call recovery to open one closed explanatory dialog."""
        sheet = ActionSheet.current
        assert sheet is not None and sheet.heading == 'Calls unavailable'
        self.modal_title(sheet, 'Calls unavailable')
        assert not self.feedback.children and not self.feedback.dismiss.focus
        self.records['feedback_focus_revoked_under_modal'] = 'pass'
        self.capture('-audio')
        self.controller.voice.routes.scanned = True
        self.controller.voice.routes.endpoints = tuple(
            AudioEndpoint(
                index,
                f'Headset {index:02}: very long microphone endpoint name that must remain bounded',
                True,
                True,
            )
            for index in range(20)
        )
        go = next(
            widget
            for widget in sheet.walk()
            if isinstance(widget, Action)
            and widget.label.text == 'Go to audio settings'
        )
        self.click(go)
        Clock.schedule_once(self.audio_settings, FRAME_SETTLE_SECONDS)

    def audio_settings(self, _elapsed: float) -> None:
        """Uses the audio modal's scroll viewport to reach the device picker."""
        sheet = ActionSheet.current
        assert sheet is not None and sheet.heading == 'Audio settings'
        self.modal_title(sheet, 'Audio settings')
        self.choose = next(
            widget
            for widget in sheet.walk()
            if isinstance(widget, Action) and widget.label.text == 'Choose microphone'
        )
        sheet.scroll.scroll_to(self.choose, animate=False)
        Clock.schedule_once(self.audio_choose, FRAME_SETTLE_SECONDS)

    def audio_choose(self, _elapsed: float) -> None:
        """Opens a separate bounded scrolling endpoint dialog instead of inline expansion."""
        self.click(self.choose)
        Clock.schedule_once(self.audio_choices, FRAME_SETTLE_SECONDS)

    def audio_choices(self, _elapsed: float) -> None:
        """Checks many long endpoint names preserve scroll and the explicit close target."""
        sheet = ActionSheet.current
        assert sheet is not None and sheet.heading == 'Choose microphone'
        self.modal_title(sheet, 'Choose microphone')
        assert sheet.scroll.do_scroll_y and sheet.column.height > sheet.scroll.height
        assert len(sheet.column.children) == 20
        assert all(
            isinstance(widget, Action)
            and widget.label.shorten
            and widget.width <= sheet.scroll.width
            for widget in sheet.column.children
        )
        self.endpoint_sheet = sheet
        self.capture('-endpoints')
        Window.size = (1180, 760) if self.viewport[0] == 360 else (360, 640)
        Clock.schedule_once(self.audio_choices_resized, FRAME_SETTLE_SECONDS)

    def audio_choices_resized(self, _elapsed: float) -> None:
        """Keeps the same closed picker scrollable across the desktop breakpoint."""
        sheet = ActionSheet.current
        assert sheet is self.endpoint_sheet
        assert sheet is not None and len(sheet.column.children) == 20
        self.modal_title(sheet, 'Choose microphone')
        assert sheet.scroll.do_scroll_y and sheet.column.height > sheet.scroll.height
        close = next(
            widget
            for widget in sheet.header.walk()
            if isinstance(widget, IconAction) and widget.accessible_name == 'Close'
        )
        self.click(close)
        Window.size = self.viewport
        Clock.schedule_once(self.audio_closed, FRAME_SETTLE_SECONDS)

    def audio_closed(self, _elapsed: float) -> None:
        """Requires audio dismissal to leave no expanded picker in the conversation."""
        assert ActionSheet.current is None
        assert self.controller.state.route == Route('V09', PEER, Delivery.LIVE)
        assert not any(
            isinstance(widget, Action) and widget.label.text == 'Choose microphone'
            for widget in self.shell.walk()
        )
        self.records['closed_audio_recovery_and_scrollable_endpoint_picker'] = 'pass'
        self.click(self.peer().more)
        Clock.schedule_once(self.menu_close, FRAME_SETTLE_SECONDS)

    def menu_close(self, _elapsed: float) -> None:
        """Checks More is independently hittable before returning directly to the root."""
        sheet = ActionSheet.current
        assert sheet is not None
        self.click(sheet.cancel)
        Clock.schedule_once(self.back_to_root, FRAME_SETTLE_SECONDS)

    def back_to_root(self, _elapsed: float) -> None:
        """Clicks the visible conversation Back after modal dismissal animation ends."""
        assert ActionSheet.current is None
        back = next(
            widget
            for widget in self.peer().header.walk()
            if isinstance(widget, IconAction) and widget.accessible_name == 'Back'
        )
        self.click(back)
        self.refresh()
        Clock.schedule_once(self.finished, FRAME_SETTLE_SECONDS)

    def finished(self, _elapsed: float) -> None:
        """Confirms Back exits the contact and every media owner remains inert."""
        assert self.controller.state.route == Route('V06'), self.controller.state.route
        assert not any(isinstance(widget, PeerView) for widget in self.shell.walk())
        assert self.controller.voice.worker is None
        assert self.controller.playback.worker is None
        assert not self.controller.calls.media_active
        self.records['back_after_drop_live_switch_exits_conversation'] = 'pass'
        self.capture('-root')
        self.completed = True
        self.stop()

    def on_stop(self) -> None:
        """Releases modal, key and mock ownership without an SDK detach operation."""
        Window.unbind(on_flip=self.first_frame)
        Window.unbind(on_key_down=self.key_down, on_key_up=self.key_up)
        if ActionSheet.current is not None:
            ActionSheet.current.dismiss(animation=False)
        self.patches.close()


def main() -> None:
    """Runs one native width and writes explicitly software-only acceptance evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--width', type=int, default=360)
    parser.add_argument('--height', type=int, default=640)
    args = parser.parse_args()
    args.result.parent.mkdir(parents=True, exist_ok=True)
    harness = ConversationHarness(args.result.with_suffix(''), args.width, args.height)
    harness.run()
    assert harness.completed
    args.result.write_text(
        json.dumps(
            {
                'kind': 'native Kivy window and widgets with synthetic input and SDK DTOs',
                'viewport': [args.width, args.height],
                'font_scale': 1.5,
                'core': False,
                'audio_streams': False,
                'physical_hardware': False,
                'sdk_admission': 'explicit mock; typed acceptance injected',
                'screenshots': harness.images,
                'checks': harness.records,
            },
            indent=2,
        )
        + '\n',
        encoding='utf-8',
    )
    print('NATIVE_CONVERSATION_UX_OK')


if __name__ == '__main__':
    main()
