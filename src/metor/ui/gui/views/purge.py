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
    wrapper = AnchorLayout(padding=dp(Geometry.EDGE))
    scroll = ScrollView(do_scroll_x=False, size_hint_x=None)
    wrapper.bind(
        width=lambda owner, width: setattr(
            scroll, 'width', min(dp(Geometry.FORM_MAX), width - dp(Geometry.EDGE * 2))
        )
    )
    body = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(16))
    body.bind(minimum_height=body.setter('height'))
    body.add_widget(Label(controller.purge.title, role='title'))
    body.add_widget(Label(controller.purge.detail, tone='textSecondary'))
    scroll.add_widget(body)
    wrapper.add_widget(scroll)
    return wrapper
