"""Explicit LIVE fallback and dismissal using canonical Core outcomes."""

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    ConnectCommand,
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
    RetunnelCommand,
    RetunnelInitiatedEvent,
)
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

    def start(self, peer: str) -> bool:
        """Starts or reconnects only on explicit intent, opening an existing active context.

        Args:
            peer: Original canonical contact identity.
        Returns:
            bool: Whether navigation or a new request was admitted.
        """
        state = self.controller.state
        if state.covered or state.snapshot is None or self.pending is not None:
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
        return self._request(peer, 'start')

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
            attempt_id: Exact current calling identity for Cancel.
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
                'This service cannot safely identify the displayed call'
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
            attempt_id: Original calling identity.
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
        mutation = self.pending
        if mutation is None or update.operation != mutation.operation:
            return False
        controller, event = self.controller, update.event
        if event is None:
            if mutation.kind == 'fallback':
                controller.receipts.start(mutation.retained)
            self._uncertain_snapshot = id(controller.state.snapshot)
            controller.refresh_state()
            if not controller.state.covered:
                controller.state.status = 'Could not confirm the Live action. Refreshing current state; no automatic retry.'
            return True
        self.pending = None
        status = 'Live action could not be completed'
        if (
            mutation.kind == 'start'
            and isinstance(event, ConnectionConnectingEvent)
            and event.onion == mutation.peer
        ):
            status = 'Calling…'
        elif (
            mutation.kind == 'end'
            and isinstance(event, LiveControlCompletedEvent)
            and event.onion == mutation.peer
        ):
            status = 'Call cancelled' if mutation.attempt_id else 'Live ended'
        elif isinstance(event, LiveControlRejectedEvent):
            status = 'The call changed. Current state is being refreshed.'
        elif (
            mutation.kind == 'route'
            and isinstance(event, RetunnelInitiatedEvent)
            and event.onion == mutation.peer
        ):
            status = 'Changing Live route…'
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
            status = (
                str(event.count) + ' queued as Drop' + ('s' if event.count != 1 else '')
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
        if not controller.state.covered:
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
        controller.playback.forget(peer, Delivery.LIVE)
        controller.transcript.discard(peer, Delivery.LIVE)
        controller.state.drafts.pop((peer, Delivery.LIVE), None)
        for msg_id, turn in tuple(controller.voice.live_turns.items()):
            if turn.binding.peer == peer:
                del controller.voice.live_turns[msg_id]
        auto = controller.playback.auto
        auto.overrides = {
            key: value for key, value in auto.overrides.items() if key[0] != peer
        }
        auto.queue = deque(
            (target, key) for target, key in auto.queue if target.peer != peer
        )
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
