"""Explicit LIVE fallback and dismissal using canonical Core outcomes."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    ConnectedEvent,
    ConnectCommand,
    ConnectionAutoAcceptedEvent,
    ConnectionConnectingEvent,
    DisconnectCommand,
    DismissLiveContextCommand,
    FallbackCommand,
    FallbackSuccessEvent,
    FallbackRejectedEvent,
    IpcEvent,
    LiveContextDismissedEvent,
    LiveContextDismissRejectedEvent,
    LiveControlCompletedEvent,
    LiveControlRejectedEvent,
    MessageDirectionCode,
    MessageOperationReason,
    MaxConnectionsReachedEvent,
    RetunnelCommand,
    RetunnelInitiatedEvent,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from ..receipts import ReceiptTarget
from .progress import LiveProgress, startable_context
from .removal import LiveRemovalFlow

if TYPE_CHECKING:
    from ..controller import GuiController


@dataclass(frozen=True)
class LiveMutation:
    """One immutable peer action with an optional exact outbound selection."""

    operation: str
    peer: str
    kind: str
    msg_ids: tuple[str, ...] | None = None
    context_generation: int | None = None
    attempt_id: str | None = None
    retained: tuple[ReceiptTarget, ...] = ()
    cancel_pending: bool = False


class LiveActions:
    """Keeps local presentation until an acknowledged Core mutation permits cleanup."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates one activation-owned action slot.

        Args:
            controller: Current public-service GUI coordinator.
        Returns:
            None
        """
        self.controller = controller
        self.pending: LiveMutation | None = None
        self._serial = 0
        self._uncertain_snapshot: RuntimeSnapshotEvent | None = None
        self._awaiting_snapshot = False
        self._progress = LiveProgress(controller)
        self._removal = LiveRemovalFlow(controller)

    def starting(self, peer: str) -> bool:
        """Reports whether the explicit start still awaits authoritative transport state."""
        return self._progress.starting(peer)

    def failure(self, peer: str) -> str:
        """Returns the peer's actionable failure without duplicating transport progress."""
        return self._progress.failure(peer)

    def stop_status(self, peer: str) -> str:
        """Returns immediate progress while the exact End or Cancel is being confirmed."""
        return self._progress.stop_status(peer)

    def cover(self) -> None:
        """Drops private snapshot references without releasing in-flight or uncertain actions."""
        self._uncertain_snapshot = None
        self._progress.cover()
        self._removal.cover()

    def removing(self, peer: str) -> bool:
        """Reports a confirmed conversion awaiting its separate ended-context dismissal."""
        return self._removal.pending is not None and self._removal.pending.peer == peer

    def remove_context(self, peer: str, *, send_pending_as_drops: bool) -> bool:
        """Applies the explicit send-or-discard choice for an ended conversation."""
        return self._removal.request(peer, send_pending_as_drops=send_pending_as_drops)

    def idle(self, peer: str) -> bool:
        """Reports whether public context facts permit a fresh explicit connection request."""
        snapshot = self.controller.state.snapshot
        if snapshot is None or self.controller.state.covered:
            return False
        return startable_context(
            next((row for row in snapshot.live_contexts if row.onion == peer), None)
        )

    def retry_ready(self, peer: str) -> bool:
        """Enables a fresh explicit start only when its authoritative route permits it."""
        state = self.controller.state
        if (
            state.covered
            or state.busy
            or state.snapshot is None
            or self.controller.client is None
            or self.pending is not None
            or self.starting(peer)
            or bool(self.stop_status(peer))
        ):
            return False
        return self.idle(peer)

    def start(self, peer: str) -> bool:
        """Starts or reconnects only on explicit intent, opening an existing active context.

        Args:
            peer: Original canonical contact identity.
        Returns:
            bool: Whether navigation or a new request was admitted.
        """
        state = self.controller.state
        if state.covered or self.starting(peer) or self.stop_status(peer):
            return False
        if self.controller.client is None or state.snapshot is None:
            state.status = 'Open a profile before starting Live'
            return False
        if state.busy or self.pending is not None:
            state.status = (
                'Wait for the current action to finish, then try Start Live again'
            )
            return False
        entry = next(
            (row for row in state.snapshot.live_contexts if row.onion == peer), None
        )
        if entry is not None and (
            entry.session_state == 'connected' or entry.recovery_eligible
        ):
            self.controller.navigate(Route('V09', peer, Delivery.LIVE))
            return True
        if not startable_context(entry):
            state.status = 'A Live request is already in progress'
            return False
        if not self._progress.prepare_start(peer):
            return False
        if not self._request(peer, 'start'):
            state.status = 'Live request was not started. Try again.'
            return False
        self._progress.start_submitted(peer)
        return True

    def end(
        self,
        peer: str,
        context_generation: int | None = None,
        attempt_id: str | None = None,
    ) -> bool:
        """Ends the originally displayed context after its own local capture has finalized.

        Args:
            peer: Immutable displayed peer.
            context_generation: Exact logical End Live identity.
            attempt_id: Exact current chat invitation identity for Cancel.
        Returns:
            bool: Whether the explicitly requested end sequence was admitted.
        """
        controller = self.controller
        if (
            controller.state.covered
            or self.pending is not None
            or self.stop_status(peer)
        ):
            return False
        if 'qualified_live_control' not in controller.state.capabilities or (
            context_generation is None and attempt_id is None
        ):
            controller.state.status = (
                'This service cannot safely identify the displayed chat invitation'
            )
            return False
        if not self._progress.prepare_stop(peer):
            return False
        binding = controller.voice.press.binding
        if (
            binding is not None
            and binding.peer == peer
            and binding.delivery is Delivery.LIVE
        ):
            self.pending = LiveMutation(
                'live:end-wait',
                peer,
                'end_wait',
                context_generation=context_generation,
                attempt_id=attempt_id,
            )
            self._progress.stop_submitted(
                peer, context_generation, attempt_id, finalizing=True
            )
            controller.voice.depart()
            controller.state.status = 'Finishing recording before ending Live…'
            return True
        return self._request(
            peer, 'end', context_generation=context_generation, attempt_id=attempt_id
        )

    def fallback(self, peer: str, msg_ids: tuple[str, ...] | None = None) -> bool:
        """Requests selective or bulk conversion without assigning new message IDs.

        Args:
            peer: Canonical original peer.
            msg_ids: Explicit immutable selection, or None for Core-eligible bulk conversion.
        Returns:
            bool: Whether the explicit request was admitted.
        """
        if msg_ids is not None and not msg_ids:
            return False
        return self._request(peer, 'fallback', msg_ids)

    def change_route(self, peer: str, context_generation: int) -> bool:
        """Changes only the explicitly selected active LIVE route.

        Args:
            peer: Canonical original peer.
            context_generation: Logical context captured by the menu control.
        Returns:
            bool: Whether the exact action was admitted.
        """
        state = self.controller.state
        if 'qualified_live_retunnel' not in state.capabilities:
            return False
        return self._request(peer, 'route', context_generation=context_generation)

    def close_context(self, peer: str, *, cancel_pending: bool = False) -> bool:
        """Closes only ended contexts, preserving unresolved outbound work.

        Args:
            peer: Exact canonical context identity.
        Returns:
            bool: Whether local close or a Core dismissal request was admitted.
        """
        state = self.controller.state
        if cancel_pending and 'live_pending_cancellation' not in state.capabilities:
            state.status = 'This Core does not support discarding pending Live messages'
            return False
        if not self._removal.ready(peer, allow_pending=cancel_pending):
            return False
        assert state.snapshot is not None
        entry = next(
            (item for item in state.snapshot.live_contexts if item.onion == peer), None
        )
        if entry is not None:
            return self._request(peer, 'close', cancel_pending=cancel_pending)
        self._discard_context(peer)
        state.status = 'Local Live conversation closed'
        return True

    def _request(
        self,
        peer: str,
        kind: str,
        msg_ids: tuple[str, ...] | None = None,
        context_generation: int | None = None,
        attempt_id: str | None = None,
        cancel_pending: bool = False,
    ) -> bool:
        """Admits one captured action without automatic retries.

        Args:
            peer: Exact canonical peer.
            kind: Internal explicit fallback/close operation.
            msg_ids: Optional direction-qualified outbound selection.
            context_generation: Original logical End identity.
            attempt_id: Original chat invitation identity.
        Returns:
            bool: Whether the current client accepted the request.
        """
        controller, client = self.controller, self.controller.client
        if (
            controller.state.covered
            or client is None
            or self.pending is not None
            or (kind == 'fallback' and controller.receipts.busy)
        ):
            return False
        self._serial += 1
        mutation = LiveMutation(
            'live:' + str(self._serial),
            peer,
            kind,
            msg_ids,
            context_generation,
            attempt_id,
            tuple(
                target
                for target in controller.receipts.capture(
                    Delivery.LIVE, peer, direction=MessageDirectionCode.OUT
                )
                if msg_ids is None or target.msg_id in msg_ids
            )
            if kind == 'fallback'
            else (),
            cancel_pending=cancel_pending,
        )
        command = (
            FallbackCommand(peer, list(msg_ids) if msg_ids is not None else None)
            if kind == 'fallback'
            else DisconnectCommand(peer, context_generation, attempt_id)
            if kind == 'end'
            else ConnectCommand(peer)
            if kind == 'start'
            else RetunnelCommand(peer, context_generation)
            if kind == 'route'
            else DismissLiveContextCommand(peer, cancel_pending)
        )
        if not controller.submit(
            mutation.operation, lambda: client.request(command, IpcEvent)
        ):
            return False
        self.pending = mutation
        if kind == 'end':
            self._progress.stop_submitted(peer, context_generation, attempt_id)
        return True

    def install(self, update: Update) -> bool:
        """Reconciles only the correlated result, retaining sources after uncertainty.

        Args:
            update: Current-activation public completion.
        Returns:
            bool: Whether this owner handled the completion.
        """
        if update.generation != self.controller.state.generation:
            return False
        self._progress.observe_start(update.event)
        mutation = self.pending
        if mutation is None or update.operation != mutation.operation:
            return False
        controller, event = self.controller, update.event
        self._removal.observe(update.operation, event)
        if mutation.kind == 'end':
            self._progress.resolve_stop(mutation.peer, event)
        if event is None:
            progress = self._progress.starts.get(mutation.peer)
            if (
                mutation.kind == 'start'
                and progress is not None
                and progress.phase in {'submitting', 'connecting'}
            ):
                progress.phase = 'checking'
            if mutation.kind == 'fallback':
                controller.receipts.start(mutation.retained)
            self._uncertain_snapshot = controller.state.snapshot
            self._awaiting_snapshot = True
            controller.refresh_state()
            if not controller.state.covered and mutation.kind != 'start':
                controller.state.status = 'Could not confirm the Live action. Refreshing current state; no automatic retry.'
            return True
        self.pending = None
        status: str | None = 'Live action could not be completed'
        if (
            mutation.kind == 'start'
            and isinstance(
                event,
                (
                    ConnectionConnectingEvent,
                    ConnectionAutoAcceptedEvent,
                    ConnectedEvent,
                ),
            )
            and event.onion == mutation.peer
        ):
            progress = self._progress.starts.get(mutation.peer)
            if progress is not None and progress.phase in {'submitting', 'checking'}:
                progress.phase = 'connecting'
                progress.snapshot = controller.state.snapshot
                progress.revision = max(progress.revision, event.revision or 0)
            status = None
        elif mutation.kind == 'start':
            self._progress.fail_start(
                mutation.peer,
                'Too many Live connections. End one and try again.'
                if isinstance(event, MaxConnectionsReachedEvent)
                else 'Live could not connect. Try again or send a Drop.',
            )
            status = None
        elif (
            mutation.kind == 'end'
            and isinstance(event, LiveControlCompletedEvent)
            and event.onion == mutation.peer
        ):
            self._progress.starts.pop(mutation.peer, None)
            status = (
                'Chat invitation cancelled' if mutation.attempt_id else 'Live ended'
            )
        elif isinstance(event, LiveControlRejectedEvent):
            if mutation.kind == 'end':
                self._progress.stops.pop(mutation.peer, None)
            status = 'The Live chat changed. Current state is being refreshed.'
        elif (
            mutation.kind == 'route'
            and isinstance(event, RetunnelInitiatedEvent)
            and event.onion == mutation.peer
        ):
            status = None
        elif (
            mutation.kind == 'fallback'
            and isinstance(event, FallbackSuccessEvent)
            and event.onion == mutation.peer
        ):
            if mutation.msg_ids is not None and set(event.msg_ids) != set(
                mutation.msg_ids
            ):
                controller.refresh_state()
                return True
            for msg_id in event.msg_ids:
                self.confirm_fallback(mutation.peer, msg_id)
            controller.inventory.reset()
            if controller.state.route == Route('V09', mutation.peer, Delivery.LIVE):
                controller.navigate(Route('V08', mutation.peer, Delivery.DROP))
            status = (
                None
                if controller.state.route == Route('V08', mutation.peer, Delivery.DROP)
                else str(event.count)
                + ' moved to Drop'
                + ('s' if event.count != 1 else '')
            )
        elif (
            mutation.kind == 'close'
            and isinstance(event, LiveContextDismissedEvent)
            and event.onion == mutation.peer
        ):
            self._discard_context(mutation.peer)
            status = 'Live conversation closed'
        elif isinstance(
            event, (FallbackRejectedEvent, LiveContextDismissRejectedEvent)
        ):
            status = {
                MessageOperationReason.OUTBOUND_PENDING_LIVE: 'Reconnect or send pending items as Drops before closing Live',
                MessageOperationReason.ACTIVE_LIVE_CONTEXT: 'End Live before closing this conversation',
                MessageOperationReason.NOT_FINALIZED: 'Finish recording or retry finalization before sending as Drop',
                MessageOperationReason.NOT_PENDING_LIVE: 'Selected items are no longer pending Live',
                MessageOperationReason.INVALID_SELECTION: 'The selection is no longer available',
            }.get(event.reason, 'Live action could not be completed')
        controller.refresh_state()
        if not controller.state.covered and status is not None:
            controller.state.status = status
        return True

    def confirm_fallback(self, peer: str, msg_id: str) -> None:
        """Installs positively confirmed conversion of one original own LIVE identity.

        Args:
            peer: Exact original peer.
            msg_id: Original message identity, preserved by Core fallback.
        Returns:
            None
        """
        controller = self.controller
        controller.transcript.discard(
            peer, Delivery.LIVE, msg_id, MessageDirectionCode.OUT
        )
        controller.playback.forget(
            peer, Delivery.LIVE, msg_id, MessageDirectionCode.OUT
        )
        turn = controller.voice.live_turns.get(msg_id)
        if turn is not None and turn.binding.peer == peer:
            turn.actual_delivery = Delivery.DROP
        controller.inventory.reset()

    def _discard_context(self, peer: str) -> None:
        """Releases all volatile content and permission belonging to a closed LIVE context.

        Args:
            peer: Positively dismissed or purely local context.
        Returns:
            None
        """
        controller = self.controller
        self._progress.discard(peer)
        controller.playback.forget(peer, Delivery.LIVE)
        controller.transcript.discard(peer, Delivery.LIVE)
        controller.state.drafts.pop((peer, Delivery.LIVE), None)
        for msg_id, turn in tuple(controller.voice.live_turns.items()):
            if turn.binding.peer == peer:
                del controller.voice.live_turns[msg_id]
        if (
            controller.state.route.peer == peer
            and controller.state.route.delivery is Delivery.LIVE
        ):
            controller.navigate(Route('V07', delivery=Delivery.LIVE))
        controller.inventory.reset()

    def poll(self) -> None:
        """Rearms a fresh explicit action only after an uncertain result is resnapshotted.

        Args:
            None
        Returns:
            None
        """
        controller = self.controller
        waiting = self.pending
        if (
            waiting is not None
            and waiting.kind == 'end_wait'
            and controller.voice.press.binding is None
            and not controller.state.covered
        ):
            self.pending = None
            if not self._request(
                waiting.peer,
                'end',
                context_generation=waiting.context_generation,
                attempt_id=waiting.attempt_id,
            ):
                self.pending = waiting
        snapshot = controller.state.snapshot
        if (
            self._awaiting_snapshot
            and not controller.state.covered
            and snapshot is not None
            and snapshot is not self._uncertain_snapshot
        ):
            self.pending = None
            self._uncertain_snapshot = None
            self._awaiting_snapshot = False
        if snapshot is None or controller.state.covered:
            return
        self._progress.poll()
        self._removal.poll()
