"""Exact Call acceptance permission independent of LIVE chat and message media."""

from collections.abc import Callable
from dataclasses import replace
from functools import partial

from kivy.uix.boxlayout import BoxLayout

from metor.core.api import GuiPreferences
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Label, SettingRow
from metor.ui.gui.widgets.sheet import confirm


def call_preferences(
    controller: GuiController,
    body: BoxLayout,
    preferences: GuiPreferences,
    save: Callable[[GuiPreferences], None],
) -> None:
    """Offers explicit Call-only locked acceptance with a secure disabled default.

    Args:
        controller: Current public-service GUI owner.
        body: Scrolling settings content.
        preferences: Protected authoritative revision displayed by the form.
        save: Revision-qualified mutation callback for this exact document.
    """
    body.add_widget(Label('Calls', role='peer'))

    def toggle() -> None:
        """Confirms widening Call acceptance without granting chat or message media."""
        change = partial(
            save,
            replace(
                preferences, accept_calls_locked=not preferences.accept_calls_locked
            ),
        )
        if preferences.accept_calls_locked:
            change()
        else:
            confirm(
                controller,
                'Accept calls without unlocking',
                'An explicit acceptance allows only that phone call. Chat stays locked. Select a microphone and audio output in audio settings.',
                change,
            )

    body.add_widget(
        SettingRow(
            'Accept calls without unlocking',
            'On' if preferences.accept_calls_locked else 'Off',
            'This profile · explicit acceptance of one exact call only',
            toggle,
            disabled=controller.state.busy
            or 'calls' not in controller.state.capabilities,
        )
    )
