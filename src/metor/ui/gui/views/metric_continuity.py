"""Retain volatile peer and contact interaction state across native DPI reflow."""

from __future__ import annotations

from dataclasses import dataclass

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from metor.core.api import MessageDirectionCode
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, TextField

# Local Package Imports
from .contacts import ContactListView
from .peer import PeerView


def _focused_action_identity(panel: Widget) -> tuple[str, ...] | None:
    """Finds a stable action key or a uniquely matchable static label.

    Args:
        panel: Current foreground interaction panel.
    Returns:
        tuple[str, ...] | None: Stable key or static label, if any.
    """
    return next(
        (
            action.focus_key or ('label', action.accessible_name)
            for action in panel.walk(restrict=True)
            if isinstance(action, Action) and action.focus
        ),
        None,
    )


def _has_new_focus() -> bool:
    """Prevents a deferred restore from overriding newer native input.

    Args:
        None
    Returns:
        bool: Whether an attached widget currently owns keyboard focus.
    """
    return any(
        bool(getattr(widget, 'focus', False))
        for root in Window.children
        for widget in root.walk()
    )


def _restore_action(panel: Widget, identity: tuple[str, ...] | None) -> None:
    """Restores focus only to the same available action in the replacement panel.

    Args:
        panel: Rebuilt foreground interaction panel.
        identity: Previously focused stable key or static label.
    Returns:
        None
    """
    if identity is None or _has_new_focus():
        return
    matches = [
        item
        for item in panel.walk(restrict=True)
        if isinstance(item, Action)
        and (item.focus_key or ('label', item.accessible_name)) == identity
        and not item.disabled
    ]
    if len(matches) == 1:
        matches[0].focus = True


@dataclass(frozen=True)
class PeerMetricContinuity:
    """Capture one peer's text focus and identity-based timeline position."""

    generation: int
    route: Route
    action_identity: tuple[str, ...] | None
    text_focused: bool
    cursor: tuple[int, int]
    scroll_y: float
    anchor: tuple[MessageDirectionCode, str] | None
    edge: bool
    known: frozenset[tuple[MessageDirectionCode, str]]
    new_count: int

    @classmethod
    def capture(
        cls, panel: PeerView, controller: GuiController
    ) -> PeerMetricContinuity:
        """Copies only volatile viewport metadata, leaving drafts in GUI state.

        Args:
            panel: Peer panel being replaced for a different pixel scale.
            controller: Current presentation authority.
        Returns:
            PeerMetricContinuity: Captured focus and timeline position.
        """
        timeline = panel.timeline
        return cls(
            controller.state.generation,
            panel.route,
            _focused_action_identity(panel),
            panel.composer.entry.focus,
            panel.composer.entry.cursor,
            timeline.scroll.scroll_y,
            timeline._anchor,
            timeline._edge,
            frozenset(timeline._known),
            timeline._new_count,
        )

    def restore(self, panel: PeerView, controller: GuiController) -> None:
        """Rebuilds the same timeline page and restores focus after native layout.

        Args:
            panel: Replacement peer panel for the new pixel scale.
            controller: Current presentation authority.
        Returns:
            None
        """
        state = controller.state
        if (
            state.covered
            or state.generation != self.generation
            or state.route != self.route
        ):
            return
        timeline = panel.timeline
        timeline._anchor = self.anchor
        timeline._edge = self.edge
        timeline._known = set(self.known)
        timeline._new_count = self.new_count
        panel.update()

        def apply(_elapsed: float) -> None:
            """Restores only to an attached panel still representing the same route.

            Args:
                _elapsed: Native layout scheduling delay.
            Returns:
                None
            """
            if (
                state.covered
                or state.generation != self.generation
                or state.route != self.route
                or panel.get_root_window() is None
            ):
                return
            timeline.scroll.scroll_y = self.scroll_y
            if (
                self.text_focused
                and not panel.composer.entry.disabled
                and not _has_new_focus()
            ):
                panel.composer.entry.focus = True
                panel.composer.entry.cursor = self.cursor
            else:
                _restore_action(panel, self.action_identity)

        Clock.schedule_once(lambda _elapsed: Clock.schedule_once(apply, 0), 0)


