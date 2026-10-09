"""Stable responsive LIVE header action with explicit keyboard and tooltip semantics."""

from collections.abc import Callable
from functools import partial

from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from metor.core.api import CallState, Delivery
from metor.ui.gui.constants import Geometry
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import ActionRow, Label
from metor.ui.gui.widgets.symbol import IconAction


class LiveHeaderAction(IconAction):
    """Switches one fixed action between icon and text without replacing its input owner."""

    def __init__(
        self,
        label: str,
        symbol: str,
        callback: Callable[[], object],
        *,
        tone: str = 'text',
        surface: str = 'raised',
    ) -> None:
        """Binds immutable action identity while allowing width-only visual reflow."""
        super().__init__(
            symbol,
            label,
            callback,
            tone=tone,
            surface=surface,
            pos_hint={'center_y': 0.5},
        )
        self.label.text = label
        self.label.shorten = False
        self._show_text = False
        self._measurement: tuple[str, str, float] | None = None
        self._text_width = dp(48)

    def present(self, *, available_width: float) -> None:
        """Shows its explicit label whenever the measured status row has room."""
        key = self.label.text, self.label.font_name, self.label.font_size
        if key != self._measurement:
            measured = CoreLabel(
                text=self.label.text,
                font_name=self.label.font_name,
                font_size=self.label.font_size,
            )
            measured.refresh()
            self._text_width = max(
                dp(Geometry.TARGET), measured.texture.size[0] + dp(24)
            )
            self._measurement = key
        show_text = available_width >= dp(Geometry.TARGET)
        if show_text != self._show_text:
            self.remove_widget(self.symbol if show_text else self.label)
            self.add_widget(self.label if show_text else self.symbol)
            self._show_text = show_text
        self.width = (
            min(self._text_width, available_width) if show_text else dp(Geometry.TARGET)
        )


