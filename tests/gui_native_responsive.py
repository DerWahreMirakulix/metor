"""Native breakpoint regression for persistent composer, PTT and timeline ownership."""

from collections.abc import Callable

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp

from metor.ui.gui.app import MetorApp
from metor.ui.gui.views.peer import PeerView


def exercise_responsive(app: MetorApp, complete: Callable[[], None]) -> None:
    """Resizes the actual application across the desktop breakpoint without replacing its peer.

    Args:
        app: Native simulator containing enough synthetic rows for scrolling.
        complete: Continuation once the original viewport is restored.
    Returns:
        None
    """
    assert app.shell is not None
    peer = next(widget for widget in app.shell.walk() if isinstance(widget, PeerView))
    original = tuple(Window.size)
    entry, ptt, timeline = peer.composer.entry, peer.composer.ptt, peer.timeline
    entry.text = 'Draft and cursor survive the breakpoint'
    entry.cursor = (5, 0)
    entry.focus = True
    timeline.scroll.scroll_y = 0.6
    anchor = timeline._anchor
    controls = dict(timeline._widgets)
    route = app.controller.state.route
    sizes = iter((959, 960, 1180, 959, int(original[0] / dp(1))))

    def resize(_elapsed: float = 0) -> None:
        """Changes only native geometry; no fixture navigation restores lost state.

        Args:
            _elapsed: Native frame interval.
        Returns:
            None
        """
        width = next(sizes, None)
        if width is None:
            assert tuple(Window.size) == original
            complete()
            return
        Window.size = (dp(width), original[1])
        Clock.schedule_once(verify, 0.3)

    def verify(_elapsed: float) -> None:
        """Checks the actual reflowed controls, focus and scroll ownership before another resize.

        Args:
            _elapsed: Native geometry interval.
        Returns:
            None
        """
        assert app.shell._peer_panel is peer
        assert peer.composer.entry is entry and peer.composer.ptt is ptt
        assert entry.focus and entry.text == 'Draft and cursor survive the breakpoint'
        assert entry.cursor == (5, 0)
        assert peer.timeline is timeline and timeline._widgets == controls
        assert timeline._anchor == anchor and not timeline._edge
        assert app.controller.state.route == route and app.controller.client is None
        assert peer._end_parent is (
            peer.header if Window.width >= dp(960) else peer.controls
        )
        assert peer.timeline.height >= dp(48)
        Clock.schedule_once(resize, 0)

    Clock.schedule_once(resize, 0.3)
