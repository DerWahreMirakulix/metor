"""Measured control rows that reserve space for full labels and minimum hit targets."""

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.constants import Geometry


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
