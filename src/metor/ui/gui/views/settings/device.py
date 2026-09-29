"""Standard controls for confirmed local hardware setting values."""

from collections.abc import Callable
from functools import partial
import math
from typing import cast

from kivy.uix.boxlayout import BoxLayout

from metor.client.platform import (
    DeviceSettingDescriptor,
    DeviceSettingKind,
    DeviceSettingResult,
    DeviceSettingStatus,
    DeviceSettingValue,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, SettingRow, TextField
from metor.ui.gui.widgets.sheet import ActionSheet


def _value_text(
    descriptor: DeviceSettingDescriptor, result: DeviceSettingResult | None
) -> str:
    """Show only confirmed effective values, otherwise an honest outcome."""
    if result is None:
        return 'Unknown'
    if result.status is not DeviceSettingStatus.APPLIED:
        return cast(str, result.status.value).capitalize()
    value = result.value
    if descriptor.kind is DeviceSettingKind.BOOLEAN:
        return 'On' if value is True else 'Off'
    if descriptor.unit:
        return f'{value} {descriptor.unit}'
    return str(value)


class DeviceSettingEditor(ActionSheet):
    """Edit one local ordinary setting without using profile authorization state."""

    def __init__(
        self,
        controller: GuiController,
        descriptor: DeviceSettingDescriptor,
        result: DeviceSettingResult | None,
    ) -> None:
        """Create finite boolean, number or choice controls from one descriptor."""
        self._descriptor = descriptor
        self._selected: DeviceSettingValue | None = (
            result.value
            if result is not None and result.status is DeviceSettingStatus.APPLIED
            else None
        )
        self._field = TextField(
            text=str(self._selected) if self._selected is not None else '',
            multiline=False,
            size_hint_y=None,
            height='52dp',
        )
        self._feedback = Label('', role='support', tone='danger')
        self._boolean_action: Action | None = None
        self._choice_actions: dict[str, Action] = {}
        super().__init__(
            controller,
            self._content,
            title=descriptor.name,
            primary=('Apply', self._apply),
            rebuild_on_snapshot=False,
            primary_tone='text',
        )

    def _content(self, body: BoxLayout) -> None:
        """Render descriptor bounds and one matching standard input control."""
        descriptor = self._descriptor
        body.add_widget(
            Label('This device · shared across local frontends', role='support')
        )
        if descriptor.kind is DeviceSettingKind.BOOLEAN:
            self._boolean_action = Action(
                'On' if self._selected is True else 'Off',
                self._toggle,
            )
            body.add_widget(self._boolean_action)
        elif descriptor.kind is DeviceSettingKind.CHOICE:
            self._choice_actions = {}
            for choice in descriptor.choices:
                action = Action(
                    ('✓ ' if choice == self._selected else '') + choice,
                    partial(self._choose, choice),
                )
                self._choice_actions[choice] = action
                body.add_widget(action)
        else:
            body.add_widget(
                Label(
                    f'Allowed: {descriptor.minimum} to {descriptor.maximum}'
                    + (f' {descriptor.unit}' if descriptor.unit else ''),
                    role='support',
                )
            )
            body.add_widget(self._field)
        body.add_widget(self._feedback)

    def _toggle(self) -> None:
        """Change the proposed boolean only until explicit Apply."""
        self._selected = self._selected is not True
        action = self._boolean_action
        if action is not None:
            action.label.text = 'On' if self._selected else 'Off'
            action.accessible_name = action.label.text

    def _choose(self, choice: str) -> None:
        """Choose only one declared finite option."""
        self._selected = choice
        for candidate, action in self._choice_actions.items():
            action.label.text = ('✓ ' if candidate == choice else '') + candidate
            action.accessible_name = action.label.text

    def _apply(self) -> None:
        """Submit typed input asynchronously and retain uncertainty in the row."""
        value = self._selected
        descriptor = self._descriptor
        if descriptor.kind is DeviceSettingKind.NUMBER:
            raw = self._field.text.strip()
            if len(raw) > GuiLimits.SETTING_INPUT_CHARACTERS:
                self._feedback.text = 'Enter a supported value'
                return
            try:
                value = float(raw) if any(mark in raw for mark in '.eE') else int(raw)
            except ValueError:
                self._feedback.text = 'Enter a number in the allowed range'
                return
            if not math.isfinite(value):
                self._feedback.text = 'Enter a finite number'
                return
        if value is None or not descriptor.accepts(value):
            self._feedback.text = 'Enter a supported value'
            return
        if self.controller.device.settings.write(descriptor.key, value):
            self.dismiss(animation=False)
        else:
            self._feedback.text = self.controller.device.settings.feedback


def device_settings_group(
    controller: GuiController, body: BoxLayout, refresh: Callable[[], None]
) -> None:
    """Show selected adapter settings with confirmed readback and explicit reload."""
    settings = controller.device.settings
    if not settings.available:
        return
    body.add_widget(Label('Hardware settings', role='peer'))
    if not settings.loaded:
        body.add_widget(Label('Loading device settings…', role='support'))
        settings.refresh()
    for descriptor in settings.descriptors:
        result = settings.values.get(descriptor.key)

        def open_editor(
            selected: DeviceSettingDescriptor = descriptor,
            current: DeviceSettingResult | None = result,
        ) -> None:
            """Open the captured local descriptor without mutating it."""
            DeviceSettingEditor(controller, selected, current).show()
            refresh()

        body.add_widget(
            SettingRow(
                descriptor.name,
                _value_text(descriptor, result),
                'This device · current effective value',
                open_editor,
                disabled=not descriptor.writable or settings.pending,
            )
        )
    if settings.feedback:
        body.add_widget(Label(settings.feedback, role='support', tone='info'))
    body.add_widget(
        Action('Reload device settings', settings.refresh, disabled=settings.pending)
    )