@dataclass(frozen=True)
class SecondaryMetricContinuity:
    """Retain a nonsecret secondary form's focused field and scroll position."""

    generation: int
    route: Route
    action_identity: tuple[str, ...] | None
    field_index: int | None
    cursor: tuple[int, int] | None
    scroll_y: float | None

    @classmethod
    def capture(
        cls, panel: Widget, controller: GuiController
    ) -> SecondaryMetricContinuity:
        """Captures native focus without copying the controller-owned form values.

        Args:
            panel: Current secondary foreground panel.
            controller: Current presentation authority.
        Returns:
            SecondaryMetricContinuity: Field identity, cursor and viewport position.
        """
        fields = [
            item for item in panel.walk(restrict=True) if isinstance(item, TextField)
        ]
        focused = next(
            (index for index, field in enumerate(fields) if field.focus), None
        )
        scroll = next(
            (
                item
                for item in panel.walk(restrict=True)
                if isinstance(item, ScrollView)
            ),
            None,
        )
        return cls(
            controller.state.generation,
            controller.state.route,
            _focused_action_identity(panel),
            focused,
            fields[focused].cursor if focused is not None else None,
            scroll.scroll_y if scroll is not None else None,
        )

    def restore(self, panel: Widget, controller: GuiController) -> None:
        """Restores focus only after the same authorized route is visible again.

        Args:
            panel: Replacement secondary panel.
            controller: Current presentation authority.
        Returns:
            None
        """
        state = controller.state

        def apply(_elapsed: float) -> None:
            """Applies only to the newly attached authorized panel.

            Args:
                _elapsed: Native layout scheduling delay.
            Returns:
                None
            """
            if (
                state.covered
                or state.generation != self.generation
                or state.route != self.route
                or panel.get_root_window() is None
            ):
                return
            scroll = next(
                (
                    item
                    for item in panel.walk(restrict=True)
                    if isinstance(item, ScrollView)
                ),
                None,
            )
            if scroll is not None and self.scroll_y is not None:
                scroll.scroll_y = self.scroll_y
            fields = [
                item
                for item in panel.walk(restrict=True)
                if isinstance(item, TextField)
            ]
            if self.field_index is not None and self.field_index < len(fields):
                field = fields[self.field_index]
                if (
                    not field.disabled
                    and self.cursor is not None
                    and not _has_new_focus()
                ):
                    field.focus = True
                    field.cursor = self.cursor
                    return
            _restore_action(panel, self.action_identity)

        Clock.schedule_once(lambda _elapsed: Clock.schedule_once(apply, 0), 0)


@dataclass(frozen=True)
class ContactMetricContinuity:
    """Retain the address-book query's native cursor and visible page position."""

    generation: int
    route: Route
    action_identity: tuple[str, ...] | None
    search_focused: bool
    cursor: tuple[int, int]
    scroll_y: float

    @classmethod
    def capture(
        cls, panel: ContactListView, controller: GuiController
    ) -> ContactMetricContinuity:
        """Copies only native focus and scroll; query and selection stay in the controller.

        Args:
            panel: Contact list being replaced for a different pixel scale.
            controller: Current presentation authority.
        Returns:
            ContactMetricContinuity: Captured local interaction position.
        """
        return cls(
            controller.state.generation,
            panel.route,
            _focused_action_identity(panel),
            panel.search.focus,
            panel.search.cursor,
            panel.scroll.scroll_y,
        )

    def restore(self, panel: ContactListView, controller: GuiController) -> None:
        """Restores native interaction without changing contact selection or query.

        Args:
            panel: Replacement contact list.
            controller: Current presentation authority.
        Returns:
            None
        """
        state = controller.state

        def apply(_elapsed: float) -> None:
            """Applies only after the same authorized contact view is attached.

            Args:
                _elapsed: Native layout scheduling delay.
            Returns:
                None
            """
            if (
                state.covered
                or state.generation != self.generation
                or state.route != self.route
                or panel.get_root_window() is None
            ):
                return
            panel.scroll.scroll_y = self.scroll_y
            if self.search_focused and not _has_new_focus():
                panel.search.focus = True
                panel.search.cursor = self.cursor
            else:
                _restore_action(panel, self.action_identity)

        Clock.schedule_once(lambda _elapsed: Clock.schedule_once(apply, 0), 0)
