"""Exercises actual native contextual gestures with synthetic input, without Core or hardware IO."""

# ruff: noqa: E402

import argparse
import json
import os
from pathlib import Path
from unittest.mock import Mock
from dataclasses import replace

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
from metor.ui.gui.widgets.controls import TextField
from metor.ui.gui.widgets.symbol import IconAction
from metor.client import FrontendLaunchContext, FrontendProfileState
from metor.core.api import (
    IncomingConnectionEvent,
    PendingConnectionExpiredEvent,
    CallInfo,
    CallState,
    CallStateEvent,
    NotificationPrivacy,
    Delivery,
    LiveContextEntry,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.views.live_invitation import LiveInvitationOverlay
from metor.ui.gui.views.calls import CallOverlay
from metor.ui.gui.views.peer import PeerView
from metor.ui.gui.state import Route
from metor.ui.gui.runtime.voice.models import VoiceReview
from metor.ui.gui.runtime.voice.press import CaptureBinding
from metor.ui.gui.widgets.controls import Action


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
        self.field = TextField(
            text='Keep typing',
            multiline=False,
            size_hint=(None, None),
            size=(dp(240), dp(48)),
            pos=(dp(40), dp(100)),
        )
        self.panel.add_widget(self.field)
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
        self.action.focus = False
        self.field.focus = True
        Clock.schedule_once(self.pointer_feedback, 0.2)

    def pointer_feedback(self, _elapsed: float) -> None:
        """Checks pointer activation preserves typing focus and nested More owns its press."""
        pressed = self.touch('left', 'pointer-with-typing-focus')
        EventLoop.post_dispatch_input('begin', pressed)
        assert self.action.state == 'down'
        assert self.field.focus and not self.action.focus
        EventLoop.post_dispatch_input('end', pressed)
        assert self.primary == [True, True, True]
        self.more = IconAction('ellipsis', 'More', lambda: self.contexts.append(True))
        self.action.add_widget(self.more)
        Clock.schedule_once(self.nested_press, 0.2)

    def nested_press(self, _elapsed: float) -> None:
        """Starts a held nested action through actual window touch dispatch."""
        self.nested = MouseMotionEvent(
            'mouse',
            'nested-more',
            (
                self.more.center_x / Window.width,
                self.more.center_y / Window.height,
                'left',
            ),
            is_touch=True,
        )
        self.nested.scale_for_screen(Window.width, Window.height)
        EventLoop.post_dispatch_input('begin', self.nested)
        assert self.action._hold is None
        assert self.field.focus and not self.more.focus
        Clock.schedule_once(self.nested_release, 0.65)

    def nested_release(self, _elapsed: float) -> None:
        """Ensures the row does not also navigate or open another menu for its child press."""
        assert len(self.contexts) == 3
        EventLoop.post_dispatch_input('end', self.nested)
        assert len(self.contexts) == 4
        assert self.primary == [True, True, True]
        assert self.field.focus
        self.gui = GuiController(
            FrontendLaunchContext(
                'fixture',
                Mock(
                    profile_state=lambda: FrontendProfileState(
                        'fixture',
                        True,
                        False,
                        False,
                    )
                ),
            ),
            simulator=True,
        )
        self.gui.state.covered = False
        self.gui.client = Mock()
        self.gui.submit = Mock(return_value=True)
        self.gui.live_invitations.observe(
            IncomingConnectionEvent('Peer', 'peer', 'exact-call')
        )
        self.overlay = LiveInvitationOverlay(self.gui, lambda: None)
        self.panel.add_widget(self.overlay)
        self.gui.state.busy = True
        self.overlay.render()
        self.accept = next(
            widget
            for widget in self.overlay.walk()
            if isinstance(widget, Action) and widget.label.text == 'Accept'
        )
        assert self.accept.disabled
        self.gui.state.busy = False
        self.overlay.render()
        self.accept = next(
            widget
            for widget in self.overlay.walk()
            if isinstance(widget, Action) and widget.label.text == 'Accept'
        )
        assert not self.accept.disabled
        Clock.schedule_once(self.accept_call, 0.2)

    def accept_call(self, _elapsed: float) -> None:
        """Accepts through the re-enabled native button and hides ended requests."""
        touch = MouseMotionEvent(
            'mouse',
            'accept-call',
            (
                self.accept.center_x / Window.width,
                self.accept.center_y / Window.height,
                'left',
            ),
            is_touch=True,
        )
        touch.scale_for_screen(Window.width, Window.height)
        EventLoop.post_dispatch_input('begin', touch)
        EventLoop.post_dispatch_input('end', touch)
        assert self.gui.submit.call_count == 1
        assert self.gui.live_invitations._operation[1] == 'exact-call'
        assert self.field.focus
        self.gui.live_invitations.observe(
            PendingConnectionExpiredEvent('Peer', 'peer', action_handle='exact-call')
        )
        self.overlay.render()
        assert not self.overlay.children
        self.gui.calls.observe(
            CallStateEvent(
                CallInfo(
                    'phone',
                    'private-peer',
                    'Private Alias',
                    CallState.ACTIVE,
                    muted=False,
                    owned=True,
                )
            )
        )
        self.gui.state.covered = True
        self.gui.security._policy = replace(
            self.gui.security._policy,
            notifications_locked=NotificationPrivacy.ANONYMIZE,
        )
        self.phone_overlay = CallOverlay(self.gui, lambda: None)
        self.panel.add_widget(self.phone_overlay)
        self.phone_overlay.render()
        self.mute = next(
            widget
            for widget in self.phone_overlay.walk()
            if isinstance(widget, Action) and widget.label.text == 'Mute'
        )
        assert not any(
            getattr(widget, 'text', '') == 'Private Alias'
            for widget in self.phone_overlay.walk()
        )
        Clock.schedule_once(self.mute_phone, 0.2)

    def mute_phone(self, _elapsed: float) -> None:
        """Dispatches reduced locked Call controls without unlocking private chat."""
        touch = MouseMotionEvent(
            'mouse',
            'phone-mute',
            (
                self.mute.center_x / Window.width,
                self.mute.center_y / Window.height,
                'left',
            ),
            is_touch=True,
        )
        touch.scale_for_screen(Window.width, Window.height)
        EventLoop.post_dispatch_input('begin', touch)
        EventLoop.post_dispatch_input('end', touch)
        assert self.gui.submit.call_count == 2
        assert self.gui.calls._operation[1] == 'phone'
        assert self.gui.state.covered
        self.gui.state.covered = False
        self.gui.state.snapshot = RuntimeSnapshotEvent(
            'fixture',
            '',
            profile_instance_id='instance',
            epoch='epoch',
            live_contexts=[
                LiveContextEntry(
                    'Peer',
                    'peer',
                    True,
                    'connected',
                    context_generation=7,
                )
            ],
        )
        self.gui.state.route = Route('V09', 'peer', Delivery.LIVE)
        self.review_binding = CaptureBinding(
            'instance',
            'epoch',
            self.gui.state.generation,
            'peer',
            Delivery.LIVE,
            'draft',
            7,
        )
        self.gui.voice.reviews['peer'] = VoiceReview(self.review_binding, 640, 20)
        self.panel.remove_widget(self.field)
        self.field.focus = False
        self.panel.remove_widget(self.action)
        self.panel.remove_widget(self.overlay)
        self.peer = PeerView(self.gui, lambda: None, wide=False)
        self.panel.add_widget(self.peer)
        self.panel.remove_widget(self.phone_overlay)
        self.panel.add_widget(self.phone_overlay)
        self.gui.calls.visible = False
        self.gui.calls.revision += 1
        self.phone_overlay.render()
        self.preview = self.peer.composer.preview
        self.review_send = self.peer.composer.commit
        self.review_send.focus = True
        Window.size = (360, 640)
        Clock.schedule_once(self.review_call_resize, 0.3)

    def review_call_resize(self, _elapsed: float) -> None:
        """Preserves review and keyboard ownership while an accepted Call stays active."""
        assert self.gui.calls.active
        assert self.peer.composer._mode == 'review'
        assert self.preview.disabled, 'Call allowed competing message preview audio'
        assert self.review_send.focus
        assert self.gui.voice.reviews['peer'].binding == self.review_binding
        self.peer.reflow(wide=True)
        self.peer.update()
        Window.size = (1180, 760)
        self.phone_overlay.render()
        Clock.schedule_once(self.review_call_finished, 0.3)

    def review_call_finished(self, _elapsed: float) -> None:
        """Checks responsive layout has not rebuilt the staged review or resumed media."""
        self.peer.update()
        self.phone_overlay.render()
        assert self.peer.composer.preview is self.preview
        assert self.peer.composer.commit is self.review_send
        assert self.review_send.focus
        assert self.gui.voice.reviews['peer'].binding == self.review_binding
        assert self.gui.calls.active
        assert not self.gui.voice.available()
        assert self.gui.voice.worker is None and self.gui.playback.worker is None
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
                'pointer_preserves_typing_focus': 'pass',
                'nested_more_owns_press': 'pass',
                'live_accept_reenabled_after_busy': 'pass',
                'ended_invitations_hidden': 'pass',
                'locked_phone_mute_reachable': 'pass',
                'locked_phone_identity_anonymous': 'pass',
                'call_and_unsent_review_coexist': 'pass',
                'review_focus_survives_call_and_resize': 'pass',
                'message_media_stays_inert_during_call': 'pass',
            },
            indent=2,
        )
        + '\n'
    )


if __name__ == '__main__':
    main()
