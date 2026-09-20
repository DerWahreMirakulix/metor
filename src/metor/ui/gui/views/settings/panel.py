"""Protected GUI settings with explicit confirmation for weakened lock policy."""

from collections.abc import Callable
from dataclasses import replace
from functools import partial

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.core.api import ClientUnlockMethod, GuiPreferences
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label, SettingRow

# Local Package Imports
from ..audio import audio_routes_body
from ..actions import clear_drops
from .preferences import live_preferences
from .descriptors import core_settings_group
from .timeout import TimeoutEditor
from .privacy import notification_preference, profile_name_preference
from ..profiles import request_exit


def settings_body(controller: GuiController, refresh: Callable[[], None]) -> BoxLayout:
    """Builds settings from the current protected preference result only.

    Args:
        controller: GUI command and policy owner.
        refresh: Native repaint request.
    Returns:
        BoxLayout: Measured settings section.
    """
    body = BoxLayout(orientation='vertical', spacing=dp(12), size_hint_y=None)
    body.bind(minimum_height=body.setter('height'))
    state = controller.state
    current = state.preferences
    if current is None:
        body.add_widget(Label('Protected settings unavailable', role='peer'))
        body.add_widget(
            Label(
                'Open a supported encrypted profile to manage these settings.',
                tone='textSecondary',
            )
        )
        return body
    preferences = current.preferences
    if controller.preferences.last_error:

        def reload_preferences() -> None:
            """Requests authoritative readback without repeating a protected save.

            Args:
                None
            Returns:
                None
            """
            controller.preferences.refresh_needed = True

        body.add_widget(
            Action('Reload preferences', reload_preferences, disabled=state.busy)
        )

    def save(value: GuiPreferences) -> None:
        """Submits a validated protected change without changing local truth.

        Args:
            value: Explicit strictly validated preference document.
        Returns:
            None
        """
        try:
            controller.preferences.save(value, current.preferences_revision)
        except (ValueError, TypeError):
            state.status = 'That setting value is not supported'
        refresh()

    live_preferences(controller, body, preferences, save)
    core_settings_group(controller, body, 'Live')
    body.add_widget(Label('Privacy', role='peer'))
    core_settings_group(controller, body, 'Privacy')
    body.add_widget(
        Action('Activity history', lambda: controller.navigate(Route('V18')))
    )
    notification_preference(controller, body, preferences, save)
    body.add_widget(
        Action(
            'Clear all Drops',
            partial(clear_drops, controller, None),
            tone='danger',
            disabled=state.busy or controller.drop.pending is not None,
        )
    )
    body.add_widget(Label('Device', role='peer'))
    if controller.device.battery_status:
        body.add_widget(
            Label(
                controller.device.battery_status, role='support', tone='textSecondary'
            )
        )
    core_settings_group(controller, body, 'Device')
    body.add_widget(audio_routes_body(controller, refresh))
    body.add_widget(
        Label('Metor application lock', role='support', tone='textSecondary')
    )

    def lock() -> None:
        """Requests application restriction and immediately repaints the cover.

        Args:
            None
        Returns:
            None
        """
        controller.security.lock()
        refresh()

    body.add_widget(Action('Lock Metor', lock))
    if controller.device.power_available:
        body.add_widget(Action('Power off', controller.device.open_power_menu))

    def manage() -> None:
        """Opens protected lock-method management.

        Args:
            None
        Returns:
            None
        """
        controller.navigate(Route('V04'))
        refresh()

    body.add_widget(
        SettingRow(
            'Unlock method',
            {
                ClientUnlockMethod.PIN: 'PIN',
                ClientUnlockMethod.PROFILE_PASSWORD: 'Profile password',
                ClientUnlockMethod.NONE: 'None',
            }[preferences.unlock_method],
            'This profile · password, PIN or explicit None',
            manage,
        )
    )
    profile_name_preference(controller, body, preferences, save)
    body.add_widget(
        SettingRow(
            'Keyboard layout',
            preferences.keyboard_layout.upper(),
            'This profile · local software keyboard only',
            lambda: save(
                replace(
                    preferences,
                    keyboard_layout='qwertz'
                    if preferences.keyboard_layout == 'qwerty'
                    else 'qwerty',
                )
            ),
            disabled=state.busy,
        )
    )
    body.add_widget(
        SettingRow(
            'Application timeout',
            str(preferences.idle_seconds) + ' s'
            if preferences.idle_seconds
            else 'Disabled',
            'This profile · inactivity before Metor locks',
            lambda: TimeoutEditor(controller, current).show(),
            disabled=state.busy,
        )
    )
    body.add_widget(Label('Profiles and Advanced', role='peer'))
    body.add_widget(Action('Profiles', lambda: controller.navigate(Route('V20'))))
    body.add_widget(Action('Advanced', lambda: controller.navigate(Route('V19'))))
    body.add_widget(Action('Exit Metor', lambda: request_exit(controller)))
    return body
