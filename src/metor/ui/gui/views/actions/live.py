"""Explicit pending fallback and ended-context dismissal in root and peer menus."""

from collections.abc import Callable

from kivy.uix.boxlayout import BoxLayout

from metor.core.api import Delivery
from metor.ui.gui.runtime import GuiController
from metor.ui.gui.widgets import Action, Label
from metor.ui.gui.widgets.sheet import confirm


def live_context_actions(
    controller: GuiController,
    peer: str,
    body: BoxLayout,
    dismiss: Callable[[], None],
    refresh: Callable[[], None],
    *,
    primary_controls: bool = True,
) -> None:
    """Builds current-state actions while preserving the originally selected peer.

    Args:
        controller: Authorized GUI action owner.
        peer: Immutable canonical target.
        body: Native scrolling menu body.
        dismiss: Closes the existing menu before another explicit interaction.
        refresh: Presents admitted action state before any asynchronous result.
        primary_controls: Includes connection controls only when no header owns them.
    Returns:
        None
    """
    snapshot = controller.state.snapshot
    entry = (
        next((item for item in snapshot.live_contexts if item.onion == peer), None)
        if snapshot
        else None
    )
    pending = entry.pending_outbound_count if entry else 0
    busy = (
        controller.state.busy
        or controller.live.pending is not None
        or bool(controller.live.stop_status(peer))
    )

    def end() -> None:
        """Ends only the originally displayed logical context or calling attempt.

        Args:
            None
        Returns:
            None
        """
        dismiss()
        if entry is not None:
            controller.live.end(
                peer,
                None
                if entry.outbound_attempt_id and not entry.recovery_eligible
                else entry.context_generation,
                entry.outbound_attempt_id if not entry.recovery_eligible else None,
            )
        refresh()

    def reconnect() -> None:
        """Starts an explicit reconnect and never runs merely because the menu opened.

        Args:
            None
        Returns:
            None
        """
        dismiss()
        controller.live.start(peer)
        refresh()

    active = bool(
        entry and (entry.session_state == 'connected' or entry.recovery_eligible)
    )
    calling = bool(entry and entry.outbound_attempt_id and not active)
    if primary_controls and (active or calling):
        body.add_widget(
            Action(
                'Cancel Live' if calling else 'End Live',
                end,
                tone='danger',
                disabled=busy
                or 'qualified_live_control' not in controller.state.capabilities,
            )
        )

    def change_route() -> None:
        """Changes the exact displayed active route through qualified Core admission.

        Args:
            None
        Returns:
            None
        """
        dismiss()
        if entry is not None and entry.context_generation is not None:
            controller.live.change_route(peer, entry.context_generation)
        refresh()

    if entry is not None and entry.session_state == 'connected':
        body.add_widget(
            Action(
                'Changing route…' if entry.route_changing else 'Change route',
                change_route,
                disabled=busy
                or entry.route_changing
                or entry.context_generation is None
                or 'qualified_live_retunnel' not in controller.state.capabilities,
            )
        )

    def fallback() -> None:
        """Requests Core-eligible bulk fallback without changing logical message IDs.

        Args:
            None
        Returns:
            None
        """
        dismiss()
        controller.live.fallback(peer)
        refresh()

    def close() -> None:
        """Explains local destruction of unseen content before a Core dismissal.

        Args:
            None
        Returns:
            None
        """
        dismiss()
        if (
            entry is not None
            and entry.unseen_count
            or controller.state.drafts.get((peer, Delivery.LIVE))
        ):
            confirm(
                controller,
                'Remove Live conversation',
                'Remove this ended Live conversation, its unread items, transcript and unsent text draft. Drops and saved contacts remain.',
                lambda: controller.live.close_context(peer),
            )
        else:
            controller.live.close_context(peer)
            refresh()

    if pending:
        body.add_widget(Action('Send pending as Drop', fallback, disabled=busy))
        body.add_widget(
            Label(
                'Complete pending items only. Ongoing recordings remain in Live.',
                role='support',
            )
        )
    ended = (
        entry is None
        or entry.session_state == 'disconnected'
        and not entry.recovery_eligible
    )
    retained = (
        entry is not None
        or any(
            item.peer == peer and item.delivery is Delivery.LIVE
            for item in controller.transcript.items.values()
        )
        or bool(controller.state.drafts.get((peer, Delivery.LIVE)))
    )
    if controller.live.idle(peer) and retained and primary_controls:
        body.add_widget(
            Action(
                'Reconnect Live',
                reconnect,
                disabled=busy or not controller.live.retry_ready(peer),
            )
        )
    if ended and retained:
        body.add_widget(
            Action(
                'Remove Live conversation',
                close,
                tone='danger',
                disabled=busy or bool(pending),
            )
        )
        if pending:
            body.add_widget(
                Label(
                    'Reconnect or send pending items as Drops before closing Live.',
                    role='support',
                )
            )
