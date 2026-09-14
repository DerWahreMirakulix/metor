"""New-DROP resend controls for one captured delivered-own-LIVE source."""

from kivy.uix.boxlayout import BoxLayout

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label


def resend_controls(
    body: BoxLayout, controller: GuiController, peer: str, msg_id: str
) -> None:
    """Shows complete-source eligibility and exact new-ID recovery without another send intent.

    Args:
        body: Current contextual menu column.
        controller: Current authorized operation owner.
        peer: Captured original peer and destination.
        msg_id: Captured original delivered LIVE identity.
    Returns:
        None
    """
    actions = controller.resend
    current = actions.current
    if current is not None:
        same = (
            current.source.target.peer == peer
            and current.source.target.msg_id == msg_id
        )
        if not same:
            body.add_widget(Label('Resolve the current resend first', role='support'))
            return
        body.add_widget(Label(actions.status, role='support'))
        if actions.pending:
            body.add_widget(Action('Stop copying', actions.cancel))
        else:
            body.add_widget(
                Action(
                    'Check result',
                    actions.check,
                    disabled=controller.state.busy
                    or 'message_outcome' not in controller.state.capabilities,
                )
            )
            if actions.state == 'draft':
                body.add_widget(
                    Action(
                        'Discard unsent copy',
                        actions.discard,
                        tone='danger',
                        disabled=controller.state.busy,
                    )
                )
        return
    available = actions.available(peer, msg_id)
    body.add_widget(
        Action(
            'Resend as Drop',
            lambda: actions.start(peer, msg_id),
            disabled=not available or controller.state.busy or controller.voice.running,
        )
    )
    body.add_widget(
        Label(
            'Creates a new Drop'
            if available
            else 'Complete source no longer available',
            role='support',
        )
    )


def resend_revision(controller: GuiController, peer: str, msg_id: str) -> object:
    """Returns a content-free key so eviction and unknown results update an open menu.

    Args:
        controller: Current authorized operation owner.
        peer: Original source peer.
        msg_id: Original source identity.
    Returns:
        object: Finite local eligibility value; no source bytes or passwords.
    """
    return (
        controller.resend.revision,
        controller.resend.available(peer, msg_id),
        controller.state.busy,
        controller.voice.running,
    )
