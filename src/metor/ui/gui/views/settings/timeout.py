"""Protected idle-timeout editor with explicit disable warning and correlated save state."""

from dataclasses import replace

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.core.api import GuiPreferencesEvent
from metor.shared import Constants
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, TextField
from metor.ui.gui.widgets.sheet import ActionSheet


class TimeoutEditor(ActionSheet):
    """Preserves one displayed preference revision until save, cancel or explicit reload."""

    def __init__(self, controller: GuiController, current: GuiPreferencesEvent) -> None:
        """Captures the original protected document without sharing its mutable pin list.

        Args:
            controller: Authorized public preference owner.
            current: Actual preferences displayed when this editor opened.
        Returns:
            None
        """
        self.preferences = replace(
            current.preferences, pins=list(current.preferences.pins)
        )
        self.revision = current.preferences_revision
        self.field = TextField(
            text=str(self.preferences.idle_seconds),
            multiline=False,
            size_hint_y=None,
            height=dp(52),
        )
        self.feedback = Label('', role='support', tone='danger')
        self._disable_confirmed = False
        self._serial: int | None = None
        super().__init__(
            controller,
            self._content,
            title='Application timeout',
            primary=('Save', self._save),
            primary_tone='text',
            rebuild_on_snapshot=False,
            footer=Label(
                'This profile · protected GUI preference',
                role='support',
                tone='textSecondary',
            ),
        )
        self.field.bind(text=self._edited)
        self.bind(on_dismiss=self._clear)
        Clock.schedule_interval(self._poll, GuiLimits.UI_TICK_SECONDS)

    def _content(self, body: BoxLayout) -> None:
        """Shows the SDK-owned finite range and an explicit discard/readback action.

        Args:
            body: Native scroll column.
        Returns:
            None
        """
        body.add_widget(
            Label(
                'Lock after this many seconds without user activity. Enter 0 to disable automatic lock. Maximum: '
                + str(Constants.GUI_MAX_IDLE_SECONDS)
                + ' seconds.',
                role='support',
            )
        )
        body.add_widget(self.field)
        body.add_widget(self.feedback)
        body.add_widget(Action('Discard edit and reload', self._reload))

    def _edited(self, *_args: object) -> None:
        """Requires a fresh disable confirmation after any further input change.

        Args:
            _args: Native field update.
        Returns:
            None
        """
        self._disable_confirmed = False
        self.feedback.text = ''
        self._caption('Save')

    def _caption(self, text: str) -> None:
        """Updates the fixed primary label without rebuilding or losing input focus.

        Args:
            text: Exact current save/confirmation action.
        Returns:
            None
        """
        self.primary = (text, self._save)
        for action in self.actions.children:
            if isinstance(action, Action) and action is not self.cancel:
                action.label.text = text
                action.accessible_name = text
        self._resize()

    def _save(self) -> None:
        """Validates bounded input, warns once for disable and submits the captured revision.

        Args:
            None
        Returns:
            None
        """
        if self._serial is not None or self.controller.state.busy:
            return
        try:
            if len(self.field.text) > GuiLimits.SETTING_INPUT_CHARACTERS:
                raise ValueError('Input limit')
            proposed = replace(self.preferences, idle_seconds=int(self.field.text))
        except (ValueError, TypeError):
            self.feedback.text = (
                'Enter a whole number from 0 to '
                + str(Constants.GUI_MAX_IDLE_SECONDS)
                + '.'
            )
            return
        if proposed.idle_seconds == 0 and not self._disable_confirmed:
            self._disable_confirmed = True
            self.feedback.text = 'Metor will remain unlocked until you explicitly lock or close it. Confirm Disable lock to save this change.'
            self._caption('Disable lock')
            return
        if self.controller.preferences.save(proposed, self.revision):
            self._serial = self.controller.preferences.save_serial
            self.feedback.text = 'Saving'
        else:
            self.feedback.text = (
                self.controller.preferences.last_error
                or 'Save is unavailable. Recheck current preferences.'
            )

    def _reload(self) -> None:
        """Discards only this explicit edit and requests fresh public preferences.

        Args:
            None
        Returns:
            None
        """
        if self._serial is None and not self.controller.state.busy:
            self.controller.preferences.refresh_needed = True
            self.dismiss(animation=False)

    def _poll(self, _elapsed: float) -> None:
        """Closes only on this save's positive result; rejection preserves the input.

        Args:
            _elapsed: Native UI tick.
        Returns:
            None
        """
        bridge = self.controller.preferences
        if self._serial is not None and bridge.save_serial == self._serial:
            if bridge.save_state == 'saved':
                self.dismiss(animation=False)
                return
            if bridge.save_state in {'rejected', 'unknown'}:
                self._serial = None
                self.feedback.text = bridge.last_error
        self.field.readonly = self._serial is not None
        for action in self.actions.children:
            if isinstance(action, Action) and action is not self.cancel:
                action.disabled = self.controller.state.busy or self._serial is not None

    def _clear(self, *_args: object) -> None:
        """Releases editor callbacks and text on explicit dismissal or privacy cover.

        Args:
            _args: Native dismissal event.
        Returns:
            None
        """
        Clock.unschedule(self._poll)
        self.field.unbind(text=self._edited)
        self.field.text = ''
