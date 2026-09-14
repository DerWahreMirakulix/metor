"""Stable setting-key editor preserving input across asynchronous Core snapshots."""

from dataclasses import replace
import math

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.core.api import SettingSnapshotEntry
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, TextField
from metor.ui.gui.widgets.sheet import ActionSheet


class SettingEditor(ActionSheet):
    """Keeps a displayed expectation until explicit reload or confirmed save."""

    def __init__(self, controller: GuiController, entry: SettingSnapshotEntry) -> None:
        """Builds an immutable-key profile override editor from a public descriptor.

        Args:
            controller: Current authorized GUI.
            entry: Original descriptor and effective value.
        Returns:
            None
        """
        self.entry = replace(entry)
        self.operation: str | None = None
        self._reload_revision: int | None = None
        self.proposed_bool = entry.value == 'True'
        self.field = TextField(
            text=entry.value,
            multiline=False,
            size_hint_y=None,
            height=dp(52),
        )
        self.feedback = Label('', role='support', tone='danger')
        self.scope_label = Label('', role='support', tone='textSecondary')
        self.boolean = Action('', self._toggle)
        self.reload_action = Action('Reload current value', self._reload)
        super().__init__(
            controller,
            self._content,
            title=entry.display_name,
            primary=('Save', self._save),
            rebuild_on_snapshot=False,
            primary_tone='text',
            footer=self.scope_label,
        )
        self.bind(on_dismiss=self._clear_input)
        Clock.schedule_interval(self._poll, GuiLimits.UI_TICK_SECONDS)

    def _content(self, body: BoxLayout) -> None:
        """Presents exact meaning, scope, constraints and any policy warning before Save.

        Args:
            body: Shared measured scrolling sheet body.
        Returns:
            None
        """
        self._scope()
        body.add_widget(Label(self.entry.description, role='support'))
        body.add_widget(Label(self.entry.constraints, role='support'))
        if self.entry.security_note:
            body.add_widget(
                Label(self.entry.security_note, role='support', tone='info')
            )
        if self.entry.value_type == 'bool':
            self.boolean.label.text = 'On' if self.proposed_bool else 'Off'
            body.add_widget(self.boolean)
        else:
            body.add_widget(self.field)
        body.add_widget(self.feedback)
        body.add_widget(self.reload_action)

    def _scope(self) -> None:
        """Shows actual effective source while keeping the mutation profile-local.

        Args:
            None
        Returns:
            None
        """
        self.scope_label.text = (
            'Profile override · current source: '
            + (
                'profile override'
                if self.entry.source == 'profile_override'
                else self.entry.source
            )
            + '.'
        )

    def _toggle(self) -> None:
        """Changes only proposed input until the explicit Save action.

        Args:
            None
        Returns:
            None
        """
        if self.operation is None:
            self.proposed_bool = not self.proposed_bool
            self.boolean.label.text = 'On' if self.proposed_bool else 'Off'

    def _value(self) -> str | int | float | bool:
        """Parses a finite user value using the descriptor's declared primitive type.

        Args:
            None
        Returns:
            str | int | float | bool: Proposed value for independent Core validation.
        """
        if self.entry.value_type == 'bool':
            return self.proposed_bool
        raw = self.field.text.strip()
        if len(raw) > GuiLimits.SETTING_INPUT_CHARACTERS:
            raise ValueError('Value is too long')
        if self.entry.value_type not in {'int', 'float'}:
            raise ValueError('Unsupported setting type')
        value = int(raw) if self.entry.value_type == 'int' else float(raw)
        if not math.isfinite(value):
            raise ValueError('Enter a finite number')
        if self.entry.min_value is not None and value < self.entry.min_value:
            raise ValueError(self.entry.constraints)
        if self.entry.max_value is not None and value > self.entry.max_value:
            raise ValueError(self.entry.constraints)
        return value

    def _save(self) -> None:
        """Admits one typed save without dismissing rejected or uncertain input.

        Args:
            None
        Returns:
            None
        """
        if self.operation is not None:
            return
        try:
            value = self._value()
        except (ValueError, OverflowError):
            self.feedback.text = 'Enter a supported value. ' + self.entry.constraints
            return
        self.operation = self.controller.core_settings.save(self.entry, value)
        if self.operation is not None:
            self.feedback.text = 'Saving profile setting…'

    def _reload(self) -> None:
        """Explicitly replaces stale input with a fresh descriptor value.

        Args:
            None
        Returns:
            None
        """
        settings = self.controller.core_settings
        self._reload_revision = settings.revision
        settings.reload()
        self.feedback.text = 'Reading current value…'

    def _poll(self, _elapsed: float) -> bool:
        """Displays the correlated outcome while preserving native focus on failure.

        Args:
            _elapsed: Native scheduler interval.
        Returns:
            bool: Whether this visible editor still needs observation.
        """
        if ActionSheet.current is not self:
            return False
        settings = self.controller.core_settings
        if (
            self._reload_revision is not None
            and settings.revision != self._reload_revision
            and not self.controller.state.busy
            and not settings.refresh_needed
        ):
            self._reload_revision = None
            current = next(
                (row for row in settings.entries if row.key == self.entry.key), None
            )
            if current is not None and settings.last_read_success:
                self.entry = replace(current)
                self.field.text = current.value
                self.proposed_bool = current.value == 'True'
                self.boolean.label.text = 'On' if self.proposed_bool else 'Off'
                self.feedback.text = ''
                self._scope()
            else:
                self.feedback.text = settings.error
        if (
            self.operation is not None
            and settings.completed_operation == self.operation
        ):
            self.operation = None
            if settings.completed_success:
                self.dismiss(animation=False)
                return False
            self.feedback.text = settings.error
        self.reload_action.disabled = (
            self.operation is not None
            or self._reload_revision is not None
            or self.controller.state.busy
        )
        for action in self.actions.children:
            if action is not self.cancel:
                action.disabled = (
                    self.operation is not None
                    or self._reload_revision is not None
                    or self.controller.state.busy
                    or settings.pending is not None
                )
        return True

    def _clear_input(self, *_args: object) -> None:
        """Releases abandoned private input when authorization or the sheet ends.

        Args:
            _args: Native dismissal notification.
        Returns:
            None
        """
        self.field.text = ''
