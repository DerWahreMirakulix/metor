"""Activation-owned LIVE progress bridging asynchronous admission and Core snapshots."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from metor.core.api import (
    ConnectedEvent,
    ConnectionActor,
    ConnectionFailedEvent,
    ConnectionReasonCode,
    ConnectionRejectedEvent,
    IpcEvent,
    Delivery,
    LiveContextEntry,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route

if TYPE_CHECKING:
    from ..controller import GuiController


def startable_context(entry: LiveContextEntry | None) -> bool:
    """Allows explicit starts through idle recovery hints without reusing logical permission.

    Core may retain grace or scheduled transport hints after an invitation ends.
    Only an accepted recovery context or an actual outbound attempt makes those
    hints an ongoing chat. The explicit Connect command still owns admission.
    """
    return entry is None or (
        not entry.recovery_eligible
        and not entry.outbound_attempt_id
        and entry.session_state
        in {'disconnected', 'reconnect_grace', 'reconnect_scheduled'}
    )


@dataclass
class LiveStart:
    """Bridges explicit local admission to authoritative transport presentation."""

    snapshot: RuntimeSnapshotEvent | None
    revision: int
    phase: Literal['submitting', 'connecting', 'connected', 'checking', 'failed'] = (
        'submitting'
    )
    error: str = ''


@dataclass
class LiveStop:
    """Exact local stop identity retained while its result awaits a fresh snapshot."""

    snapshot: RuntimeSnapshotEvent | None
    revision: int
    context_generation: int | None
    attempt_id: str | None
    finalizing: bool = False
    awaiting_result: bool = True


class LiveProgress:
    """Retains bounded local operation feedback until authoritative state catches up."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates one activation-owned progress cache with no communication side effects."""
        self.controller = controller
        self.starts: dict[str, LiveStart] = {}
        self.stops: dict[str, LiveStop] = {}

    def starting(self, peer: str) -> bool:
        """Reports an admitted start before its final transport outcome is known."""
        progress = self.starts.get(peer)
        return progress is not None and progress.phase != 'failed'

    def failure(self, peer: str) -> str:
        """Returns one peer's failure until retry or authoritative connection success."""
        if self.controller.state.covered:
            return ''
        progress = self.starts.get(peer)
        return progress.error if progress is not None else ''

    def prepare_start(self, peer: str) -> bool:
        """Reserves bounded progress capacity without replacing a pending request."""
        if len(self.starts) >= GuiLimits.TEXT_CONTEXTS and peer not in self.starts:
            completed = next(
                (key for key, item in self.starts.items() if item.phase == 'failed'),
                None,
            )
            if completed is None:
                self.controller.state.status = (
                    'Finish a pending Live request before starting another'
                )
                return False
            del self.starts[completed]
        return True

    def start_submitted(self, peer: str) -> None:
        """Bridges the admitted request until a current transport snapshot arrives."""
        snapshot = self.controller.state.snapshot
        assert snapshot is not None
        self.starts[peer] = LiveStart(snapshot, snapshot.revision or 0)

    def prepare_stop(self, peer: str) -> bool:
        """Bounds outstanding stop feedback without evicting an unconfirmed action."""
        if len(self.stops) >= GuiLimits.TEXT_CONTEXTS and peer not in self.stops:
            self.controller.state.status = (
                'Refresh the current Live state before ending another conversation'
            )
            return False
        return True

    def stop_submitted(
        self,
        peer: str,
        context_generation: int | None,
        attempt_id: str | None,
        *,
        finalizing: bool = False,
    ) -> None:
        """Publishes immediate progress for the exact End or Cancel target."""
        snapshot = self.controller.state.snapshot
        self.stops[peer] = LiveStop(
            snapshot,
            snapshot.revision or 0 if snapshot is not None else 0,
            context_generation,
            attempt_id,
            finalizing,
        )

    def stop_status(self, peer: str) -> str:
        """Describes only the original stopping identity, never a replacement connection."""
        progress = self.stops.get(peer)
        state = self.controller.state
        if progress is None or state.covered:
            return ''
        entry = (
            next(
                (row for row in state.snapshot.live_contexts if row.onion == peer), None
            )
            if state.snapshot is not None
            else None
        )
        if (
            entry is not None
            and not startable_context(entry)
            and (
                progress.context_generation is not None
                and entry.context_generation != progress.context_generation
                or progress.attempt_id is not None
                and entry.outbound_attempt_id != progress.attempt_id
            )
        ):
            return ''
        return (
            'Finishing recording…'
            if progress.finalizing
            else 'Cancelling Live…'
            if progress.attempt_id is not None
            else 'Ending Live…'
        )

    def resolve_stop(self, peer: str, event: IpcEvent | None) -> None:
        """Retains resolved or uncertain stop feedback until a post-result snapshot arrives."""
        progress = self.stops.get(peer)
        if progress is None:
            return
        snapshot = self.controller.state.snapshot
        progress.awaiting_result = False
        progress.snapshot = snapshot
        progress.revision = max(
            progress.revision,
            snapshot.revision or 0 if snapshot is not None else 0,
            event.revision or 0 if event is not None else 0,
        )

    def discard(self, peer: str) -> None:
        """Clears presentation belonging to a positively removed local conversation."""
        self.starts.pop(peer, None)
        self.stops.pop(peer, None)

    def cover(self) -> None:
        """Releases private snapshot references while preserving exact operation progress."""
        for starting in self.starts.values():
            starting.snapshot = None
        for stopping in self.stops.values():
            stopping.snapshot = None

    def fail_start(self, peer: str, text: str) -> None:
        """Keeps actionable failure by its peer and notifies only a departed view."""
        state = self.controller.state
        progress = self.starts.get(peer)
        if progress is None or progress.phase == 'failed' or state.covered:
            return
        progress.phase, progress.error = 'failed', text
        progress.snapshot = state.snapshot
        if state.route != Route('V09', peer, Delivery.LIVE):
            state.status = self.controller.contacts.alias(peer) + ': ' + text

    def observe_start(self, event: IpcEvent | None) -> None:
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
        progress = self.starts.get(peer)
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
            progress.snapshot = state.snapshot
        elif isinstance(event, ConnectionRejectedEvent):
            if (
                event.actor is not ConnectionActor.LOCAL
                and event.reason_code
                is not ConnectionReasonCode.MUTUAL_TIEBREAKER_LOSER
            ):
                self.fail_start(peer, 'Live was declined. Try again or send a Drop.')
        else:
            self.fail_start(peer, 'Live could not connect. Try again or send a Drop.')

    def poll(self) -> None:
        """Reconciles local progress only against a newer authoritative snapshot."""
        controller = self.controller
        snapshot = controller.state.snapshot
        if snapshot is None or controller.state.covered:
            return
        for peer, stopping in tuple(self.stops.items()):
            if (
                stopping.finalizing
                or stopping.awaiting_result
                or stopping.snapshot is snapshot
                or (
                    snapshot.revision is not None
                    and snapshot.revision < stopping.revision
                )
            ):
                continue
            del self.stops[peer]
        for peer, progress in tuple(self.starts.items()):
            if (
                self.stop_status(peer)
                or progress.snapshot is snapshot
                or (
                    snapshot.revision is not None
                    and snapshot.revision < progress.revision
                )
            ):
                continue
            progress.snapshot = snapshot
            entry = next(
                (row for row in snapshot.live_contexts if row.onion == peer), None
            )
            if entry is not None and (
                entry.session_state == 'connected' or entry.recovery_eligible
            ):
                self.starts.pop(peer, None)
            elif progress.phase in {'connecting', 'connected', 'checking'} and not (
                entry is not None
                and (entry.outbound_attempt_id or entry.session_state == 'pending')
            ):
                self.fail_start(
                    peer,
                    'Live request could not be confirmed. Try again or send a Drop.'
                    if progress.phase == 'checking'
                    else 'Live ended. Try again or send a Drop.'
                    if progress.phase == 'connected'
                    else 'Live could not connect. Try again or send a Drop.',
                )
