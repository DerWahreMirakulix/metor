"""Shared, width-limited presentation for entry and locked forms."""

from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.ui.gui.constants import Geometry
from metor.ui.gui.widgets import Label, Panel


class PrivateForm(AnchorLayout):
    """Center a private form, keeping one comfortable text column and scrolling only its overflow."""

    def __init__(self) -> None:
        """Keep card edges and text insets distinct even at minimum width or with a keyboard."""
        super().__init__(padding='24dp')
        self.card = Panel(orientation='vertical', size_hint=(None, None))
        self.scroll = ScrollView(do_scroll_x=False, always_overscroll=False)
        self.body = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(8))
        self.body.bind(minimum_height=self.body.setter('height'))
        self.body.add_widget(Label('METOR', role='eyebrow', tone='textSecondary'))
        self.scroll.add_widget(self.body)
        self.card.add_widget(self.scroll)
        self.add_widget(self.card)
        self.bind(size=self._fit, padding=self._fit)
        self.body.bind(minimum_height=self._fit)
        self._fit()

    def _fit(self, *_args: object) -> None:
        """Limit reading width on desktop and preserve working room on a small display."""
        width = max(0, self.width - self.padding[0] - self.padding[2])
        height = max(0, self.height - self.padding[1] - self.padding[3])
        inset = min(
            dp(Geometry.EDGE), max(dp(16), (width - dp(Geometry.MIN_WIDTH)) / 2)
        )
        self.card.padding = (inset, dp(20))
        self.card.width = min(width, dp(Geometry.FORM_MAX) + 2 * inset)
        self.card.height = min(height, self.body.minimum_height + dp(40))
        self.scroll.do_scroll_y = self.body.minimum_height > max(0, height - dp(40))
