"""Canonical root conversation menus independent of mutable displayed aliases."""

from collections.abc import Callable
from kivy.uix.boxlayout import BoxLayout
from metor.core.api import Delivery
from metor.ui.gui.runtime import GuiController, conversation_rows
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet

# Local Package Imports
from ..actions import clear_drops, live_context_actions


def conversation_menu(
    controller: GuiController,
    peer: str,
    delivery: Delivery,
    refresh: Callable[[], None],
) -> None:
    """Uses a stable canonical identity for More, right-click and hold actions.

    Args:
        controller: Public state and action owner.
        peer: Originally displayed canonical peer identity.
        delivery: Originally displayed projection.
        refresh: Native repaint request.
    Returns:
        None
    """

    def build(body: BoxLayout) -> None:
        """Resolves current eligibility and labels each time canonical state changes.

        Args:
            body: Scrolling native menu body.
        Returns:
            None
        """
        current = next(
            (
                row
                for row in conversation_rows(controller, delivery)
                if row.peer == peer
            ),
            None,
        )
        if current is None:
            body.add_widget(Label('Conversation no longer available'))
            return

        def pin() -> None:
            """Applies a protected pin change only to the displayed DROP identity.

            Args:
                None
            Returns:
                None
            """
            sheet.dismiss(animation=False)
            controller.preferences.pin(peer)
            refresh()

        def delete() -> None:
            """Moves from More to a separate local DROP confirmation.

            Args:
                None
            Returns:
                None
            """
            sheet.dismiss(animation=False)
            clear_drops(controller, peer)

        if delivery is Delivery.DROP:
            body.add_widget(
                Action(
                    'Unpin' if current.pinned else 'Pin',
                    pin,
                    disabled=controller.state.busy
                    or controller.state.preferences is None,
                )
            )
            body.add_widget(
                Action(
                    'Delete conversation',
                    delete,
                    tone='danger',
                    disabled=controller.state.busy
                    or controller.drop.pending is not None,
                )
            )
        else:

            def open_live() -> None:
                """Navigates to the existing peer without initiating a call.

                Args:
                    None
                Returns:
                    None
                """
                sheet.dismiss(animation=False)
                controller.navigate(Route('V09', peer, Delivery.LIVE))
                refresh()

            body.add_widget(Action('Open Live', open_live))
            live_context_actions(
                controller, peer, body, lambda: sheet.dismiss(animation=False)
            )
        snapshot = controller.state.snapshot
        saved = snapshot is not None and any(
            contact.onion == peer and contact.saved for contact in snapshot.contacts
        )
        if not saved:

            def save_contact() -> None:
                """Opens Save-only contact promotion without changing communication state.

                Args:
                    None
                Returns:
                    None
                """
                sheet.dismiss(animation=False)
                controller.contacts.begin('save', peer)
                refresh()

            body.add_widget(
                Action('Save contact', save_contact, disabled=controller.state.busy)
            )

    sheet = ActionSheet(
        controller,
        build,
        title=lambda: controller.contacts.alias(peer),
        compact_menu=True,
    )
    sheet.show()
