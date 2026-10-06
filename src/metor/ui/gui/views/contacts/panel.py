"""Native saved-contact browsing and intent-labelled add/picker surfaces."""

from collections.abc import Callable
from functools import partial

from kivy.core.clipboard import Clipboard
from kivy.core.clipboard.clipboard_dummy import ClipboardDummy
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from metor.core.api import Delivery
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.qr import ContactQr
from metor.ui.gui.widgets.sheet import ActionSheet, confirm

from ..audio import show_audio_unavailable

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
        """Builds the selected contact action sheet.

        Args:
            body (BoxLayout): The body input.

        Returns:
            None
        """
        body.add_widget(Label(peer, role='support', tone='textSecondary'))

        def selected(delivery: Delivery) -> None:
            """Applies the explicitly selected delivery mode to this peer.

            Args:
                delivery (Delivery): The delivery input.

            Returns:
                None
            """
            sheet.dismiss(animation=False)
            controller.contacts.select(
                peer, 'live' if delivery is Delivery.LIVE else 'drop'
            )
            refresh()

        def call() -> None:
            """Starts an explicit phone call while preserving the invoking route."""
            sheet.dismiss(animation=False)
            if not controller.calls.ready:
                show_audio_unavailable(controller, refresh, purpose='calls')
                return
            controller.calls.start(peer)
            refresh()

        body.add_widget(
            Action(
                'Call',
                call,
                disabled=controller.state.busy
                or 'calls' not in controller.state.capabilities,
            )
        )
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
            """Opens the rename form for this immutable peer identity.

            Args:
                None

            Returns:
                None
            """
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
            own_address = snapshot.onion
            generation = controller.state.generation
            qr_available = False
            try:
                body.add_widget(ContactQr(own_address))
                qr_available = True
            except ValueError:
                body.add_widget(Label('Contact QR unavailable', tone='textSecondary'))
            body.add_widget(Widget(size_hint_y=None, height=dp(8)))
            address = Label(own_address, role='support')
            address.halign = 'center'
            body.add_widget(address)
            if controller.clipboard_own_address and qr_available:

                def copy_address() -> None:
                    """Exports only the still-visible current public identity on request."""
                    current = controller.state
                    if (
                        current.covered
                        or current.generation != generation
                        or current.route.view != 'V15'
                        or current.snapshot is None
                        or current.snapshot.onion != own_address
                    ):
                        return
                    try:
                        Clipboard.copy(own_address)
                        copied = Clipboard.paste() == own_address
                    except Exception:  # noqa: BLE001 - isolate optional clipboard providers
                        copied = False
                    status = 'Address copied' if copied else 'Copy unavailable'
                    copy_action.label.text = status
                    copy_action.accessible_name = status

                clipboard_unavailable = isinstance(Clipboard, ClipboardDummy)
                copy_action = Action(
                    'Copy unavailable' if clipboard_unavailable else 'Copy address',
                    copy_address,
                    disabled=clipboard_unavailable,
                )
                body.add_widget(copy_action)
        else:
            body.add_widget(Label('Contact identity unavailable', tone='textSecondary'))
            body.add_widget(Action('Retry', controller.refresh_state))
        return
