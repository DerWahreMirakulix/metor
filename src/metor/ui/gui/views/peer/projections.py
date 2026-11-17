"""Bounded native DROP/LIVE view reuse for one authorized foreground peer."""

from collections.abc import Callable

from metor.core.api import Delivery, MessagesDataEvent
from metor.ui.gui.runtime import GuiController

# Local Package Imports
from .panel import PeerView
from .timeline import projection


class PeerProjections:
    """Retains at most two immutable routes within one uninterrupted conversation."""

    def __init__(self, controller: GuiController, refresh: Callable[[], None]) -> None:
        """Creates an empty view owner without starting any client operation."""
        self.controller, self.refresh = controller, refresh
        self._owner: tuple[int, str] | None = None
        self._views: dict[Delivery, PeerView] = {}
        self._drop_page: MessagesDataEvent | None = None

    def reconcile(self, *, allowed: bool, metrics_changed: bool) -> None:
        """Discards departed ownership and suspends the hidden projection before reuse.

        Args:
            allowed: Whether the normal foreground route is authorized and uncovered.
            metrics_changed: Whether native pixel scaling requires replacement widgets.
        """
        state, route = self.controller.state, self.controller.state.route
        owner = (
            (state.generation, route.peer)
            if allowed and route.view in {'V08', 'V09'} and route.peer is not None
            else None
        )
        if owner != self._owner or metrics_changed:
            self.clear()
        self._owner = owner
        for delivery, view in tuple(self._views.items()):
            if view.route == route:
                continue
            if not view.disabled or view.parent is not None:
                view.suspend()
            if view.parent is not None:
                view.parent.remove_widget(view)
            if delivery is Delivery.DROP and (
                self.controller.messages is None
                or self.controller.messages is not self._drop_page
                and view.timeline._widgets.keys()
                - {row.key for row in projection(self.controller, view.route)}
            ):
                view.revoke()
                self._views.pop(delivery)
        self._drop_page = self.controller.messages if owner is not None else None

    def current(self, *, wide: bool) -> PeerView:
        """Reconciles current public facts before a retained view can be attached.

        Args:
            wide: Current responsive shell mode.
        Returns:
            PeerView: Authorized route whose media and input remain controller-owned.
        """
        route = self.controller.state.route
        if self._owner != (self.controller.state.generation, route.peer):
            raise RuntimeError('Peer projection owner is unavailable')
        view = self._views.get(route.delivery)
        if view is not None and view.route != route:
            view.revoke()
            view = None
        if view is None:
            view = PeerView(self.controller, self.refresh, wide=wide)
            self._views[route.delivery] = view
        else:
            view.reflow(wide=wide)
        return view

    def clear(self) -> None:
        """Synchronously revokes private text and drops all retained route references."""
        for view in self._views.values():
            view.revoke()
            if view.parent is not None:
                view.parent.remove_widget(view)
        self._views.clear()
        self._owner = None
        self._drop_page = None
