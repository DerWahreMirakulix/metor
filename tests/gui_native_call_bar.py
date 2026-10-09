"""Real Kivy Call bar, scoped controls and replacement dialog with synthetic Call DTOs."""

# ruff: noqa: E402

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import time
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
from kivy.metrics import Metrics
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout

from metor.client import FrontendLaunchContext
from metor.core.api import (
    CallInfo,
    CallState,
    CallStateEvent,
    ClientRestrictedEvent,
    ClientUnlockMethod,
    ContactEntry,
    Delivery,
    MessageDirectionCode,
    NotificationPrivacy,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.app import MetorApp
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.voice.models import VoiceReview
from metor.ui.gui.runtime.voice.press import CaptureBinding
from metor.ui.gui.state import Route
from metor.ui.gui.views.actions import call_peer
from metor.ui.gui.views.calls import CallBar, CallOverlay
from metor.ui.gui.views.peer import PeerView
from metor.ui.gui.views.shell import Shell
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.symbol import IconAction
from metor.ui.gui.widgets.voice import VoiceCard

FRAME_SECONDS = 0.3
PEER = 'call-bar-peer'
OTHER = 'call-bar-other-peer'
ALIAS = 'Alex with a readable long contact name'
OTHER_ALIAS = 'A different contact with a readable name'


class CallBarHarness(App):
    """Exercises concrete Call controls without Core, native media or transport."""

    def __init__(self, output: Path, width: int, height: int) -> None:
        """Captures only evidence paths and synthetic layout parameters."""
        super().__init__()
        self.output, self.viewport_size = output, (width, height)
        self.completed = False
        self.checks: dict[str, bool] = {}

    def build(self) -> FloatLayout:
        """Uses the app's reserved bar and actual shell composition at enlarged text size."""
        Window.size = self.viewport_size
        Metrics.fontscale = 1.5
        self.gui = GuiController(
            FrontendLaunchContext('fixture', Mock()), simulator=True
        )
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        self.gui.state.covered = False
        self.gui.state.route = Route('V08', PEER, Delivery.DROP)
        self.gui.state.capabilities = frozenset({'calls'})
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            '',
            epoch='epoch',
            profile_instance_id='instance',
            contacts=[ContactEntry(ALIAS, PEER), ContactEntry(OTHER_ALIAS, OTHER)],
        )
        self.call = CallInfo(
            'displayed-call',
            PEER,
            ALIAS,
            CallState.ACTIVE,
            started_at=time.time() - 83,
            owned=True,
        )
        self.gui.calls.observe(CallStateEvent(self.call))
        self.stage = FloatLayout()
        self.viewport = BoxLayout(orientation='vertical')
        self.shell = Shell(self.gui, lambda: None)
        self.bar = CallBar(self.gui, lambda: None)
        self.overlay = CallOverlay(self.gui, lambda: None)
        self.viewport.add_widget(self.shell)
        self.viewport.add_widget(self.bar, index=1)
        self.stage.add_widget(self.viewport)
        self.stage.add_widget(self.overlay)
        privacy_owner = Mock(
            controller=self.gui,
            accessibility=None,
            feedback_overlay=None,
            call_bar=self.bar,
            call_overlay=self.overlay,
            invitation_overlay=None,
            invitation_slot=None,
            shell=self.shell,
        )
        self.gui.state.privacy_fence = lambda: MetorApp._revoke_native_privacy(
            privacy_owner
        )
        Clock.schedule_once(self.initial_paint, FRAME_SECONDS)
        return self.stage

    def initial_paint(self, _elapsed: float) -> None:
        """Settles native layout before scheduling any pointer assertions."""
        self.paint()
        Clock.schedule_once(self.controls, FRAME_SECONDS)

    def paint(self, _elapsed: float = 0.0) -> None:
        """Reserves measured chrome before rendering any root, chat, settings or lock surface."""
        self.bar.render()
        self.shell.activity_inset = self.bar.height
        self.viewport.do_layout()
        self.shell.render()
        self.overlay.render()
        self.shell.inset_locked_call(self.overlay.occupied_height)

    @staticmethod
    def click(widget: Action, identity: str) -> None:
        """Dispatches native window-coordinate pointer events at a fully visible target."""
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
        """Checks bar reachability and truthful audio blocking while text stays editable."""
        assert self.bar._open is not None
        assert 'Call in progress' in self.bar._open.label.text
        assert '01:' in self.bar._open.label.text
        assert self.bar.y + 0.5 >= self.shell.top, (self.bar.y, self.shell.top)
        assert self.bar._open.height >= self.bar._open.label.height
        assert not self.bar._open.label.shorten
        peer = next(
            widget for widget in self.shell.walk() if isinstance(widget, PeerView)
        )
        assert any(
            isinstance(widget, Label) and widget.text == ALIAS for widget in peer.walk()
        )
        assert peer.call.label.text == 'In call'
        assert peer.call.accessible_name == 'Open call controls'
        assert not peer.composer.entry.disabled and not peer.composer.entry.readonly
        assert peer.composer.ptt.disabled
        assert peer.composer.ptt.label.text == 'Available after call'
        target = self.gui.playback.target(
            PEER, Delivery.DROP, MessageDirectionCode.IN, 'voice'
        )
        assert target is not None
        voice = VoiceCard(self.gui, target, lambda: None)
        voice.update(PcmVoice.FRAME_BYTES, True, PcmVoice.CODEC, 'Unread')
        assert voice.play.disabled and voice.title.text == 'Available after call'
        assert self.gui.client.release_voice.call_count == 0
        self.gui.voice.reviews[PEER] = VoiceReview(
            CaptureBinding(
                'instance',
                'epoch',
                self.gui.state.generation,
                PEER,
                Delivery.DROP,
                'draft',
            ),
            PcmVoice.FRAME_BYTES,
            20,
        )
        peer.composer.update()
        assert peer.composer.preview.disabled
        assert peer.composer.preview.label.text == 'Available after call'
        assert not peer.composer.commit.disabled
        self.checks['bar_and_voice_audio_ownership'] = True
        self.overlay._hide()
        self.paint()
        assert not self.overlay.children and self.bar.height > 0
        original = self.bar._open
        assert original is not None
        self.saved_open = original
        Clock.schedule_once(self.reopen, FRAME_SECONDS)

    def reopen(self, _elapsed: float) -> None:
        """Reopens only after the hidden-overlay frame has settled its measured chrome."""
        self.click(self.saved_open, 'reopen-call')
        assert (
            self.gui.calls.visible
            and self.gui.calls.current.call_id == self.call.call_id
        )
        self.paint()
        assert self.bar._open is self.saved_open
        self.gui.client.start_call.assert_not_called()
        self.checks['hidden_controls_reopen_exact_call_without_new_call'] = True
        Clock.schedule_once(self.capture_and_confirm, FRAME_SECONDS)

    def capture_and_confirm(self, _elapsed: float) -> None:
        """Captures a settled native frame before opening the replacement dialog."""
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.stage.export_to_png(str(self.output.with_suffix('.png')))
        call_peer(self.gui, OTHER, lambda: None)
        Clock.schedule_once(self.confirmation, FRAME_SECONDS)

    def confirmation(self, _elapsed: float) -> None:
        """Exercises the wrapped replacement confirmation and its captured exact target."""
        sheet = ActionSheet.current
        assert sheet is not None and sheet.heading == 'Call ongoing'
        primary = sheet.primary_action
        assert primary is not None and not primary.disabled
        assert not primary.label.shorten and primary.height >= primary.label.height
        with patch.object(self.gui.calls, 'handover', return_value=True) as handover:
            self.click(primary, 'replace-call')
            handover.assert_called_once_with(self.call.call_id, OTHER)
        assert ActionSheet.current is None
        self.checks['replacement_dialog_full_label_and_exact_call_and_peer'] = True
        self.gui.state.route = Route('V17')
        self.paint()
        assert self.bar._open is not None and ALIAS in self.bar._open.label.text
        self.checks['bar_persists_in_settings'] = True
        retained = self.bar._open
        assert retained is not None
        self.gui.state.covered = True
        assert retained.label.text == '' and retained.accessible_name == ''
        assert retained.disabled and not self.bar.children and not self.overlay.children
        self.checks['app_cover_synchronously_revokes_retained_caller_text'] = True
        self.gui.state.route = Route('V05')
        self.gui.security.restriction = ClientRestrictedEvent(
            ClientUnlockMethod.PROFILE_PASSWORD
        )
        self.gui.security._policy = replace(
            self.gui.security._policy,
            notifications_locked=NotificationPrivacy.ANONYMIZE,
        )
        self.paint()
        Clock.schedule_once(self.locked, FRAME_SECONDS)

    def locked(self, _elapsed: float) -> None:
        """Preserves accepted Call controls while revoking private caller identity."""
        assert self.gui.calls.active
        assert not self.overlay.children
        assert (
            self.bar._open is not None
            and 'Call in progress' in self.bar._open.label.text
        )
        assert not any(
            isinstance(widget, Label) and ALIAS in widget.text
            for widget in self.stage.walk()
        )
        assert not any(
            isinstance(widget, Action) and ALIAS in widget.accessible_name
            for widget in self.stage.walk()
        )
        self.checks['accepted_call_lock_privacy'] = True
        self.click(self.bar._open, 'locked-open-controls')
        assert self.gui.calls.visible
        self.paint()
        Clock.schedule_once(self.locked_expanded, FRAME_SECONDS)

    def locked_expanded(self, _elapsed: float) -> None:
        """Opens and hides locked Call controls through native targets without ending audio."""
        assert self.overlay.children and self.gui.calls.active
        hide = next(
            widget
            for widget in self.overlay.walk()
            if isinstance(widget, IconAction)
            and widget.accessible_name == 'Hide call controls'
        )
        self.click(hide, 'locked-hide-controls')
        self.paint()
        assert not self.overlay.children and self.bar.height > 0
        assert self.gui.calls.active and not self.gui.calls.visible
        self.checks['locked_bar_reopens_and_hides_exact_call_controls'] = True
        assert self.bar._open is not None
        self.click(self.bar._open, 'locked-reopen-controls')
        self.paint()
        Clock.schedule_once(self.stale_controls, FRAME_SECONDS)

    def stale_controls(self, _elapsed: float) -> None:
        """Does not mutate or hide a replacement through retained earlier Call actions."""
        old_hangup = next(
            widget
            for widget in self.bar.walk()
            if isinstance(widget, IconAction) and widget.accessible_name == 'Hang up'
        )
        old_expanded = next(
            widget
            for widget in self.overlay.walk()
            if isinstance(widget, Action) and widget.label.text == 'Hang up'
        )
        old_hide = next(
            widget
            for widget in self.overlay.walk()
            if isinstance(widget, IconAction)
            and widget.accessible_name == 'Hide call controls'
        )
        replacement = CallInfo(
            'replacement-call',
            OTHER,
            OTHER_ALIAS,
            CallState.ACTIVE,
            owned=True,
            started_at=time.time(),
        )
        self.gui.calls.observe(CallStateEvent(replacement))
        revision = self.gui.calls.revision
        old_hangup._activate()
        old_expanded._activate()
        old_hide._activate()
        assert self.gui.calls._operation is None and self.gui.calls.revision == revision
        self.checks['stale_bar_and_expanded_hangup_do_not_end_replacement'] = True
        self.gui.security._policy = replace(
            self.gui.security._policy, notifications_locked=NotificationPrivacy.OFF
        )
        self.gui.calls.observe(
            CallStateEvent(CallInfo('incoming', OTHER, OTHER_ALIAS, CallState.INCOMING))
        )
        self.paint()
        assert self.bar.height == 0 and not self.bar.children
        self.checks['incoming_call_hidden_with_locked_notifications_off'] = True
        self.completed = True
        self.stop()

    def on_stop(self) -> None:
        """Closes synthetic modal and GUI resources without any transport or native stream."""
        if ActionSheet.current is not None:
            ActionSheet.current.dismiss(animation=False)
        self.gui.close()


def main() -> None:
    """Writes explicit native-widget evidence with Core and physical audio absent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--width', type=int, default=360)
    parser.add_argument('--height', type=int, default=640)
    args = parser.parse_args()
    harness = CallBarHarness(args.result, args.width, args.height)
    harness.run()
    assert harness.completed
    args.result.write_text(
        json.dumps(
            {
                'kind': 'real Kivy Call bar and modal with synthetic pointer input and Call DTOs',
                'viewport': [args.width, args.height],
                'font_scale': 1.5,
                'core': False,
                'audio_streams': False,
                'physical_hardware': False,
                'checks': harness.checks,
            },
            indent=2,
        )
        + '\n',
        encoding='utf-8',
    )
    print('CALL_BAR_UX_OK')


if __name__ == '__main__':
    main()
