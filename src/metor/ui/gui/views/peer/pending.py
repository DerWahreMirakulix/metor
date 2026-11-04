"""Explicit bulk fallback footer for retained work in an ended LIVE conversation."""

from collections.abc import Callable

from kivy.metrics import dp

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.live import pending_fallback_count
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label, Panel


class PendingLiveFooter(Panel):
    """Keeps ended-context work actionable without presenting an editable composer."""

    def __init__(
        self, controller: GuiController, route: Route, refresh: Callable[[], None]
    ) -> None:
        """Captures one route and retains its action through asynchronous readback."""
        super().__init__(
            orientation='vertical',
            padding=dp(12),
            spacing=dp(8),
            size_hint_y=None,
        )
        self.controller, self.route, self.refresh = controller, route, refresh
        self.bind(minimum_height=self.setter('height'))
        self.summary = Label('', role='support', tone='textSecondary')
        self.send = Action(
            'Send all pending as Drops',
            self._send,
            surface='drop',
            tone='onAccent',
        )
        self.add_widget(self.summary)
        self.add_widget(self.send)

    def _blocked(self) -> bool:
        """Prevents duplicate mutations and action through a departed route."""
        controller, state = self.controller, self.controller.state
        return (
            state.covered
            or state.busy
            or state.route != self.route
            or controller.client is None
            or controller.live.pending is not None
            or controller.receipts.busy
            or not pending_fallback_count(controller, self.route)
        )

    def _send(self) -> None:
        """Requests Core's complete eligible bulk conversion with the original IDs."""
        if self._blocked():
            return
        self.controller.live.fallback(self.route.peer or '')
        self.update()
        self.refresh()

    def update(self) -> None:
        """Shows the current retained count and immediate acknowledged-action progress."""
        pending = pending_fallback_count(self.controller, self.route)
        self.summary.text = f'Live ended · {pending} pending ' + (
            'message' if pending == 1 else 'messages'
        )
        mutation = self.controller.live.pending
        label = (
            'Sending pending as Drops…'
            if mutation is not None
            and mutation.peer == self.route.peer
            and mutation.kind == 'fallback'
            else 'Checking pending messages…'
            if self.controller.receipts.busy
            else 'Send all pending as Drops'
        )
        self.send.label.text = self.send.accessible_name = label
        self.send.disabled = self._blocked()
