"""Native root refresh proof using actual screen coordinates and canonical peer focus."""

from collections.abc import Callable
from dataclasses import replace

from kivy.clock import Clock
from kivy.uix.scrollview import ScrollView

from metor.core.api import Delivery, DropConversationSummaryEntry
from metor.ui.gui.app import MetorApp
from metor.ui.gui.widgets import Action


def exercise_root_refresh(app: MetorApp, complete: Callable[[], None]) -> None:
    """Changes root metadata while an older row owns focus and a visible pixel anchor.

    Args:
        app: Native simulator with 130 synthetic conversation summaries.
        complete: Continuation after rebuilt native bounds have settled.
    Returns:
        None
    """

    def after_layout(callback: Callable[[float], None], frames: int = 5) -> None:
        """Waits for nested native layout frames, independent of software GL frame time.

        Args:
            callback: Assertion or input to execute after layout.
            frames: Remaining native frames, including deferred continuity restoration.
        Returns:
            None
        """
        if frames:
            Clock.schedule_once(lambda elapsed: after_layout(callback, frames - 1), 0)
        else:
            callback(0)

    assert app.shell is not None
    controller = app.controller
    controller.state.root_pages[Delivery.DROP] = 0
    app.shell.render()

    def scroll_older(_elapsed: float) -> None:
        """Moves the native viewport before selecting a genuinely visible row.

        Args:
            _elapsed: Native layout interval.
        Returns:
            None
        """
        root = app.shell._root_panel
        scroll = next(
            widget for widget in root.walk() if isinstance(widget, ScrollView)
        )
        scroll.scroll_y = 0.7
        after_layout(update)

    def update(_elapsed: float) -> None:
        """Injects only newer synthetic snapshot metadata, with no restoration by the fixture.

        Args:
            _elapsed: Native scroll-settle interval.
        Returns:
            None
        """
        root = app.shell._root_panel
        scroll = next(
            widget for widget in root.walk() if isinstance(widget, ScrollView)
        )
        bottom = scroll.to_window(*scroll.pos)[1]
        action = next(
            widget
            for widget in root.walk()
            if isinstance(widget, Action)
            and widget.focus_key[:1] == ('peer',)
            and bottom <= widget.to_window(*widget.pos)[1]
            and widget.to_window(*widget.pos)[1] + widget.height
            <= bottom + scroll.height
        )
        key, y = action.focus_key, action.to_window(*action.pos)[1]
        action.focus = True
        snapshot = controller.state.snapshot
        controller.state.snapshot = replace(
            snapshot,
            revision=(snapshot.revision or 0) + 1,
            conversations=[DropConversationSummaryEntry('A new conversation', 'a-new')]
            + [
                replace(
                    item,
                    alias='Renamed while focused'
                    if item.onion == key[-1]
                    else item.alias,
                )
                for item in snapshot.conversations
            ],
        )
        app.refresh()

        def verify(_elapsed: float) -> None:
            """Checks the re-created control keeps exact focus and its actual native screen position.

            Args:
                _elapsed: Native metadata/layout interval.
            Returns:
                None
            """
            current = app.shell._root_panel
            replacement = next(
                widget
                for widget in current.walk()
                if isinstance(widget, Action) and widget.focus_key == key
            )
            assert replacement.focus
            assert 'Renamed while focused' in replacement.accessible_name
            assert abs(replacement.to_window(*replacement.pos)[1] - y) <= 1, (
                y,
                replacement.to_window(*replacement.pos)[1],
                app.shell._root_panel.scroll.scroll_y,
            )
            assert controller.state.route.view == 'V06' and controller.client is None
            complete()

        after_layout(verify)

    after_layout(scroll_older)
