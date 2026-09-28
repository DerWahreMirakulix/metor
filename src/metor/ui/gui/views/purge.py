"""Minimal noninteractive privacy cover for actual Core destruction outcomes."""

from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.ui.gui.constants import Geometry
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Label


def purge_view(controller: GuiController) -> AnchorLayout:
    """Shows no identity, cancellation, recreated profile or unsupported status-query control.

    Args:
        controller: Read-only destruction observation owner.
    Returns:
        AnchorLayout: Full-application covered layout, including the desktop master.
    """
    wrapper = AnchorLayout(padding=f'{Geometry.EDGE}dp')
    scroll = ScrollView(do_scroll_x=False, size_hint_x=None)

    def fit_width(*_args: object) -> None:
        """Keep the privacy message inside current density-scaled insets.

        Args:
            _args: Native width or padding changes.
        Returns:
            None
        """
        scroll.width = max(
            0,
            min(
                dp(Geometry.FORM_MAX),
                wrapper.width - wrapper.padding[0] - wrapper.padding[2],
            ),
        )

    wrapper.bind(width=fit_width, padding=fit_width)
    body = BoxLayout(orientation='vertical', size_hint_y=None, spacing='16dp')
    body.bind(minimum_height=body.setter('height'))
    body.add_widget(Label(controller.purge.title, role='title'))
    body.add_widget(Label(controller.purge.detail, tone='textSecondary'))
    scroll.add_widget(body)
    wrapper.add_widget(scroll)
    return wrapper
