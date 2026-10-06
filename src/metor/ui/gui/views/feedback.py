"""Single expiring action-result overlay that leaves conversation geometry stable."""

from collections.abc import Callable
from time import monotonic

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.floatlayout import FloatLayout

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
        self.bottom_inset: float = 0
        self._revision = -1
        self.card = Panel(
            surface='raised',
            orientation='horizontal',
            size_hint=(None, None),
            padding=dp(12),
            spacing=dp(8),
        )
        self.message = Label('', role='support')
        self.card.add_widget(self.message)
        self.dismiss = IconAction(
            'x', 'Dismiss message', self._dismiss, surface='raised'
        )
        self.card.add_widget(self.dismiss)
        self.bind(size=self._layout, pos=self._layout)
        self.message.bind(height=self._layout)
        self._expiry = Clock.create_trigger(self._expired, 0)

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
        self.card.width = max(
            0, min(dp(Geometry.COMPACT_MAX), self.width - dp(Geometry.EDGE * 2))
        )
        self.card.height = max(dp(Geometry.TARGET), self.message.height) + dp(24)
        self.card.pos = (
            self.x + (self.width - self.card.width) / 2,
            self.y + self.bottom_inset + dp(Geometry.COMPOSER + Geometry.EDGE * 2),
        )

    def render(self) -> None:
        """Revokes covered or expired text and reconciles the latest result in place."""
        state = self.controller.state
        text = (
            state.feedback.visible()
            if not state.covered and ActionSheet.current is None
            else ''
        )
        if state.feedback.revision != self._revision:
            self._expiry.cancel()
            if state.feedback.visible():
                self._schedule_expiry()
        if text:
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
        self._hide()

    def _hide(self) -> None:
        """Revokes both native text and keyboard ownership before detaching the card."""
        self.dismiss.focus = False
        if self.card.parent is not None:
            self.remove_widget(self.card)
        self.message.text = ''