class PeerHeader(BoxLayout):
    """Owns measured identity actions and explicit LIVE controls for one peer route."""

    def __init__(
        self,
        controller: GuiController,
        route: Route,
        *,
        back: Callable[[], object],
        call: Callable[[], object],
        more: Callable[[], object],
        start: Callable[[], object],
        end: Callable[[int | None, str | None], object],
    ) -> None:
        """Keeps Call and More beside the contact while connection state has its own row."""
        super().__init__(orientation='vertical', size_hint_y=None, spacing=dp(8))
        self.controller, self.route = controller, route
        self._end_callback = end
        self.bind(minimum_height=self.setter('height'))
        title_row = ActionRow(spacing=dp(8))
        self.title_row = title_row
        title_row.add_widget(
            IconAction('chevron-left', 'Back', back, pos_hint={'center_y': 0.5})
        )
        self.name = Label('', role='peer', pos_hint={'center_y': 0.5})
        self._name_space = Widget()
        self.expanded_title = False
        self._expanded_next = False
        self._identity_trigger = Clock.create_trigger(self._apply_identity, -1)
        self._name_measurement: tuple[str, str, float, float] | None = None
        title_row.add_widget(self.name)
        self.call = LiveHeaderAction('In call', 'phone', call)
        self.more = IconAction(
            'ellipsis', 'Conversation actions', more, pos_hint={'center_y': 0.5}
        )
        title_row.add_widget(self.call)
        title_row.add_widget(self.more)
        self.add_widget(title_row)
        self.controls = ActionRow(spacing=dp(12))
        self.subtitle = Label(
            '', role='caption', tone='textSecondary', pos_hint={'center_y': 0.5}
        )
        self.controls.add_widget(self.subtitle)
        self.live_slot = BoxLayout(
            size_hint=(None, None),
            width=dp(48),
            height=dp(48),
            pos_hint={'center_y': 0.5},
        )
        self.live_slot.bind(minimum_height=self.live_slot.setter('height'))
        self.controls.add_widget(self.live_slot)
        self.add_widget(self.controls)
        self.controls.bind(width=lambda *_args: self.update())
        self._end_identity: tuple[int | None, str | None] | None = None
        self.end = LiveHeaderAction(
            'End Live', 'x', partial(end, None, None), tone='danger'
        )
        self.connect = LiveHeaderAction(
            'Start Live', 'plus', start, surface='live', tone='onAccent'
        )
        title_row.bind(width=lambda *_args: self.update())
        self.name.bind(
            text=self._reflow_identity,
            font_name=self._reflow_identity,
            font_size=self._reflow_identity,
        )

    def _reflow_identity(self, *_args: object) -> None:
        """Gives unusually long aliases full width instead of squeezing many narrow lines."""
        inline_width = max(
            dp(1),
            self.title_row.width
            - 2 * dp(Geometry.TARGET)
            - self.call.width
            - 3 * self.title_row.spacing,
        )
        key = self.name.text, self.name.font_name, self.name.font_size, inline_width
        if key == self._name_measurement:
            return
        self._name_measurement = key
        measured = CoreLabel(
            text=self.name.text,
            font_name=self.name.font_name,
            font_size=self.name.font_size,
            text_size=(inline_width, None),
        )
        measured.refresh()
        line = CoreLabel(
            text='Ag', font_name=self.name.font_name, font_size=self.name.font_size
        )
        line.refresh()
        expanded = measured.texture.size[1] > 3 * line.texture.size[1]
        self._expanded_next = expanded
        if expanded != self.expanded_title:
            self._identity_trigger()

    def _apply_identity(self, *_args: object) -> None:
        """Reparents the stable title between frames, after native row layout completes."""
        expanded = self._expanded_next
        if expanded == self.expanded_title:
            return
        if expanded:
            self.title_row.remove_widget(self.name)
            self.title_row.add_widget(self._name_space, index=2)
            self.add_widget(self.name, index=len(self.children))
        else:
            self.remove_widget(self.name)
            self.title_row.remove_widget(self._name_space)
            self.title_row.add_widget(self.name, index=2)
        self.expanded_title = expanded

    def update(self) -> bool:
        """Updates only connection controls before the next native frame is presented.

        Returns:
            bool: Whether Core reports a connected or recoverable LIVE context.
        """
        controller, state = self.controller, self.controller.state
        peer, snapshot = self.route.peer, state.snapshot
        live = (
            next((item for item in snapshot.live_contexts if item.onion == peer), None)
            if snapshot
            else None
        )
        starting = controller.live.starting(peer or '')
        failure = controller.live.failure(peer or '')
        stopping = controller.live.stop_status(peer or '')
        active = live is not None and (
            live.session_state == 'connected' or live.recovery_eligible
        )
        connecting = bool(
            live and live.outbound_attempt_id and not active and not failure
        )
        identity = (
            live.context_generation if live and active else None,
            live.outbound_attempt_id if live and connecting else None,
        )
        if identity != self._end_identity:
            if self.end.parent is not None:
                self.end.parent.remove_widget(self.end)
            self.end = LiveHeaderAction(
                'Cancel Live' if connecting else 'End Live',
                'x',
                partial(self._end_callback, *identity),
                tone='danger',
            )
            self._end_identity = identity
        self.subtitle.text = (
            'Drop conversation'
            if self.route.delivery is Delivery.DROP
            else stopping
            if stopping
            else failure
            if failure
            else 'Changing route…'
            if live and live.route_changing
            else 'Reconnecting…'
            if live and live.session_state != 'connected' and live.recovery_eligible
            else 'Connected · Live'
            if active
            else 'Connecting Live…'
            if connecting or starting
            else 'Incoming Live request'
            if live and live.session_state == 'pending'
            else 'No Live connection'
        )
        control: LiveHeaderAction | None
        if self.route.delivery is Delivery.LIVE:
            control = self.end if active or connecting or stopping else self.connect
            available = (
                active
                or connecting
                or bool(stopping)
                or starting
                or bool(failure)
                or controller.live.idle(peer or '')
            )
            if not available:
                control = None
        else:
            control = self.connect
        for attached in tuple(self.live_slot.children):
            if attached is not control:
                self.live_slot.remove_widget(attached)
        if control is not None:
            if control.parent is None:
                self.live_slot.add_widget(control)
        else:
            self.live_slot.width = 0
        self.end.disabled = self.connect.disabled = (
            state.busy
            or controller.client is None
            or controller.live.pending is not None
            or bool(stopping)
        )
        self.end.disabled = (
            self.end.disabled
            or 'qualified_live_control' not in state.capabilities
            or identity == (None, None)
        )
        self.end.label.text = self.end.accessible_name = stopping or (
            'Cancel Live' if connecting else 'End Live'
        )
        self.connect.disabled = (
            self.connect.disabled
            or starting
            or self.route.delivery is Delivery.DROP
            and not active
            and not controller.live.idle(peer or '')
            or bool(failure)
            and not controller.live.retry_ready(peer or '')
        )
        self.connect.label.text = self.connect.accessible_name = (
            'Open Live'
            if self.route.delivery is Delivery.DROP and active
            else 'Connecting Live…'
            if starting
            else 'Retry Live'
            if failure
            else 'Reconnect Live'
            if live
            else 'Start Live'
        )
        self.call.disabled = state.busy
        current_call = controller.calls.current
        in_call = bool(
            current_call is not None
            and current_call.peer == peer
            and current_call.state is not CallState.ENDED
        )
        self.call.accessible_name = 'Open call controls' if in_call else 'Call'
        if current_call is not None and in_call:
            self.call.label.text = (
                'In call'
                if current_call.state is CallState.ACTIVE
                else 'Incoming call'
                if current_call.state is CallState.INCOMING
                else 'Calling…'
            )
        self.call.present(
            available_width=max(
                dp(Geometry.TARGET),
                self.title_row.width
                - 3 * dp(Geometry.TARGET)
                - 3 * self.title_row.spacing,
            )
            if in_call
            else 0,
        )
        self._reflow_identity()
        if control is not None:
            control.present(
                available_width=max(
                    0, self.controls.width - dp(Geometry.TARGET) - self.controls.spacing
                )
            )
            self.live_slot.width = control.width
        return active
