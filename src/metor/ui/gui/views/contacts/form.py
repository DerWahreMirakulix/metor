"""Bounded nonsecret contact editing with preserved save/open/start intent."""

from collections.abc import Callable
from functools import partial

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label, TextField


def contact_form(
    controller: GuiController, body: BoxLayout, refresh: Callable[[], None]
) -> None:
    """Builds a saved form without copying remote aliases into local consent.

    Args:
        controller: Contact-operation and current authorization owner.
        body: Measured scroll content.
        refresh: Native repaint callback.
    Returns:
        None
    """
    form = controller.contacts.form
    if form is None:
        body.add_widget(Label('Choose Add contact to begin', tone='textSecondary'))
        return
    title = {
        'save': 'Save contact',
        'drop': 'Save & Open Drop',
        'live': 'Save & Start Live',
        'rename': 'Rename',
    }[form.intent]
    body.add_widget(Label('Contact address or QR data', role='support'))
    raw = TextField(
        text=form.raw, readonly=form.fixed, size_hint_y=None, height=dp(104)
    )
    raw.use_bubble = raw.use_handles = False
    body.add_widget(raw)
    body.add_widget(Label('Local alias', role='support'))
    alias = TextField(text=form.alias, multiline=False, size_hint_y=None, height=dp(52))
    body.add_widget(alias)

    def edit(field: str, widget: TextField, value: str) -> None:
        """Copies a bounded field value into the pending contact form.

        Args:
            field (str): The field input.
            widget (TextField): The widget input.
            value (str): The value input.

        Returns:
            None
        """
        if len(value.encode('utf-8')) <= GuiLimits.CONTACT_BYTES:
            setattr(form, field, value)
        else:
            widget.text = getattr(form, field)

    raw.bind(text=partial(edit, 'raw'))
    alias.bind(text=partial(edit, 'alias'))

    def submit(recheck: bool = False) -> None:
        """Runs the selected contact action and refreshes its presentation.

        Args:
            recheck (bool): The recheck input.

        Returns:
            None
        """
        if recheck:
            controller.contacts.recheck()
        else:
            controller.contacts.save()
        refresh()

    if form.error:
        body.add_widget(Label(form.error, role='support', tone='danger'))
    body.add_widget(
        Action(
            title,
            submit,
            surface='drop' if form.intent != 'live' else 'live',
            tone='onAccent',
            disabled=controller.state.busy or form.unknown,
        )
    )
    if form.unknown:
        body.add_widget(
            Action(
                'Recheck result',
                partial(submit, True),
                disabled=controller.state.busy,
            )
        )
    if not form.fixed:
        body.add_widget(
            Label(
                'Camera unavailable. Manual entry uses the same contact validation.',
                role='support',
                tone='textSecondary',
            )
        )
