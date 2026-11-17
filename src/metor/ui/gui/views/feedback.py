"""Single expiring action-result overlay that leaves conversation geometry stable."""

from collections.abc import Callable
from time import monotonic

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from metor.ui.gui.constants import Geometry, GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Label, Panel
from metor.ui.gui.widgets.sheet import ActionSheet
from metor.ui.gui.widgets.symbol import IconAction


class FeedbackOverlay(FloatLayout):
    """Shows the latest deliberate action result once, without a notification badge."""

    def __init__(self, controller: GuiController, refresh: Callable[[], None]) -> None:
        """Creates stable native feedback controls outside the content layout.

        Args:
            controller: Presentation owner; no message or profile data is copied.
            refresh: Coalesced native repaint request.
        """
        super().__init__()
        self.controller, self.refresh = controller, refresh
        self._anchor: Widget | None = None
        self._revision = -1
        self.card = Panel(
            surface='raised',
            orientation='horizontal',
            size_hint=(None, None),
            padding=dp(12),
            spacing=dp(8),
        )
        self.message = Label('', role='support', pos_hint={'center_y': 0.5})
        self.message_viewport = ScrollView(
            do_scroll_x=False, always_overscroll=False, scroll_y=1
        )
        self.message_host = AnchorLayout(size_hint_y=None, anchor_y='center')
        self.message_host.add_widget(self.message)
        self.message_viewport.add_widget(self.message_host)
        self.card.add_widget(self.message_viewport)
        self.dismiss = IconAction(
            'x',
            'Dismiss message',
            self._dismiss,
            surface='raised',
            pos_hint={'center_y': 0.5},
        )
        self.card.add_widget(self.dismiss)
        self.bind(size=self._layout, pos=self._layout)
        self.message.bind(height=self._layout)
        self.message.bind(height=self._message_bounds)
        self.message_viewport.bind(height=self._message_bounds)
        self._expiry = Clock.create_trigger(self._expired, 0)

    def _message_bounds(self, *_args: object) -> None:
        """Centers short results and permits long text to scroll within the card.

        Args:
            _args: Native measured text or viewport height change.
        """
        self.message_host.height = max(
            self.message.height, self.message_viewport.height
        )

    def anchor_to(self, anchor: Widget | None) -> None:
        """Tracks the foreground content viewport as controls and keyboard resize.

        Args:
            anchor: Visible content bounds excluding fixed navigation and input.
        """
        if anchor is self._anchor:
            return
        if self._anchor is not None:
            self._anchor.unbind(pos=self._layout, size=self._layout)
        self._anchor = anchor
        if anchor is not None:
            anchor.bind(pos=self._layout, size=self._layout)
        self._layout()

    def _dismiss(self) -> None:
        """Dismisses only transient feedback without changing the action outcome."""
        self.controller.state.feedback.clear()
        self.render()
        self.refresh()

    def _schedule_expiry(self) -> None:
        """Uses the model's clock and rechecks early native frame dispatch.

        Native timers can dispatch slightly before their deadline. Retaining
        the remaining interval prevents that frame from leaving a result
        permanently visible without extending its model lifetime.
        """
        self._expiry.cancel()
        remaining = self.controller.state.feedback.expires_at - monotonic()
        if remaining > 0:
            self._expiry.timeout = max(GuiLimits.UI_TICK_SECONDS, remaining)
            self._expiry()

    def _expired(self, _elapsed: float) -> None:
        """Repaints expiry even when no Core event or background work arrives.

        Args:
            _elapsed: Native scheduler interval.
        """
        self.render()
        if self.controller.state.feedback.visible():
            self._schedule_expiry()
        self.refresh()

    def _layout(self, *_args: object) -> None:
        """Positions feedback above input without moving or blocking send controls.

        Args:
            _args: Native layout or measured text event.
        """
        anchor = self._anchor
        if anchor is None:
            return
        inset = dp(12)
        minimum_height = dp(Geometry.TARGET) + 2 * inset
        if anchor.height < minimum_height or anchor.width <= 0:
            if self.card.parent is not None:
                self.dismiss.focus = False
                self.remove_widget(self.card)
            return
        left, bottom = self.to_widget(*anchor.to_window(*anchor.pos))
        self.card.width = max(0, min(dp(Geometry.COMPACT_MAX), anchor.width))
        self.card.height = min(
            anchor.height,
            max(minimum_height, self.message.height + 2 * inset),
        )
        self.card.pos = (
            left + (anchor.width - self.card.width) / 2,
            bottom + max(0, min(dp(Geometry.EDGE), anchor.height - self.card.height)),
        )
        if (
            self.card.parent is None
            and self.message.text
            and self.controller.state.feedback.visible()
            and not self.controller.state.covered
            and ActionSheet.current is None
        ):
            self.add_widget(self.card)

    def render(self) -> None:
        """Revokes covered or expired text and reconciles the latest result in place."""
        state = self.controller.state
        text = (
            state.feedback.visible()
            if not state.covered
            and ActionSheet.current is None
            and self._anchor is not None
            else ''
        )
        if state.feedback.revision != self._revision:
            self._expiry.cancel()
            if state.feedback.visible():
                self._schedule_expiry()
        if text:
            if self.message.text != text:
                self.message_viewport.scroll_y = 1
            self.message.text = text
            if self.card.parent is None:
                self.add_widget(self.card)
            self._layout()
        else:
            self._hide()
        self._revision = state.feedback.revision

    def revoke(self) -> None:
        """Clears native text synchronously before applying a privacy cover."""
        self._expiry.cancel()
        self.controller.state.feedback.clear()
        self.anchor_to(None)
        self._hide()

    def _hide(self) -> None:
        """Revokes both native text and keyboard ownership before detaching the card."""
        self.dismiss.focus = False
        if self.card.parent is not None:
            self.remove_widget(self.card)
        self.message.text = ''
