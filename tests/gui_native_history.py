"""Synthetic activity-history fixtures for the ordinary native framebuffer harness."""

from collections.abc import Callable
from unittest.mock import patch

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView

from metor.core.api import (
    HistoryDataEvent,
    SummaryHistoryEntry,
    HistoryEntryFamily,
    HistorySummaryEventCode,
    HistoryEntryActor,
)
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.app import MetorApp
from metor.ui.gui.widgets import Action
from metor.ui.gui.widgets.sheet import ActionSheet


def configure_history(controller: GuiController) -> None:
    """Installs public metadata without opening Core or reconstructing message content.

    Args:
        controller: Explicit native simulator fixture owner.
    Returns:
        None
    """
    controller.state.covered = False
    controller.state.route = Route('V18')
    controller.state.capabilities |= {'history_metadata_pages'}
    controller.history.needed = False
    controller.history.page = HistoryDataEvent(
        [
            SummaryHistoryEntry(
                timestamp='2026-09-12T10:00:00+00:00',
                family=HistoryEntryFamily.DROP,
                event_code=HistorySummaryEventCode.DROP_SENT,
                peer_onion='b' * 56,
                actor=HistoryEntryActor.LOCAL,
                trigger=None,
                detail_code=None,
                detail_text='',
                flow_id=str(index),
                alias='Rhea ' + 'Long alias ' * 5,
            )
            for index in range(4)
        ],
        'fixture',
        metadata_only=True,
        record_live=False,
        record_drop=False,
        has_older=True,
        next_before_id=4,
    )


def exercise_history(app: MetorApp, complete: Callable[[], None]) -> None:
    """Checks reachable pagination, Cancel default and one native confirmed clear.

    Args:
        app: Isolated simulator with synthetic public history DTOs.
        complete: Continuation after asynchronous layout/focus checks.
    Returns:
        None
    """
    scroll = next(
        widget for widget in app.shell.walk() if isinstance(widget, ScrollView)
    )
    scroll.scroll_y = 0

    def enter(action: Action) -> None:
        """Dispatches real native focus/keys without actual Core mutations.

        Args:
            action: Current action control.
        Returns:
            None
        """
        action.focus = True
        Window.dispatch('on_key_down', 13, 40, '\r', [])
        Window.dispatch('on_key_up', 13, 40)
        action.focus = False

    def confirm(_elapsed: float) -> None:
        """Invokes one synthetic clear after the native confirmation has settled.

        Args:
            _elapsed: Native scheduling delay.
        Returns:
            None
        """
        sheet = ActionSheet.current
        assert sheet is not None and sheet.cancel.focus
        primary = next(
            widget
            for widget in sheet.actions.children
            if isinstance(widget, Action) and widget.accessible_name == 'Clear'
        )
        assert primary.height >= dp(48) and primary.to_window(*primary.pos)[1] >= 0
        with patch.object(app.controller.history, 'clear', return_value=True) as clear:
            enter(primary)
            clear.assert_called_once()
        assert ActionSheet.current is None
        scroll.scroll_y = 1
        app.controller.state.status = ''
        app.refresh()
        complete()

    def cancel(_elapsed: float) -> None:
        """Verifies initial Enter remains on Cancel and submits no destruction.

        Args:
            _elapsed: Native scheduling delay.
        Returns:
            None
        """
        sheet = ActionSheet.current
        assert sheet is not None and sheet.cancel.focus
        with patch.object(app.controller.history, 'clear') as clear:
            enter(sheet.cancel)
            clear.assert_not_called()
        assert ActionSheet.current is None
        clear_action = next(
            widget
            for widget in app.shell.walk()
            if isinstance(widget, Action)
            and widget.accessible_name == 'Clear activity history'
        )
        enter(clear_action)
        Clock.schedule_once(confirm, 0.3)

    def page(_elapsed: float) -> None:
        """Verifies bottom controls fit and Enter targets the intended page action.

        Args:
            _elapsed: Native layout settling delay.
        Returns:
            None
        """
        actions = {
            widget.accessible_name: widget
            for widget in app.shell.walk()
            if isinstance(widget, Action)
        }
        for name in ('Newer', 'Older', 'Refresh newest'):
            action = actions[name]
            assert action.height >= dp(48)
            assert action.to_window(*action.pos)[1] >= 0
        with patch.object(app.controller.history, 'move') as move:
            enter(actions['Older'])
            move.assert_called_once_with('older')
        enter(actions['Clear activity history'])
        Clock.schedule_once(cancel, 0.3)

    def refreshed(_elapsed: float) -> None:
        """Checks the rebuilt native scroll retains the previous visible position.

        Args:
            _elapsed: Native restore/layout delay.
        Returns:
            None
        """
        nonlocal scroll
        scroll = next(
            widget for widget in app.shell.walk() if isinstance(widget, ScrollView)
        )
        assert abs(scroll.scroll_y) < 0.01
        page(_elapsed)

    def refresh(_elapsed: float) -> None:
        """Forces a background-status rebuild while the reader is at the bottom.

        Args:
            _elapsed: Native layout delay.
        Returns:
            None
        """
        app.controller.state.status = 'History readback available'
        app.refresh()
        Clock.schedule_once(refreshed, 0.3)

    Clock.schedule_once(refresh, 0.3)
