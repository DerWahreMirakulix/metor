"""Measured Core setting groups sourced solely from public safe descriptors."""

from functools import partial

from kivy.uix.boxlayout import BoxLayout

from metor.core.api import SettingSnapshotEntry
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, SettingRow

# Local Package Imports
from .editor import SettingEditor


def open_setting(controller: GuiController, entry: SettingSnapshotEntry) -> None:
    """Opens an explicit editor without modifying policy merely by navigation.

    Args:
        controller: Current authorization owner.
        entry: Captured setting identity and descriptor.
    Returns:
        None
    """
    if not controller.state.covered and entry.editable:
        SettingEditor(controller, entry).show()


def core_settings_group(controller: GuiController, body: BoxLayout, group: str) -> None:
    """Adds finite current values in the requested ordinary or Advanced group.

    Args:
        controller: Current public setting model.
        body: Existing measured settings scroll column.
        group: Public descriptor grouping label.
    Returns:
        None
    """
    settings = controller.core_settings
    if 'safe_setting_descriptors' not in controller.state.capabilities:
        if group == 'Live':
            body.add_widget(
                Label(
                    'Service settings unavailable with this Core version.',
                    role='support',
                )
            )
        return
    if not settings.loaded:
        if group in {'Live', 'Advanced'}:
            body.add_widget(
                Label(settings.error or 'Loading service settings…', role='support')
            )
            if settings.error:
                body.add_widget(Action('Retry settings', settings.reload))
        return
    if settings.error and group in {'Live', 'Advanced'}:
        body.add_widget(Label(settings.error, role='support', tone='info'))
        body.add_widget(Action('Reload service settings', settings.reload))
    for entry in settings.entries:
        if entry.display_group != group:
            continue
        value = (
            ('On' if entry.value == 'True' else 'Off')
            if entry.value_type == 'bool'
            else entry.value
        )
        body.add_widget(
            SettingRow(
                entry.display_name,
                value,
                'Profile override'
                if entry.source == 'profile_override'
                else 'Inherited global value',
                partial(open_setting, controller, entry),
                disabled=controller.state.busy or not entry.editable,
            )
        )
