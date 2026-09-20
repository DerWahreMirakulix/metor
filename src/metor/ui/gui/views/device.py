"""Minimal full-cover Power and pre-acceptance purge device surfaces."""

from collections.abc import Callable

from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView

from metor.ui.gui.constants import Geometry
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.runtime.device import DevicePhase
from metor.ui.gui.widgets import Action, Label


def device_view(controller: GuiController, refresh: Callable[[], None]) -> AnchorLayout:
    """Renders only lifecycle-safe text and explicit reversible power actions.

    Args:
        controller: Device lifecycle owner.
        refresh: Native repaint request.
    Returns:
        AnchorLayout: Full-application covered surface.
    """
    device = controller.device
    wrapper = AnchorLayout(padding=dp(Geometry.EDGE))
    scroll = ScrollView(do_scroll_x=False, size_hint_x=None)
    wrapper.bind(
        width=lambda owner, width: setattr(
            scroll, 'width', min(dp(Geometry.FORM_MAX), width - dp(Geometry.EDGE * 2))
        )
    )
    body = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(16))
    body.bind(minimum_height=body.setter('height'))
    body.add_widget(Label(device.title, role='title'))
    body.add_widget(Label(device.detail, tone='textSecondary'))
    if device.phase is DevicePhase.PURGE_ARMING:
        body.add_widget(
            Label(
                f'Hold progress · {round(device.progress * 100)}%',
                role='peer',
            )
        )
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
    scroll.add_widget(body)
    wrapper.add_widget(scroll)
    return wrapper
