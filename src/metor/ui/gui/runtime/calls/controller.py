"""Explicit phone Call actions and exact-client native duplex ownership."""

import secrets
import threading
import time
from typing import TYPE_CHECKING
from collections.abc import Callable

from metor.core.api import (
    CallInfo,
    CallRejectedEvent,
    CallReason,
    CallState,
    CallStateEvent,
    CallsStateEvent,
    IpcEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.audio import HeadsetAudio
from metor.ui.gui.platform.call_audio import CallHeadsetAudio
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from .media import CallMediaWorker
from .handover import CallHandover
from .reconcile import EndCallReconciliation

if TYPE_CHECKING:
    from ..controller import GuiController


class CallActions:
    """Keeps phone Calls separate from chat navigation and Voice message staging."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates inert presentation; no audio opens before accepted Core authority."""
        self.controller = controller
        self.current: CallInfo | None = None
        self.worker: CallMediaWorker | None = None
        self.visible = False
        self.revision = 0
        self.status = ''
        self._operation: tuple[str, str] | None = None
        self._serial = 0
        self._snapshot_at = 0.0
        self._snapshot_pending = False
        self._checking_id: str | None = None
        self._media_failed_id: str | None = None
        self._ending_id: str | None = None
        self._handover = CallHandover(controller)
        self._end_reconciliation = EndCallReconciliation(controller)

    def show(self, call_id: str) -> bool:
        """Opens only the current ongoing Call's controls without an SDK operation."""
        current = self.current
        if (
            current is None
            or current.call_id != call_id
            or current.state is CallState.ENDED
            or not (current.owned or current.state is CallState.INCOMING)
        ):
            return False
        self.visible = True
        self.revision += 1
        return True

    def handover(self, call_id: str, canonical_peer: str) -> bool:
        """Continues an explicit end-and-call choice only through confirmed current state."""
        return self._handover.request(call_id, canonical_peer)

    def cover(self) -> None:
        """Cancels continuation and expanded controls while preserving accepted Call media."""
        self._handover.cancel()
        self._end_reconciliation.clear()
        if self.current is not None and self.current.state is not CallState.INCOMING:
            self.visible = False
            self.revision += 1

    @property
    def active(self) -> bool:
        """Reports accepted same-client authority independently of native startup."""
        return bool(
            self.current is not None
            and self.current.owned
            and self.current.state is CallState.ACTIVE
        )

    @property
    def media_active(self) -> bool:
        """Reports native input/output ownership until both directions finish cleanup."""
        return self.worker is not None and not self.worker.done.is_set()

    @property
    def ready(self) -> bool:
        """Requires selected microphone/output endpoints to match the installed audio route."""
        voice = self.controller.voice
        audio = voice.audio
        return (
            isinstance(audio, HeadsetAudio)
            and voice.routes.input is not None
            and voice.routes.output is not None
            and audio.input_device == voice.routes.input
            and audio.output_device == voice.routes.output
        )

    def _request(
        self, action: str, call_id: str, run: Callable[[], IpcEvent | None]
    ) -> bool:
        """Submits an exact immutable Call operation with no chat route transition."""
        if self._operation is not None or self.controller.client is None:
            return False
        self._serial += 1
        operation = f'call:{action}:{self._serial}'
        if not self.controller.submit(operation, run):
            return False
        self._operation = operation, call_id
        self.status = {'start': 'Calling…', 'accept': 'Accepting…'}.get(action, '')
        if action not in {'end', 'mute'}:
            self.visible = True
        self.revision += 1
        return True

    def start(self, peer: str) -> bool:
        """Explicitly requests telephone audio without granting or switching LIVE chat."""
        controller = self.controller
        if controller.state.covered:
            return False
        if self._handover.pending is not None:
            return False
        if (
            controller.simulator
            or controller.client is None
            or 'calls' not in controller.state.capabilities
        ):
            self.status = 'Calls are unavailable'
            self.visible = True
            self.revision += 1
            return False
        if self._checking_id is not None:
            self.status = 'Checking call status…'
            self.visible = True
            self.revision += 1
            return False
        if self.current is not None and self.current.state is not CallState.ENDED:
            self.visible = True
            self.revision += 1
            return False
        if not self.ready:
            self.visible = False
            self.status = 'Choose a microphone and audio output before calling'
            self.revision += 1
            return False
        self.current = None
        controller.voice.depart()
        controller.playback.stop()
        client = controller.client
        call_id = secrets.token_hex(GuiLimits.MESSAGE_ID_BYTES)
        return self._request('start', call_id, lambda: client.start_call(peer, call_id))

    def accept(self, call_id: str) -> bool:
        """Accepts only this incoming phone Call; locked chat remains covered."""
        controller, current = self.controller, self.current
        if (
            current is None
            or current.call_id != call_id
            or current.state is not CallState.INCOMING
        ):
            return False
        if controller.state.covered and (not controller.security.accept_calls_locked):
            self.status = 'Unlock to accept this call'
            self.revision += 1
            return False
        if not self.ready:
            self.status = (
                'Unlock and choose a microphone and audio output before accepting'
            )
            self.revision += 1
            return False
        client = controller.client
        if client is None:
            return False
        controller.voice.depart()
        controller.playback.stop()
        return self._request('accept', call_id, lambda: client.accept_call(call_id))

    def reject(self, call_id: str) -> bool:
        """Declines an exact incoming Call without ending an existing LIVE chat."""
        current, client = self.current, self.controller.client
        if current is None or client is None or current.call_id != call_id:
            return False
        return self._request('reject', call_id, lambda: client.reject_call(call_id))

    def end(self) -> bool:
        """Cancels before acceptance or hangs up accepted audio, retaining chat context."""
        current, client = self.current, self.controller.client
        if current is None or client is None or not current.owned:
            return False
        call_id, active = current.call_id, current.state is CallState.ACTIVE

        def run() -> IpcEvent | None:
            """Ends only the immutable displayed Call identity."""
            return (
                client.hangup_call(call_id) if active else client.cancel_call(call_id)
            )

        if not self._request('end', call_id, run):
            return False
        self._ending_id = call_id
        if self.worker is not None:
            self.worker.stop()
        assert self._operation is not None
        self._end_reconciliation.begin(
            self._operation[0], call_id, current.peer, client
        )
        return True

    def mute(self) -> bool:
        """Changes only the accepted Call microphone and preserves it across App-Lock."""
        current, client = self.current, self.controller.client
        if current is None or client is None or not self.active:
            return False
        muted = not current.muted
        if muted and self.worker is not None:
            self.worker.mute(True)
        return self._request(
            'mute', current.call_id, lambda: client.mute_call(current.call_id, muted)
        )

    def observe(self, event: IpcEvent) -> None:
        """Installs lifecycle metadata; broadcasts never invent same-client authority."""
        if not isinstance(event, CallStateEvent):
            return
        self._handover.observe(event)
        self._end_reconciliation.observe(event)
        source = event.call
        if (
            source.call_id in {self._media_failed_id, self._ending_id}
            and source.state is not CallState.ENDED
        ):
            return
        prior = self.current
        if source == prior:
            return
        if (
            prior is not None
            and prior.call_id == source.call_id
            and prior.owned
            and not source.owned
            and source.state is not CallState.ENDED
        ):
            # Broadcast metadata requires a same-client projection before media changes.
            self._snapshot_at = 0.0
            return
        if not source.owned and source.state not in {
            CallState.INCOMING,
            CallState.ENDED,
        }:
            if (
                prior is not None
                and prior.call_id == source.call_id
                and prior.state is CallState.INCOMING
            ):
                self.current = None
                self.visible = False
                self.status = ''
                self.revision += 1
            return
        if source.state is CallState.ENDED and (
            prior is None or prior.call_id != source.call_id
        ):
            return
        self.current = source
        if source.state is CallState.INCOMING or (
            not self.controller.state.covered
            and (prior is None or prior.call_id != source.call_id)
        ):
            self.visible = True
        self.status = ''
        if source.state is not CallState.ACTIVE and self.worker is not None:
            self.worker.stop()
        elif self.worker is not None:
            self.worker.mute(source.muted)
        self.revision += 1

    def install(self, update: Update) -> bool:
        """Installs correlated operations and projections without repeating unknown starts."""
        if update.generation != self.controller.state.generation:
            return False
        if self._handover.install(update):
            return True
        if self._end_reconciliation.install(update):
            return True
        if update.operation == 'call-snapshot':
            self._snapshot_pending = False
            if self._handover.pending is not None or self._end_reconciliation.pending:
                return True
            if isinstance(update.event, CallsStateEvent):
                self._checking_id = None
                source = next(
                    (
                        item
                        for item in update.event.calls
                        if item.state is not CallState.ENDED
                        and item.call_id != self._media_failed_id
                        and (item.owned or item.state is CallState.INCOMING)
                    ),
                    None,
                )
                if source is None and self.current is not None:
                    source = next(
                        (
                            item
                            for item in update.event.calls
                            if item.call_id == self.current.call_id
                            and item.state is CallState.ENDED
                        ),
                        None,
                    )
                if source is not None:
                    if source != self.current:
                        self.observe(CallStateEvent(source))
                elif (
                    self.current is not None
                    and self.current.state is not CallState.ENDED
                ):
                    if self.worker is not None:
                        self.worker.stop()
                    self.current = None
                    self.visible = False
                    self.revision += 1
            return True
        if update.operation.startswith('call-media-'):
            if update.operation.startswith('call-media-error:'):
                self._media_failed_id = update.operation.split(':', 1)[1]
            if update.status:
                self.status = update.status
                self.revision += 1
            return True
        if not update.operation.startswith('call:'):
            return False
        operation = self._operation
        if operation is None or operation[0] != update.operation:
            return True
        self._operation = None
        if (
            isinstance(update.event, CallStateEvent)
            and update.event.call.call_id == operation[1]
        ):
            self.observe(update.event)
        elif isinstance(update.event, CallRejectedEvent):
            self.status = {
                CallReason.UNSUPPORTED: 'This peer does not support phone calls',
                CallReason.BUSY: 'Another call is already in progress',
                CallReason.TIMEOUT: 'Call request expired',
                CallReason.NOT_OWNER: 'This client does not own the call',
            }.get(update.event.reason, 'Call action was not permitted')
            self.revision += 1
        else:
            if update.event is None:
                self._checking_id = operation[1]
            self.status = (
                'Checking call status…'
                if update.event is None
                else 'Call action was not permitted'
            )
            self._snapshot_at = 0.0
            self.revision += 1
        self._handover.end_result(update)
        self._end_reconciliation.end_result(update)
        return True

    def poll(self) -> bool:
        """Starts accepted duplex only after message-media cleanup and refreshes exact grants."""
        changed = False
        if self.worker is not None and self.worker.done.is_set():
            self.worker = None
            changed = True
        changed = self._handover.poll() or changed
        self._end_reconciliation.poll()
        if (
            self.active
            and self.worker is None
            and self.ready
            and self.current is not None
            and self.current.call_id != self._media_failed_id
            and self.current.call_id != self._ending_id
        ):
            controller = self.controller
            if not controller.voice.running and not controller.playback.running:
                client = controller.client
                current = self.current
                assert client is not None and current is not None
                routes = controller.voice.routes
                assert routes.input is not None and routes.output is not None
                self.worker = CallMediaWorker(
                    client,
                    current.call_id,
                    CallHeadsetAudio(routes.input, routes.output),
                    controller.mailbox,
                    controller.state.generation,
                    muted=current.muted,
                )
                self.worker.start()
                changed = True
        now = time.monotonic()
        controller, client = self.controller, self.controller.client
        if (
            client is not None
            and self._handover.pending is None
            and not self._end_reconciliation.pending
            and 'calls' in controller.state.capabilities
            and not self._snapshot_pending
            and now - self._snapshot_at >= GuiLimits.CALL_SNAPSHOT_SECONDS
            and controller.submit('call-snapshot', client.get_calls, background=True)
        ):
            self._snapshot_pending = True
            self._snapshot_at = now
        return changed

    def suspend(self) -> None:
        """Ends phone audio on system suspend; screen-off/App-Lock do not call this."""
        self.clear()

    def clear(self) -> None:
        """Stops native media and releases exact owned Call authority before client loss."""
        current, client = self.current, self.controller.client
        ending = (
            self._operation is not None
            and self._operation[0].startswith('call:end:')
            and current is not None
            and self._operation[1] == current.call_id
        )
        self._handover.cancel()
        self._end_reconciliation.clear()
        if current is not None:
            self._media_failed_id = current.call_id
        if self.worker is not None:
            self.worker.stop()
        if (
            current is not None
            and current.owned
            and current.state is not CallState.ENDED
            and client is not None
            and not ending
        ):
            call_id, active = current.call_id, current.state is CallState.ACTIVE

            def terminate() -> None:
                """Makes one best-effort exact teardown; Core also fences client closure."""
                try:
                    if active:
                        client.hangup_call(call_id)
                    else:
                        client.cancel_call(call_id)
                except Exception:
                    return

            threading.Thread(
                target=terminate, name='metor-call-cleanup', daemon=True
            ).start()
        self.current = None
        self.visible = False
        self._checking_id = None
        self._operation = None
        self._snapshot_pending = False
        self.status = ''
        self.revision += 1
