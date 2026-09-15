"""Bounded root-list focus and pixel-anchor preservation without retaining another widget tree."""

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action


class RootContinuity:
    """Retains only a focused control key and the visible root row's relative pixel position."""

    def __init__(self, panel: BoxLayout) -> None:
        """Captures an existing root before its native metadata controls are rebuilt.

        Args:
            panel: Currently displayed root for the same profile, projection and page.
        Returns:
            None
        """
        actions = [
            widget for widget in panel.walk(restrict=True) if isinstance(widget, Action)
        ]
        self.focus_key = next((item.focus_key for item in actions if item.focus), ())
        self.anchor_key: tuple[str, ...] = ()
        self.gap = 0.0
        scroll = next(
            widget
            for widget in panel.walk(restrict=True)
            if isinstance(widget, ScrollView)
        )
        self.scroll_y = scroll.scroll_y
        if not scroll.children or self.scroll_y >= 1:
            return
        column = scroll.children[0]
        visible_top = (
            scroll.height + max(0, column.height - scroll.height) * self.scroll_y
        )
        for action in actions:
            if action.focus_key[:1] == ('peer',) and action.parent is not None:
                row = action.parent
                if row.y - column.y < visible_top:
                    self.anchor_key = action.focus_key
                    self.gap = visible_top - (row.top - column.y)
                    break

    def restore(self, panel: BoxLayout, controller: GuiController) -> None:
        """Restores after native text measurement without stealing newer focus or navigating.

        Args:
            panel: Replacement for the exact original root context.
            controller: Current privacy/generation owner, rechecked at application time.
        Returns:
            None
        """
        generation = controller.state.generation

        def apply(_elapsed: float) -> None:
            """Applies only to a still-visible root after all nested layout work has run.

            Args:
                _elapsed: Native frame interval.
            Returns:
                None
            """
            if (
                controller.state.covered
                or controller.state.generation != generation
                or panel.get_root_window() is None
            ):
                return
            actions = [
                widget
                for widget in panel.walk(restrict=True)
                if isinstance(widget, Action)
            ]
            scroll = next(
                widget
                for widget in panel.walk(restrict=True)
                if isinstance(widget, ScrollView)
            )
            scroll.scroll_y = self.scroll_y
            anchor = next(
                (item for item in actions if item.focus_key == self.anchor_key), None
            )
            if anchor is not None and anchor.parent is not None and scroll.children:
                column = scroll.children[0]
                extent = column.height - scroll.height
                if extent > 0:
                    top = anchor.parent.top - column.y + self.gap
                    scroll.scroll_y = max(0.0, min(1.0, (top - scroll.height) / extent))
            if not self.focus_key or any(
                bool(getattr(widget, 'focus', False))
                for root in Window.children
                for widget in root.walk()
            ):
                return
            focus = next(
                (
                    item
                    for item in actions
                    if item.focus_key == self.focus_key and not item.disabled
                ),
                None,
            )
            if focus is None:
                focus = next(
                    (item for item in actions if item.focus_key[:1] == ('selector',)),
                    None,
                )
            if focus is not None:
                focus.focus = True

        Clock.schedule_once(lambda _elapsed: Clock.schedule_once(apply, 0), 0)
