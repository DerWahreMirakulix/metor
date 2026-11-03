"""Minimal full-cover Power and pre-acceptance purge device surfaces."""

from collections.abc import Callable

from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.widget import Widget

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.device import DevicePhase
from metor.ui.gui.theme import color
from metor.ui.gui.widgets import Action, Label

# Local Package Imports
from .cover import PrivateForm


def device_view(controller: GuiController, refresh: Callable[[], None]) -> AnchorLayout:
    """Renders only lifecycle-safe text and explicit reversible power actions.

    Args:
        controller: Device lifecycle owner.
        refresh: Native repaint request.
    Returns:
        AnchorLayout: Full-application covered surface.
    """
    device = controller.device
    wrapper = PrivateForm()
    body = wrapper.body
    body.add_widget(Label(device.title, role='title'))
    body.add_widget(Label(device.detail, tone='textSecondary'))
    if device.phase is DevicePhase.PURGE_ARMING:
        progress = max(0.0, min(device.progress, 1.0))
        body.add_widget(
            Label(
                f'Hold progress · {round(progress * 100)}%',
                role='support',
            )
        )
        track = Widget(size_hint_y=None, height=dp(6))
        with track.canvas:
            Color(*color('raised'))
            rail = RoundedRectangle(radius=[dp(3)])
            Color(*color('danger'))
            fill = RoundedRectangle(radius=[dp(3)])

        def place(*_args: object) -> None:
            """Draw only the hold time reported by the device controller."""
            rail.pos, rail.size = track.pos, track.size
            fill.pos, fill.size = track.pos, (track.width * progress, track.height)

        track.bind(pos=place, size=place)
        place()
        body.add_widget(track)
    elif device.phase in {DevicePhase.POWER_MENU, DevicePhase.POWER_FAILED}:

        def poweroff() -> None:
            """Requests preparation and schedules repaint.

            Args:
                None
            Returns:
                None
            """
            device.request_poweroff()
            refresh()

        def cancel() -> None:
            """Cancels the reversible power surface and schedules repaint.

            Args:
                None
            Returns:
                None
            """
            device.cancel()
            refresh()

        body.add_widget(
            Action(
                'Retry' if device.phase is DevicePhase.POWER_FAILED else 'Power off',
                poweroff,
                tone='danger',
                disabled=controller.state.busy,
            )
        )
        body.add_widget(Action('Cancel', cancel, disabled=controller.state.busy))
    return wrapper
