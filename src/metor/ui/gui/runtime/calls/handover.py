"""Exact-client end-then-call continuation guarded by fresh authoritative Call state."""

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from metor.client import MetorClient
from metor.core.api import CallState, CallStateEvent, CallsStateEvent, IpcEvent
from metor.shared import clean_onion, decode_tor_v3_onion_public_key
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from ..controller import GuiController


@dataclass
class CallHandoverIntent:
    """One explicit replacement choice with immutable activation and peer identity."""

    call_id: str
    source_peer: str
    target_peer: str
    client: MetorClient
    generation: int
    profile_instance: str
    epoch: str | None
    revision: int
    end_operation: str
    deadline: float
    phase: Literal['ending', 'reading', 'ready'] = 'ending'
    read_operation: str | None = None


class CallHandover:
    """Starts the selected peer only after the original owned Call is confirmed ended."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates one bounded continuation using only existing public SDK operations."""
        self.controller = controller
        self.pending: CallHandoverIntent | None = None
        self._serial = 0

    def _current_activation(self, pending: CallHandoverIntent) -> bool:
        """Matches the exact client, profile and GUI generation captured by consent."""
        state = self.controller.state
        snapshot = state.snapshot
        return bool(
            not state.covered
            and self.controller.client is pending.client
            and state.generation == pending.generation
            and snapshot is not None
            and snapshot.profile_instance_id == pending.profile_instance
            and snapshot.epoch == pending.epoch
        )

    def _known_target(self, peer: str) -> bool:
        """Rejects mutable aliases and targets removed since their dialog was opened."""
        snapshot = self.controller.state.snapshot
        if snapshot is None or clean_onion(peer) != peer:
            return False
        try:
            decode_tor_v3_onion_public_key(peer)
        except ValueError:
            return False
        known: set[str | None] = {item.onion for item in snapshot.contacts}
        known.update(item.onion for item in snapshot.conversations)
        known.update(item.onion for item in snapshot.live_contexts)
        known.update(item.onion for item in snapshot.pending)
        return peer in known

    def request(self, call_id: str, peer: str) -> bool:
        """Ends exactly the owned current Call once for an explicitly selected other peer."""
        controller, state = self.controller, self.controller.state
        calls, current = controller.calls, controller.calls.current
        snapshot, client = state.snapshot, controller.client
        if (
            self.pending is not None
            or state.covered
            or state.busy
            or snapshot is None
            or not snapshot.profile_instance_id
            or snapshot.epoch is None
            or snapshot.revision is None
            or client is None
            or current is None
            or current.call_id != call_id
            or current.state is CallState.ENDED
            or not current.owned
            or current.peer == peer
            or not self._known_target(peer)
            or not calls.ready
            or calls._operation is not None
            or calls._checking_id is not None
        ):
            return False
        if not calls.end():
            return False
        operation = calls._operation
        assert operation is not None
        self.pending = CallHandoverIntent(
            call_id,
            current.peer,
            peer,
            client,
            state.generation,
            snapshot.profile_instance_id,
            snapshot.epoch,
            snapshot.revision,
            operation[0],
            time.monotonic() + GuiLimits.CALL_HANDOVER_SECONDS,
        )
        calls.status = 'Ending current call…'
        calls.revision += 1
        return True

    def cancel(self, status: str = '') -> None:
        """Drops only the continuation; an already requested exact hangup still resolves."""
        if self.pending is None:
            return
        self.pending = None
        self.controller.calls.status = '' if self.controller.state.covered else status
        self.controller.calls.revision += 1

    def _current_event(self, pending: CallHandoverIntent, event: IpcEvent) -> bool:
        """Rejects a different daemon epoch or pre-consent lifecycle revision."""
        return (
            event.epoch == pending.epoch
            and event.revision is not None
            and event.revision >= pending.revision
        )

    def observe(self, event: IpcEvent) -> None:
        """A new ongoing Call revokes the older replacement choice before it can start."""
        pending = self.pending
        if pending is None:
            return
        if not self._current_activation(pending):
            self.cancel()
        elif isinstance(event, CallStateEvent) and self._current_event(pending, event):
            if (
                event.call.call_id != pending.call_id
                and event.call.state is not CallState.ENDED
            ):
                self.cancel('Another call is now in progress')
            elif pending.phase != 'ending' and event.call.state is not CallState.ENDED:
                self.cancel('Call status changed. Choose who to call again.')

    def end_result(self, update: Update) -> None:
        """Only the exact correlated positive ENDED reply permits a later snapshot read."""
        pending, event = self.pending, update.event
        if pending is None or update.operation != pending.end_operation:
            return
        if (
            not self._current_activation(pending)
            or update.generation != pending.generation
            or not isinstance(event, CallStateEvent)
            or not self._current_event(pending, event)
            or event.call.call_id != pending.call_id
            or event.call.peer != pending.source_peer
            or event.call.state is not CallState.ENDED
            or not event.call.owned
        ):
            self.cancel(
                'Current call could not be confirmed ended. Call the other peer again when ready.'
            )
            return
        assert event.revision is not None
        pending.revision = event.revision
        pending.phase = 'reading'
        self.controller.calls.status = 'Checking call before calling…'
        self.controller.calls.revision += 1

    def install(self, update: Update) -> bool:
        """Accepts only the new snapshot request made after the positive hangup reply."""
        if not update.operation.startswith('call-handover:read:'):
            return False
        pending, event = self.pending, update.event
        if pending is None or update.operation != pending.read_operation:
            return True
        if (
            not self._current_activation(pending)
            or update.generation != pending.generation
            or not self.controller.read_is_current(update)
            or not isinstance(event, CallsStateEvent)
            or not self._current_event(pending, event)
            or event.revision is None
            or event.revision <= pending.revision
        ):
            self.cancel(
                'Could not confirm current call status. Choose who to call again.'
            )
            return True
        original = next(
            (item for item in event.calls if item.call_id == pending.call_id), None
        )
        if (
            original is None
            or original.state is not CallState.ENDED
            or original.peer != pending.source_peer
            or not original.owned
            or any(item.state is not CallState.ENDED for item in event.calls)
        ):
            self.cancel('Call status changed. Choose who to call again.')
            return True
        pending.phase = 'ready'
        return True

    def poll(self) -> bool:
        """Waits for native cleanup and a fresh proof, then starts the immutable target once."""
        pending = self.pending
        if pending is None:
            return False
        controller, calls = self.controller, self.controller.calls
        current = calls.current
        if not self._current_activation(pending):
            self.cancel()
            return True
        if time.monotonic() >= pending.deadline:
            self.cancel('Call change timed out. Choose who to call again.')
            return True
        if current is not None and current.call_id != pending.call_id:
            self.cancel('Another call is now in progress')
            return True
        if (
            pending.phase == 'ending'
            or calls._operation is not None
            or controller.state.busy
        ):
            return False
        if calls.media_active:
            return False
        if pending.phase == 'reading' and pending.read_operation is None:
            self._serial += 1
            operation = f'call-handover:read:{self._serial}'
            if controller.submit(operation, pending.client.get_calls, background=True):
                pending.read_operation = operation
            return False
        if pending.phase != 'ready':
            return False
        if not self._known_target(pending.target_peer) or not calls.ready:
            self.cancel(
                'The selected peer or audio devices changed. Choose who to call again.'
            )
            return True
        self.pending = None
        return calls.start(pending.target_peer)
