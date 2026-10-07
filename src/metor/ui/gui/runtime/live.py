"""Explicit LIVE fallback and dismissal using canonical Core outcomes."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from metor.core.api import (
    Delivery,
    ConnectedEvent,
    ConnectCommand,
    ConnectionActor,
    ConnectionAutoAcceptedEvent,
    ConnectionConnectingEvent,
    ConnectionFailedEvent,
    ConnectionReasonCode,
    ConnectionRejectedEvent,
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
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from .receipts import ReceiptTarget

if TYPE_CHECKING:
    from .controller import GuiController


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


@dataclass
class LiveStart:
    """Bridges explicit local admission to authoritative transport presentation."""

    snapshot_id: int
    revision: int
    phase: Literal['submitting', 'connecting', 'connected', 'checking', 'failed'] = (
        'submitting'
    )
    error: str = ''


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
        self._uncertain_snapshot: int | None = None
        self._starts: dict[str, LiveStart] = {}

    def starting(self, peer: str) -> bool:
        """Reports an admitted start before its final transport outcome is known."""
        progress = self._starts.get(peer)
        return progress is not None and progress.phase != 'failed'

    def failure(self, peer: str) -> str:
        """Returns one peer's bounded local failure until retry or connection succeeds."""
        if self.controller.state.covered:
            return ''
        progress = self._starts.get(peer)
        return progress.error if progress is not None else ''

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
        ):
            return False
        return not any(
            row.onion == peer
            and (row.session_state != 'disconnected' or row.recovery_eligible)
            for row in state.snapshot.live_contexts
        )

    def start(self, peer: str) -> bool:
        """Starts or reconnects only on explicit intent, opening an existing active context.

        Args:
            peer: Original canonical contact identity.
        Returns:
            bool: Whether navigation or a new request was admitted.
        """
        state = self.controller.state
        if state.covered or self.starting(peer):
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
        if entry is not None and entry.session_state != 'disconnected':
            state.status = 'A Live request is already in progress'
            return False
        if len(self._starts) >= GuiLimits.TEXT_CONTEXTS and peer not in self._starts:
            completed = next(
                (key for key, item in self._starts.items() if item.phase == 'failed'),
                None,
            )
            if completed is None:
                state.status = 'Finish a pending Live request before starting another'
                return False
            del self._starts[completed]
        if not self._request(peer, 'start'):
            state.status = 'Live request was not started. Try again.'
            return False
        self._starts[peer] = LiveStart(id(state.snapshot), state.snapshot.revision or 0)
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
        if controller.state.covered or self.pending is not None:
            return False
        if 'qualified_live_control' not in controller.state.capabilities or (
            context_generation is None and attempt_id is None
        ):
            controller.state.status = (
                'This service cannot safely identify the displayed chat invitation'
            )
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

    def close_context(self, peer: str) -> bool:
        """Closes only ended contexts, preserving unresolved outbound work.

        Args:
            peer: Exact canonical context identity.
        Returns:
            bool: Whether local close or a Core dismissal request was admitted.
        """
        controller, state = self.controller, self.controller.state
        if state.covered or state.snapshot is None or state.busy or self.pending:
            return False
        if any(
            p == peer and d is Delivery.LIVE
            for p, d, _text in controller.text.operations.values()
        ):
            state.status = 'Confirm the pending send before closing Live'
            return False
        review = controller.voice.reviews.get(peer)
        if review is not None and review.binding.delivery is Delivery.LIVE:
            state.status = (
                'Send or discard the unsent voice recording before closing this chat'
            )
            return False
        binding = controller.voice.press.binding
        if binding is not None and binding.peer == peer:
            state.status = 'Finish recording before closing Live'
            return False
        entry = next(
            (item for item in state.snapshot.live_contexts if item.onion == peer), None
        )
        if entry is not None:
            if entry.session_state != 'disconnected' or entry.recovery_eligible:
                state.status = 'End Live before closing this conversation'
                return False
            if entry.pending_outbound_count:
                state.status = (
                    'Reconnect or send pending items as Drops before closing Live'
                )
                return False
            return self._request(peer, 'close')
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
            else DismissLiveContextCommand(peer)
        )
        if not controller.submit(
            mutation.operation, lambda: client.request(command, IpcEvent)
        ):
            return False
        self.pending = mutation
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
        self._observe_start(update.event)
        mutation = self.pending
        if mutation is None or update.operation != mutation.operation:
            return False
        controller, event = self.controller, update.event
        if event is None:
            progress = self._starts.get(mutation.peer)
            if (
                mutation.kind == 'start'
                and progress is not None
                and progress.phase in {'submitting', 'connecting'}
            ):
                progress.phase = 'checking'
            if mutation.kind == 'fallback':
                controller.receipts.start(mutation.retained)
            self._uncertain_snapshot = id(controller.state.snapshot)
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
            progress = self._starts.get(mutation.peer)
            if progress is not None and progress.phase in {'submitting', 'checking'}:
                progress.phase = 'connecting'
                progress.snapshot_id = id(controller.state.snapshot)
                progress.revision = max(progress.revision, event.revision or 0)
            status = None
        elif mutation.kind == 'start':
            self._fail_start(
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
            self._starts.pop(mutation.peer, None)
            status = (
                'Chat invitation cancelled' if mutation.attempt_id else 'Live ended'
            )
        elif isinstance(event, LiveControlRejectedEvent):
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

    def _fail_start(self, peer: str, text: str) -> None:
        """Keeps actionable failure by its peer and notifies only a departed view."""
        state = self.controller.state
        progress = self._starts.get(peer)
        if progress is None or progress.phase == 'failed' or state.covered:
            return
        progress.phase, progress.error = 'failed', text
        progress.snapshot_id = id(state.snapshot)
        if state.route != Route('V09', peer, Delivery.LIVE):
            state.status = self.controller.contacts.alias(peer) + ': ' + text

    def _observe_start(self, event: IpcEvent | None) -> None:
        """Installs terminal start facts without treating recovery as a new invitation."""
        if (
            not isinstance(
                event, (ConnectedEvent, ConnectionFailedEvent, ConnectionRejectedEvent)
            )
            or not event.onion
        ):
            return
        state = self.controller.state
        peer = event.onion
        progress = self._starts.get(peer)
        if state.covered or progress is None:
            return
        if state.snapshot is not None and (
            event.epoch is not None
            and event.epoch != state.snapshot.epoch
            or event.revision is not None
            and event.revision < progress.revision
        ):
            return
        progress.revision = max(progress.revision, event.revision or 0)
        if isinstance(event, ConnectedEvent):
            progress.phase = 'connected'
            progress.error = ''
            progress.snapshot_id = id(state.snapshot)
        elif isinstance(event, ConnectionRejectedEvent):
            if (
                event.actor is not ConnectionActor.LOCAL
                and event.reason_code
                is not ConnectionReasonCode.MUTUAL_TIEBREAKER_LOSER
            ):
                self._fail_start(peer, 'Live was declined. Try again or send a Drop.')
        else:
            self._fail_start(peer, 'Live could not connect. Try again or send a Drop.')

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
        self._starts.pop(peer, None)
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
            self._uncertain_snapshot is not None
            and snapshot is not None
            and id(snapshot) != self._uncertain_snapshot
        ):
            self.pending = None
            self._uncertain_snapshot = None
        if snapshot is None or controller.state.covered:
            return
        for peer, progress in tuple(self._starts.items()):
            if progress.snapshot_id == id(snapshot) or (
                snapshot.revision is not None and snapshot.revision < progress.revision
            ):
                continue
            progress.snapshot_id = id(snapshot)
            entry = next(
                (row for row in snapshot.live_contexts if row.onion == peer), None
            )
            if entry is not None and (
                entry.session_state == 'connected' or entry.recovery_eligible
            ):
                self._starts.pop(peer, None)
            elif progress.phase in {'connecting', 'connected', 'checking'} and not (
                entry is not None
                and (entry.outbound_attempt_id or entry.session_state == 'pending')
            ):
                self._fail_start(
                    peer,
                    'Live request could not be confirmed. Try again or send a Drop.'
                    if progress.phase == 'checking'
                    else 'Live ended. Try again or send a Drop.'
                    if progress.phase == 'connected'
                    else 'Live could not connect. Try again or send a Drop.',
                )
