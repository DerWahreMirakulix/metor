"""Fresh exact-client reconciliation after an End outcome cannot be confirmed."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metor.client import MetorClient
from metor.core.api import CallState, CallStateEvent, CallsStateEvent, IpcEvent
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from ..controller import GuiController


@dataclass
class EndCallIntent:
    """Captures one end request without retaining or reviving its replacement choice."""

    operation: str
    call_id: str
    peer: str
    client: MetorClient
    generation: int
    profile_instance: str
    epoch: str
    revision: int
    uncertain: bool = False
    read_operation: str | None = None


class EndCallReconciliation:
    """Restores only fresh owned old-call truth; it never starts a new Call."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates one bounded exact-client read owner alongside ordinary Call presentation."""
        self.controller = controller
        self.intent: EndCallIntent | None = None
        self._serial = 0

    @property
    def pending(self) -> bool:
        """Reports whether a fresh read is required after an uncertain end result."""
        return self.intent is not None and self.intent.uncertain

    def begin(
        self, operation: str, call_id: str, peer: str, client: MetorClient
    ) -> None:
        """Captures qualified activation and identity before any end reply can install."""
        self.clear()
        state, snapshot = self.controller.state, self.controller.state.snapshot
        if (
            snapshot is None
            or not snapshot.profile_instance_id
            or snapshot.epoch is None
            or snapshot.revision is None
        ):
            return
        self.intent = EndCallIntent(
            operation,
            call_id,
            peer,
            client,
            state.generation,
            snapshot.profile_instance_id,
            snapshot.epoch,
            snapshot.revision,
        )

    def _current(self, intent: EndCallIntent) -> bool:
        """Rejects privacy, client replacement and profile/daemon activation changes."""
        state, snapshot = self.controller.state, self.controller.state.snapshot
        return bool(
            not state.covered
            and self.controller.client is intent.client
            and state.generation == intent.generation
            and snapshot is not None
            and snapshot.profile_instance_id == intent.profile_instance
            and snapshot.epoch == intent.epoch
        )

    def clear(self) -> None:
        """Cancels only this read owner and its matching uncertain-operation gate."""
        intent, self.intent = self.intent, None
        if intent is not None and self.controller.calls._checking_id == intent.call_id:
            self.controller.calls._checking_id = None

    def end_result(self, update: Update) -> None:
        """An exact positive ended reply needs no recovery; all other outcomes require a read."""
        intent, event = self.intent, update.event
        if intent is None or update.operation != intent.operation:
            return
        if not self._current(intent):
            self.clear()
        elif (
            isinstance(event, CallStateEvent)
            and event.epoch == intent.epoch
            and event.revision is not None
            and event.revision >= intent.revision
            and event.call.call_id == intent.call_id
            and event.call.peer == intent.peer
            and event.call.owned
            and event.call.state is CallState.ENDED
        ):
            self.clear()
        else:
            intent.uncertain = True
            self.controller.calls._checking_id = intent.call_id

    def observe(self, event: IpcEvent) -> None:
        """A later confirmed termination or replacement revokes the older read owner."""
        intent = self.intent
        if not self.pending or intent is None:
            return
        if not self._current(intent):
            self.clear()
        elif (
            isinstance(event, CallStateEvent)
            and event.epoch == intent.epoch
            and event.revision is not None
            and event.revision > intent.revision
        ):
            intent.revision = event.revision
            if (
                event.call.call_id == intent.call_id
                and event.call.state is CallState.ENDED
            ) or (
                event.call.call_id != intent.call_id
                and event.call.state is not CallState.ENDED
            ):
                self.clear()

    def install(self, update: Update) -> bool:
        """Only the post-outcome exact read can lift explicit-end media suppression."""
        if not update.operation.startswith('call-reconcile:end:'):
            return False
        intent, event = self.intent, update.event
        if intent is None or update.operation != intent.read_operation:
            return True
        current = self.controller.calls.current
        if (
            not self._current(intent)
            or update.generation != intent.generation
            or not self.controller.read_is_current(update)
            or not isinstance(event, CallsStateEvent)
            or event.epoch != intent.epoch
            or event.revision is None
            or event.revision <= intent.revision
            or (current is not None and current.call_id != intent.call_id)
        ):
            self.clear()
            return True
        source = next(
            (item for item in event.calls if item.call_id == intent.call_id), None
        )
        if (
            source is None
            or source.peer != intent.peer
            or not source.owned
            or any(
                item.call_id != intent.call_id and item.state is not CallState.ENDED
                for item in event.calls
            )
        ):
            self.clear()
            return True
        calls = self.controller.calls
        if source.state is not CallState.ENDED and calls._ending_id == intent.call_id:
            calls._ending_id = None
        calls.current = source
        calls.status = (
            '' if source.state is CallState.ENDED else 'Call is still ongoing'
        )
        calls.revision += 1
        self.clear()
        return True

    def poll(self) -> None:
        """Reads once after uncertainty; native cleanup and real failure guards remain separate."""
        intent = self.intent
        if intent is None:
            return
        if not self._current(intent):
            self.clear()
            return
        calls = self.controller.calls
        if (
            not intent.uncertain
            or intent.read_operation is not None
            or calls._operation is not None
        ):
            return
        self._serial += 1
        operation = f'call-reconcile:end:{self._serial}'
        if self.controller.submit(operation, intent.client.get_calls, background=True):
            intent.read_operation = operation
