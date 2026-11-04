"""Minimal noninteractive privacy cover for actual Core destruction outcomes."""

from kivy.uix.anchorlayout import AnchorLayout

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Label

# Local Package Imports
from .cover import PrivateForm


def purge_view(controller: GuiController) -> AnchorLayout:
    """Shows no identity, cancellation, recreated profile or unsupported status-query control.

    Args:
        controller: Read-only destruction observation owner.
    Returns:
        AnchorLayout: Full-application covered layout, including the desktop master.
    """
    wrapper = PrivateForm()
    body = wrapper.body
    body.add_widget(Label(controller.purge.title, role='title'))
    body.add_widget(Label(controller.purge.detail, tone='textSecondary'))
    return wrapper
