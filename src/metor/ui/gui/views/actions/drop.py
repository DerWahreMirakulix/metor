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
    confirm(
        controller,
        'Clear all Drops' if peer is None else 'Delete conversation',
        'Delete local Drops and their history'
        + (' for this conversation' if peer else '')
        + '. Pending delivery is preserved. Saved contacts, Live and unsent voice reviews remain.',
        lambda: controller.drop.clear(peer),
    )
