"""Reduced telephone controls with privacy-projected identity and persistent App-Lock audio."""

from collections.abc import Callable
import time

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.input.motionevent import MotionEvent

from metor.core.api import CallState, NotificationPrivacy
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, Panel
from metor.ui.gui.widgets.symbol import IconAction

# Local Package Imports
from .audio import show_audio_unavailable


class CallPanel(Panel):
    """Consumes touches within telephone controls without a native modal focus grab."""

    def on_touch_down(self, touch: MotionEvent) -> bool:
        """Keeps a phone control press from reaching obscured chat controls."""
        return bool(super().on_touch_down(touch) or self.collide_point(*touch.pos))


class CallOverlay(FloatLayout):
    """Shows accepted duplex and exact-request actions over either chat or lock cover."""

    def __init__(
        self, controller: GuiController, refresh: Callable[[], None], **kwargs: object
    ) -> None:
        """Creates empty native presentation without probing or opening audio."""
        super().__init__(**kwargs)
        self.controller, self.refresh = controller, refresh
        self.bottom_inset = 0.0
        self.occupied_height = 0.0
        self._key: tuple[object, ...] | None = None
        self._duration: Label | None = None
        self._status: Label | None = None
        self.bind(size=lambda *_args: self.refresh())

    def render(self) -> None:
        """Updates duration without replacing controls or exposing locked chat identity."""
        controller, calls = self.controller, self.controller.calls
        state, current = controller.state, calls.current
        active = calls.active
        seconds = (
            max(0, int(time.time() - current.started_at))
            if active and current is not None and current.started_at is not None
            else 0
        )
        if self._duration is not None:
            self._duration.text = f'{seconds // 60:02d}:{seconds % 60:02d}'
        if self._status is not None:
            self._status.text = calls.status
        privacy = (
            controller.security.notification_privacy
            if state.covered
            else NotificationPrivacy.SHOW_ALL
        )
        alias = current.alias if current is not None else ''
        if current is not None and not state.covered and state.snapshot is not None:
            snapshot = state.snapshot
            alias = next(
                (
                    name
                    for peer, name in (
                        [(item.onion, item.alias) for item in snapshot.contacts]
                        + [(item.onion, item.alias) for item in snapshot.conversations]
                        + [(item.onion, item.alias) for item in snapshot.live_contexts]
                    )
                    if peer == current.peer
                ),
                alias,
            )
        incoming = current is not None and current.state is CallState.INCOMING
        key = (
            state.generation,
            state.covered,
            state.busy,
            calls.revision,
            calls.ready,
            calls.media_active,
            self.size[:],
            self.bottom_inset,
            privacy,
            alias,
        )
        if key == self._key:
            return
        self._key = key
        self.clear_widgets()
        self.occupied_height = 0.0
        self._duration = self._status = None
        if incoming and state.covered and privacy is NotificationPrivacy.OFF:
            return
        if current is None and not calls.status:
            return
        if not calls.visible:
            if current is not None and current.state is not CallState.ENDED:
                self.add_widget(
                    Action(
                        'Phone call',
                        self._show,
                        size_hint=(None, None),
                        width=dp(160),
                        pos_hint={'right': 1, 'top': 1},
                    )
                )
            return
        if state.covered and active and self.bottom_inset:
            self._keyboard_call_panel()
            return
        panel = CallPanel(
            orientation='vertical',
            padding=dp(20),
            spacing=dp(12),
            size_hint=(None, None),
            width=min(dp(420), max(dp(48), self.width - dp(48))),
        )
        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        title = Label('Phone call', role='title')
        title.bind(
            height=lambda _widget, height: setattr(
                header, 'height', max(dp(48), height)
            )
        )
        header.add_widget(title)
        header.add_widget(IconAction('x', 'Hide call controls', self._hide))
        panel.add_widget(header)
        scroll = ScrollView(do_scroll_x=False)
        body = BoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None)
        body.bind(minimum_height=body.setter('height'))
        if current is not None:
            if privacy is NotificationPrivacy.SHOW_ALL and alias:
                body.add_widget(Label(alias, role='peer'))
            phase = {
                CallState.CONNECTING: 'Connecting call…',
                CallState.OUTGOING: 'Ringing…',
                CallState.INCOMING: 'Incoming phone call',
                CallState.ACTIVE: 'Connected · microphone muted'
                if current.muted
                else 'Connected · headset audio',
                CallState.ENDED: 'Call ended'
                + (
                    ' · ' + current.reason.value.replace('_', ' ')
                    if current.reason is not None
                    else ''
                ),
            }[current.state]
            body.add_widget(Label(phase, role='support'))
        if active:
            self._duration = Label(
                f'{seconds // 60:02d}:{seconds % 60:02d}', role='peer'
            )
            body.add_widget(self._duration)
        elif not state.covered:
            body.add_widget(
                Label(
                    'Headset operation · no speaker echo cancellation',
                    role='support',
                    tone='textSecondary',
                )
            )
        self._status = Label(calls.status, role='support', tone='textSecondary')
        body.add_widget(self._status)
        scroll.add_widget(body)
        panel.add_widget(scroll)
        compact = state.covered and active
        actions = BoxLayout(
            orientation='horizontal' if compact else 'vertical',
            size_hint_y=None,
            height=dp(48) if compact else 0,
            spacing=dp(12),
        )
        actions.bind(minimum_height=actions.setter('height'))
        if current is not None:
            call_id = current.call_id
            if incoming:
                can_locked = (
                    not state.covered or controller.security.accept_calls_locked
                )
                actions.add_widget(
                    Action(
                        'Decline',
                        lambda: self._act(lambda: calls.reject(call_id)),
                        disabled=state.busy,
                    )
                )
                actions.add_widget(
                    Action(
                        'Accept' if can_locked else 'Unlock to accept',
                        lambda: self._accept(call_id),
                        disabled=state.busy,
                    )
                )
            elif active:
                actions.add_widget(
                    Action(
                        ('Unmute' if current.muted else 'Mute')
                        if state.covered
                        else (
                            'Unmute microphone' if current.muted else 'Mute microphone'
                        ),
                        lambda: self._act(calls.mute),
                        disabled=state.busy,
                    )
                )
                actions.add_widget(
                    Action(
                        'Hang up',
                        lambda: self._act(calls.end),
                        tone='danger',
                        disabled=state.busy,
                    )
                )
            elif current.state in {CallState.CONNECTING, CallState.OUTGOING}:
                actions.add_widget(
                    Action(
                        'Cancel call',
                        lambda: self._act(calls.end),
                        disabled=state.busy or not current.owned,
                    )
                )
            else:
                actions.add_widget(Action('Close', self._hide))
        panel.add_widget(actions)
        self.add_widget(panel)

        def measure(*_args: object) -> None:
            """Keeps call controls reachable above keyboard and within a compact viewport."""
            panel.height = min(
                max(dp(48), self.height - dp(48) - self.bottom_inset),
                body.height + actions.height + header.height + dp(72),
            )
            panel.x = self.x + (self.width - panel.width) / 2
            panel.y = self.y + dp(24) + self.bottom_inset
            self.occupied_height = panel.height + dp(48) + self.bottom_inset

        body.bind(height=measure)
        actions.bind(height=measure)
        header.bind(height=measure)
        measure()

    def _keyboard_call_panel(self) -> None:
        """Keeps accepted phone controls and auth scroll usable above a touch keyboard."""
        calls = self.controller.calls
        current = calls.current
        assert current is not None
        panel = CallPanel(
            orientation='vertical',
            padding=dp(12),
            spacing=dp(8),
            size_hint=(None, None),
            width=min(dp(420), self.width - dp(48)),
        )
        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        title = Label(
            'Call · muted' if current.muted else 'Call · connected', role='support'
        )
        title.bind(
            height=lambda _widget, height: setattr(
                header, 'height', max(dp(48), height)
            )
        )
        header.add_widget(title)
        seconds = (
            max(0, int(time.time() - current.started_at))
            if current.started_at is not None
            else 0
        )
        self._duration = Label(
            f'{seconds // 60:02d}:{seconds % 60:02d}',
            role='support',
            size_hint_x=None,
            width=dp(72),
        )
        header.add_widget(self._duration)
        header.add_widget(IconAction('x', 'Hide call controls', self._hide))
        panel.add_widget(header)
        actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        actions.add_widget(
            Action(
                'Unmute' if current.muted else 'Mute',
                lambda: self._act(calls.mute),
                disabled=self.controller.state.busy,
            )
        )
        actions.add_widget(
            Action(
                'Hang up',
                lambda: self._act(calls.end),
                tone='danger',
                disabled=self.controller.state.busy,
            )
        )
        panel.add_widget(actions)
        self.add_widget(panel)

        def measure(*_args: object) -> None:
            """Reserves exactly the compact control extent above the keyboard."""
            panel.height = header.height + actions.height + dp(32)
            panel.x = self.x + (self.width - panel.width) / 2
            panel.y = self.y + self.bottom_inset + dp(24)
            self.occupied_height = self.bottom_inset + panel.height + dp(48)

        header.bind(height=measure)
        measure()

    def _accept(self, call_id: str) -> None:
        """Offers explicit closed audio setup before accepting this incoming Call."""
        if not self.controller.calls.ready and not self.controller.state.covered:
            show_audio_unavailable(self.controller, self.refresh, purpose='calls')
        else:
            self._act(lambda: self.controller.calls.accept(call_id))

    def _show(self) -> None:
        """Explicitly restores phone controls without navigating or accepting a Call."""
        calls = self.controller.calls
        calls.visible = True
        calls.revision += 1
        self.refresh()

    def _hide(self) -> None:
        """Hides full controls; an active Call remains reachable through a compact badge."""
        calls = self.controller.calls
        calls.visible = False
        calls.revision += 1
        self.refresh()

    def _act(self, action: Callable[[], object]) -> None:
        """Activates an exact displayed Call action and requests native repaint."""
        action()
        self.refresh()
