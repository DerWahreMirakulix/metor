"""Projects ended LIVE work without changing Core recovery or fallback policy."""

from typing import TYPE_CHECKING

from metor.core.api import Delivery
from metor.ui.gui.state import Route

if TYPE_CHECKING:
    from ..controller import GuiController


def pending_fallback_count(controller: 'GuiController', route: Route) -> int:
    """Returns retained outbound work only when this LIVE conversation has ended.

    Accepted recovery keeps its normal composer. An admitted local start or stop
    also bridges stale snapshots, so a transient disconnected projection cannot
    invite fallback during an ongoing connection operation. The returned count
    is presentation only; Core owns eligibility and conversion on explicit intent.
    """
    state = controller.state
    if (
        state.covered
        or state.snapshot is None
        or route.delivery is not Delivery.LIVE
        or controller.live.starting(route.peer or '')
        or controller.live.stop_status(route.peer or '')
    ):
        return 0
    entry = next(
        (row for row in state.snapshot.live_contexts if row.onion == route.peer),
        None,
    )
    return (
        entry.pending_outbound_count
        if entry is not None
        and entry.session_state == 'disconnected'
        and not entry.recovery_eligible
        and not entry.outbound_attempt_id
        else 0
    )
