"""Native saved-contact browsing and intent-labelled add/picker surfaces."""

from collections.abc import Callable
from functools import partial

from kivy.uix.boxlayout import BoxLayout

from metor.core.api import Delivery
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.qr import ContactQr
from metor.ui.gui.widgets.sheet import ActionSheet, confirm

# Local Package Imports
from .form import contact_form


def contact_sheet(
    controller: GuiController, peer: str, refresh: Callable[[], None]
) -> None:
    """Opens labelled actions for one immutable peer without placing an implicit call.

    Args:
        controller: Current public-service coordinator.
        peer: Stable selected peer identity.
        refresh: Native repaint callback.
    Returns:
        None
    """

    def build(body: BoxLayout) -> None:
        body.add_widget(Label(peer, role='support', tone='textSecondary'))

        def selected(delivery: Delivery) -> None:
            sheet.dismiss(animation=False)
            controller.contacts.select(
                peer, 'live' if delivery is Delivery.LIVE else 'drop'
            )
            refresh()

        body.add_widget(Action('Open Drop', partial(selected, Delivery.DROP)))
        body.add_widget(
            Action(
                'Open active Live'
                if controller.contacts.active(peer)
                else 'Start Live',
                partial(selected, Delivery.LIVE),
            )
        )

        def rename() -> None:
            sheet.dismiss(animation=False)
            controller.contacts.begin('rename', peer)
            refresh()

        body.add_widget(Action('Rename', rename))
        body.add_widget(
            Action(
                'Remove contact',
                lambda: confirm(
                    controller,
                    'Remove contact',
                    'Remove this saved contact. Retained conversations and active communication may remain.',
                    lambda: controller.contacts.remove(peer),
                ),
                tone='danger',
            )
        )

    sheet = ActionSheet(
        controller, build, title=lambda: controller.contacts.alias(peer)
    )
    sheet.show()


def contacts_body(
    controller: GuiController, body: BoxLayout, refresh: Callable[[], None]
) -> None:
    """Builds current saved contacts, contact forms, or a real supported own QR.

    Args:
        controller: Current public-service coordinator.
        body: Measured scrolling parent.
        refresh: Coalesced native repaint callback.
    Returns:
        None
    """

    def enter_manual() -> None:
        """Keeps the scanner's original save/open/start intent and caller return route.

        Args:
            None
        Returns:
            None
        """
        controller.contacts.manual()
        refresh()

    route, snapshot = controller.state.route, controller.state.snapshot
    if route.view == 'V13':
        contact_form(controller, body, refresh)
        return
    if route.view == 'V14':
        body.add_widget(Label('Camera unavailable', role='peer'))
        body.add_widget(
            Label(
                'Enter an address or supported QR contact data manually.',
                tone='textSecondary',
            )
        )
        body.add_widget(
            Action(
                'Enter contact data',
                enter_manual,
            )
        )
        return
    if route.view == 'V15':
        if snapshot and snapshot.onion:
            try:
                body.add_widget(ContactQr(snapshot.onion))
            except ValueError:
                body.add_widget(Label('Contact QR unavailable', tone='textSecondary'))
            body.add_widget(Label(snapshot.onion, role='support'))
        else:
            body.add_widget(Label('Contact identity unavailable', tone='textSecondary'))
            body.add_widget(Action('Retry', controller.refresh_state))
        return
