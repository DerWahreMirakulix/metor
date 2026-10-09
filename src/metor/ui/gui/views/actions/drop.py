"""Explicit local DROP confirmation shared by root, peer and Privacy entry points."""

from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets.sheet import confirm


def clear_drops(controller: GuiController, peer: str | None) -> None:
    """Shows the approved local scope before any DROP clear request.

    Args:
        controller: Current authorized GUI action owner.
        peer: Exact peer, or None for the explicit all-DROP Privacy action.
    Returns:
        None
    """
    if not controller.drop.can_clear(peer):
        controller.state.status = (
            'Update Core to cancel queued Drops when deleting.'
            if 'drop_pending_cancellation' not in controller.state.capabilities
            else 'Wait until the send result is confirmed before deleting.'
        )
        return
    confirm(
        controller,
        'Clear all Drops' if peer is None else 'Delete conversation',
        'Delete local Drops and their history'
        + (' for this conversation' if peer else '')
        + (
            '. Queued Drops will be cancelled. A copy already transmitted may still arrive.'
            if peer is not None
            else '. Pending delivery is preserved.'
        )
        + ' Saved contacts, Live, text drafts and unsent voice reviews remain.',
        lambda: controller.drop.clear(peer),
    )
