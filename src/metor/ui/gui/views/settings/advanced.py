"""Safe descriptor-based Advanced settings and content-free local platform diagnostics."""

import platform

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet

# Local Package Imports
from .descriptors import core_settings_group


def advanced_body(controller: GuiController) -> BoxLayout:
    """Renders only Core-permitted technical settings and bounded local diagnostics.

    Args:
        controller: Current SDK-driven settings owner.
    Returns:
        BoxLayout: Measured Advanced column.
    """
    body = BoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None)
    body.bind(minimum_height=body.setter('height'))
    body.add_widget(
        Action(
            'Raw activity history',
            lambda: controller.navigate(Route('V18', history_raw=True)),
        )
    )
    core_settings_group(controller, body, 'Advanced')

    def diagnostics() -> None:
        """Shows process/platform facts without profile paths, payloads or secrets.

        Args:
            None
        Returns:
            None
        """

        def build(column: BoxLayout) -> None:
            """Adds a finite, content-free diagnostic snapshot.

            Args:
                column: Shared sheet scroll column.
            Returns:
                None
            """
            lines = (
                'Platform: ' + platform.system(),
                'Architecture: ' + platform.machine(),
                'Python: ' + platform.python_version(),
                'Mode: ' + ('Simulator' if controller.simulator else 'Native GUI'),
                'Headset route: '
                + (
                    'Confirmed'
                    if controller.voice.headset_confirmed
                    else 'Not confirmed'
                ),
                'Audio input worker: '
                + ('Active' if controller.voice.running else 'Idle'),
                'Audio output worker: '
                + ('Active' if controller.playback.running else 'Idle'),
            )
            for line in lines:
                column.add_widget(Label(line, role='support'))

        ActionSheet(controller, build, title='Platform diagnostics').show()

    body.add_widget(Action('Platform diagnostics', diagnostics))
    return body
