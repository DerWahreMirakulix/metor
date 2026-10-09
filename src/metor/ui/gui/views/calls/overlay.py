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
from metor.ui.gui.widgets import Action, ActionRow, Label, Panel
from metor.ui.gui.widgets.symbol import IconAction

# Local Package Imports
from ..audio import show_audio_unavailable


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

    def revoke(self) -> None:
        """Clears caller content before cover without ending an accepted Call."""
        for widget in self.walk(restrict=True):
            if isinstance(widget, Action):
                widget.cancel_input()
                widget.focus = False
                widget.disabled = True
                widget.accessible_name = ''
            if isinstance(widget, Label):
                widget.text = ''
        self.clear_widgets()
        self._key = None
        self._duration = self._status = None
        self.occupied_height = 0.0

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
            return
        if state.covered and active and self.bottom_inset:
            self._keyboard_call_panel()
            return
        hide_id = current.call_id if current is not None else None
        hide_phase = current.state if current is not None else None
        hide_generation = state.generation

        def hide_controls() -> None:
            """Does not dismiss a replacement Call through a retained close action."""
            source = calls.current
            if (
                controller.state.generation != hide_generation
                or (source.call_id if source is not None else None) != hide_id
                or (source.state if source is not None else None) is not hide_phase
            ):
                return
            self._hide()

        panel = CallPanel(
            orientation='vertical',
            padding=dp(20),
            spacing=dp(12),
            size_hint=(None, None),
            width=min(dp(420), max(dp(48), self.width - dp(48))),
        )
        header = ActionRow(spacing=dp(12))
        title = Label('Phone call', role='title')
        header.add_widget(title)
        header.add_widget(IconAction('x', 'Hide call controls', hide_controls))
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
                else 'Connected',
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
        self._status = Label(calls.status, role='support', tone='textSecondary')
        body.add_widget(self._status)
        scroll.add_widget(body)
        panel.add_widget(scroll)
        compact = state.covered and active
        actions = ActionRow(
            orientation='horizontal' if compact else 'vertical',
            spacing=dp(12),
        )
        if current is not None:
            call_id = current.call_id
            generation, phase = state.generation, current.state
            if incoming:
                can_locked = (
                    not state.covered or controller.security.accept_calls_locked
                )
                actions.add_widget(
                    Action(
                        'Decline',
                        lambda: self._act(
                            lambda: calls.reject(call_id), call_id, generation, phase
                        ),
                        disabled=state.busy,
                    )
                )
                actions.add_widget(
                    Action(
                        'Accept' if can_locked else 'Unlock to accept',
                        lambda: self._accept(call_id, generation),
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
                        lambda: self._act(
                            calls.mute,
                            call_id,
                            generation,
                            phase,
                            muted=current.muted,
                        ),
                        disabled=state.busy,
                    )
                )
                actions.add_widget(
                    Action(
                        'Hang up',
                        lambda: self._act(calls.end, call_id, generation, phase),
                        tone='danger',
                        disabled=state.busy,
                    )
                )
            elif current.state in {CallState.CONNECTING, CallState.OUTGOING}:
                actions.add_widget(
                    Action(
                        'Cancel call',
                        lambda: self._act(calls.end, call_id, generation, phase),
                        disabled=state.busy or not current.owned,
                    )
                )
            else:
                actions.add_widget(Action('Close', hide_controls))
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
        generation, call_id = self.controller.state.generation, current.call_id
        panel = CallPanel(
            orientation='vertical',
            padding=dp(12),
            spacing=dp(8),
            size_hint=(None, None),
            width=min(dp(420), self.width - dp(48)),
        )
        header = ActionRow(spacing=dp(8))
        title = Label(
            'Call · muted' if current.muted else 'Call · connected', role='support'
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
        header.add_widget(
            IconAction(
                'x',
                'Hide call controls',
                lambda: self._act(self._hide, call_id, generation, CallState.ACTIVE),
            )
        )
        panel.add_widget(header)
        actions = ActionRow(spacing=dp(8))
        actions.add_widget(
            Action(
                'Unmute' if current.muted else 'Mute',
                lambda: self._act(
                    calls.mute,
                    call_id,
                    generation,
                    CallState.ACTIVE,
                    muted=current.muted,
                ),
                disabled=self.controller.state.busy,
            )
        )
        actions.add_widget(
            Action(
                'Hang up',
                lambda: self._act(calls.end, call_id, generation, CallState.ACTIVE),
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

    def _accept(self, call_id: str, generation: int) -> None:
        """Offers explicit closed audio setup before accepting this incoming Call."""
        current = self.controller.calls.current
        if (
            generation != self.controller.state.generation
            or current is None
            or current.call_id != call_id
            or current.state is not CallState.INCOMING
        ):
            return
        if not self.controller.calls.ready and not self.controller.state.covered:
            show_audio_unavailable(self.controller, self.refresh, purpose='calls')
        else:
            self._act(
                lambda: self.controller.calls.accept(call_id),
                call_id,
                generation,
                CallState.INCOMING,
            )

    def _hide(self) -> None:
        """Hides expanded controls while the persistent Call bar keeps the call reachable."""
        calls = self.controller.calls
        calls.visible = False
        calls.revision += 1
        self.refresh()

    def _act(
        self,
        action: Callable[[], object],
        call_id: str,
        generation: int,
        phase: CallState,
        *,
        muted: bool | None = None,
    ) -> None:
        """Activates an exact displayed Call action and requests native repaint."""
        current = self.controller.calls.current
        if (
            self.controller.state.generation != generation
            or current is None
            or current.call_id != call_id
            or current.state is not phase
            or muted is not None
            and current.muted is not muted
        ):
            return
        action()
        self.refresh()
