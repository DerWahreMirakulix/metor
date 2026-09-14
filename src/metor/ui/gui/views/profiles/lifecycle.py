"""Minimal covered lifecycle progress and desktop close's single consequence confirmation."""

from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import confirm


def request_exit(controller: GuiController) -> None:
    """Requests GUI-only close; idle close adds no confirmation or global runtime exit.

    Args:
        controller: Current native GUI lifecycle owner.
    Returns:
        None
    """
    state, lifecycle = controller.state, controller.lifecycle
    if lifecycle.active or lifecycle.failed or lifecycle.exit_ready:
        return
    if state.busy:
        state.status = 'Finish or cancel the current operation before closing Metor.'
        return
    if not state.covered and (state.drafts or controller.voice.reviews):
        confirm(
            controller,
            'Exit Metor',
            'This GUI’s unsent text drafts and uncommitted Drop recordings will be discarded. '
            'Authorized active recording is finalized locally. Queued messages and other clients’ Live activity remain managed by Metor.',
            lifecycle.start,
        )
    else:
        lifecycle.start()


def lifecycle_body(controller: GuiController, body: BoxLayout) -> None:
    """Shows actual transition progress without exposing old-profile private content.

    Args:
        controller: Actual lifecycle phase owner.
        body: Native full-cover content column.
    Returns:
        None
    """
    lifecycle = controller.lifecycle
    body.add_widget(
        Label(
            'Closing Metor' if lifecycle.exit_requested else 'Switching profile',
            role='peer',
        )
    )
    if lifecycle.failed:
        if lifecycle.return_available:
            body.add_widget(
                Action('Return to current profile', lifecycle.return_to_source)
            )
        body.add_widget(Action('Choose profile', lifecycle.choose_profile))
        if lifecycle.exit_requested and lifecycle.owner_loss_supported:
            body.add_widget(
                Label(
                    'Exit anyway uses Metor’s protected recovery for accepted audio. Recording preservation could not be confirmed here.',
                    role='support',
                )
            )
            body.add_widget(Action('Exit anyway', lifecycle.exit_anyway, tone='danger'))
    else:
        body.add_widget(Label(lifecycle.phase, role='support', tone='textSecondary'))
