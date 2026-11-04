"""Confirmed pending fallback followed by separately guarded ended LIVE dismissal."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    FallbackSuccessEvent,
    IpcEvent,
    RuntimeSnapshotEvent,
)

if TYPE_CHECKING:
    from ..controller import GuiController


@dataclass
class PendingRemoval:
    """One explicit send-and-remove intent waiting for confirmed conversion."""

    peer: str
    operation: str
    snapshot: RuntimeSnapshotEvent | None = None
    revision: int = 0
    confirmed: bool = False


class LiveRemovalFlow:
    """Keeps pending conversion and removal separate under authoritative readback."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates one activation-owned chain without an automatic delivery policy."""
        self.controller = controller
        self.pending: PendingRemoval | None = None

    def ready(self, peer: str, *, allow_pending: bool) -> bool:
        """Checks local unresolved admission and Core-owned ended-state eligibility."""
        controller, state = self.controller, self.controller.state
        if (
            state.covered
            or state.snapshot is None
            or state.busy
            or controller.live.pending
        ):
            return False
        if any(
            p == peer and d is Delivery.LIVE
            for p, d, _text in controller.text.operations.values()
        ):
            state.status = 'Confirm the pending send before removing Live'
            return False
        review = controller.voice.reviews.get(peer)
        if review is not None and review.binding.delivery is Delivery.LIVE:
            state.status = (
                'Send or discard the unsent voice recording before removing this chat'
            )
            return False
        binding = controller.voice.press.binding
        if binding is not None and binding.peer == peer:
            state.status = 'Finish recording before removing Live'
            return False
        entry = next(
            (row for row in state.snapshot.live_contexts if row.onion == peer), None
        )
        if (
            controller.live.starting(peer)
            or controller.live.stop_status(peer)
            or entry is not None
            and (
                entry.session_state != 'disconnected'
                or entry.recovery_eligible
                or entry.outbound_attempt_id
            )
        ):
            state.status = 'End Live before removing this conversation'
            return False
        if entry is not None and entry.pending_outbound_count and not allow_pending:
            state.status = (
                'Reconnect or send pending items as Drops before removing Live'
            )
            return False
        return True

    def request(self, peer: str, *, send_pending_as_drops: bool) -> bool:
        """Admits exactly the explicit pending-work choice without implicit conversion."""
        controller, state = self.controller, self.controller.state
        if self.pending is not None or not self.ready(peer, allow_pending=True):
            return False
        assert state.snapshot is not None
        entry = next(
            (row for row in state.snapshot.live_contexts if row.onion == peer), None
        )
        if entry is None or not entry.pending_outbound_count:
            return controller.live.close_context(peer)
        if not send_pending_as_drops:
            return controller.live.close_context(peer, cancel_pending=True)
        if not controller.live.fallback(peer):
            return False
        mutation = controller.live.pending
        assert mutation is not None
        self.pending = PendingRemoval(peer, mutation.operation)
        return True

    def observe(self, operation: str, event: IpcEvent | None) -> None:
        """Only a positive bulk conversion arms the subsequent dismissal step."""
        pending = self.pending
        if pending is None or operation != pending.operation:
            return
        if isinstance(event, FallbackSuccessEvent) and event.onion == pending.peer:
            pending.confirmed = True
            pending.snapshot = self.controller.state.snapshot
            pending.revision = event.revision or 0
            return
        self.pending = None

    def cover(self) -> None:
        """Cancels deferred dismissal when privacy revokes its foreground interaction."""
        self.pending = None

    def poll(self) -> None:
        """Dismisses only after conversion and a fresh ended snapshot with no pending work."""
        controller, pending = self.controller, self.pending
        state, snapshot = controller.state, controller.state.snapshot
        if (
            pending is None
            or not pending.confirmed
            or state.covered
            or state.busy
            or controller.live.pending is not None
            or controller.receipts.busy
            or snapshot is None
            or snapshot is pending.snapshot
            or snapshot.revision is not None
            and snapshot.revision < pending.revision
        ):
            return
        self.pending = None
        if not self.ready(pending.peer, allow_pending=False):
            return
        controller.live.close_context(pending.peer)
