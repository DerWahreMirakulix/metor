"""Measured control rows and keyboard focus visibility in native scrolling layouts."""

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

from metor.ui.gui.constants import Geometry


def reveal_focus(widget: Widget, focused: bool) -> None:
    """Bring an attached focus target into its scroll viewport without activating it."""
    if not focused or widget.get_root_window() is None:
        return
    parent = widget.parent
    while parent is not None and parent.parent is not parent:
        if isinstance(parent, ScrollView):
            parent.scroll_to(widget, padding=Geometry.EDGE, animate=False)
            break
        parent = parent.parent


class ActionRow(BoxLayout):
    """Lets the row owner grow when its controls or headings need additional lines."""

    def __init__(self, **kwargs: object) -> None:
        """Creates a content-measured horizontal row with a minimum control height."""
        kwargs.setdefault('size_hint_y', None)
        kwargs.setdefault('height', dp(Geometry.TARGET))
        super().__init__(**kwargs)
        self.bind(minimum_height=self._measure)

    def _measure(self, *_args: object) -> None:
        """Reserves the real child height instead of allowing wrapped labels to overlap."""
        self.height = max(dp(Geometry.TARGET), self.minimum_height)
