"""Atomic initial settings presentation across asynchronous metadata sources."""

from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Label


def show_initial_loading(
    controller: GuiController, body: BoxLayout, *, include_device: bool = False
) -> bool:
    """Keeps controls in one complete layout until their first metadata reads resolve.

    Loaded values stay usable during later refreshes. A failed service read ends
    the initial wait so protected preferences and the explicit retry remain
    available; a device read always publishes a confirmed or unavailable result.

    Args:
        controller: Current authorized settings and device metadata owners.
        body: Empty measured column for either progress or settings controls.
        include_device: Whether this view includes local hardware settings.
    Returns:
        bool: Whether initial metadata is still pending and progress was shown.
    """
    core = controller.core_settings
    waiting_for_core = (
        'safe_setting_descriptors' in controller.state.capabilities
        and not core.loaded
        and not core.initial_read_complete
    )
    device = controller.device.settings
    waiting_for_device = include_device and device.available and not device.loaded
    if waiting_for_device and not device.pending:
        device.refresh()
    if not waiting_for_core and not waiting_for_device:
        return False
    body.add_widget(Label('Loading settings…', role='peer'))
    body.add_widget(
        Label(
            'Reading current values. Navigation stays available.',
            role='support',
            tone='textSecondary',
        )
    )
    return True
