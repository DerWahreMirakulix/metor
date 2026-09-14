"""Direction-qualified message menus with current eligibility and separate confirmation."""

from collections.abc import Callable

from kivy.uix.boxlayout import BoxLayout

from metor.core.api import Delivery, MessageDirectionCode, MessageStatusCode
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.state import Route
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import ActionSheet, confirm

# Local Package Imports
from .resend import resend_controls, resend_revision


def message_menu(
    controller: GuiController,
    route: Route,
    direction: MessageDirectionCode,
    msg_id: str,
    lookup: Callable[[], MessageStatusCode | None],
) -> None:
    """Captures a complete displayed identity and rechecks its current presentation.

    Args:
        controller: Authorized GUI action owner.
        route: Original peer and projection, independent of later navigation.
        direction: Exact displayed inbound/outbound identity qualifier.
        msg_id: Stable displayed message identity.
        lookup: Current same-identity presentation status; None means unavailable.
    Returns:
        None
    """

    def build(body: BoxLayout) -> None:
        """Updates eligibility without substituting another message or confirming on arrival.

        Args:
            body: Scrolling contextual menu body.
        Returns:
            None
        """
        status = lookup()
        if status is None:
            body.add_widget(Label('Item no longer available'))
            return
        if route.delivery is Delivery.DROP:
            pending = (
                direction is MessageDirectionCode.OUT
                and status is MessageStatusCode.PENDING
            )

            def delete() -> None:
                """Requires an explicit local-only confirmation for this captured item.

                Args:
                    None
                Returns:
                    None
                """
                sheet.dismiss(animation=False)
                confirm(
                    controller,
                    'Delete Drop',
                    'Delete this Drop from local history. This does not delete the remote copy or cancel pending delivery.',
                    lambda: controller.drop.delete(route.peer or '', msg_id, direction),
                )

            body.add_widget(
                Action(
                    'Delete Drop',
                    delete,
                    tone='danger',
                    disabled=pending
                    or controller.state.busy
                    or controller.drop.pending is not None,
                )
            )
            if pending:
                body.add_widget(Label('Pending delivery is preserved', role='support'))

        elif (
            direction is MessageDirectionCode.OUT
            and status is MessageStatusCode.PENDING
        ):

            def fallback() -> None:
                """Converts this own pending item using the existing message identity.

                Args:
                    None
                Returns:
                    None
                """
                sheet.dismiss(animation=False)
                controller.live.fallback(route.peer or '', (msg_id,))

            body.add_widget(
                Action(
                    'Send as Drop',
                    fallback,
                    disabled=controller.state.busy
                    or controller.live.pending is not None,
                )
            )
        elif (
            route.delivery is Delivery.LIVE
            and direction is MessageDirectionCode.OUT
            and status in {MessageStatusCode.DELIVERED, MessageStatusCode.READ}
        ):
            resend_controls(body, controller, route.peer or '', msg_id)

    sheet = ActionSheet(
        controller,
        build,
        title='Message actions',
        compact_menu=True,
        revision=lambda: (
            lookup(),
            resend_revision(controller, route.peer or '', msg_id),
        ),
    )
    sheet.show()
