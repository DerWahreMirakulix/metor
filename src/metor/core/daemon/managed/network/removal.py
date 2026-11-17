"""Atomic ended LIVE context removal with explicitly requested pending cancellation."""

import threading
from collections.abc import Callable

from metor.core.api import MessageOperationReason
from metor.data import MessageManager, PendingLiveRecord

# Local Package Imports
from .state import StateTracker


class LiveContextRemoval:
    """Serializes ended-state admission, durable cancellation and transport fencing."""

    def __init__(
        self,
        messages: MessageManager,
        state: StateTracker,
        operation_lock: threading.RLock,
        recovering: Callable[[str], bool],
        cancel_voice: Callable[[str, list[PendingLiveRecord]], None],
        dismiss_voice: Callable[[str], None],
    ) -> None:
        """Captures the existing lifecycle owners without creating delivery policy."""
        self._messages, self._state = messages, state
        self._operation_lock, self._recovering = operation_lock, recovering
        self._cancel_voice, self._dismiss_voice = cancel_voice, dismiss_voice

    def dismiss(
        self, onion: str, cancel_pending: bool
    ) -> tuple[MessageOperationReason | None, int]:
        """Removes exact ended peer state without touching Drops or unpublished drafts.

        The shared operation and transport barriers exclude connection admission,
        replay, fallback and final writer claims while the durable spool changes.
        Existing clients retain the rejection of unresolved outbound LIVE work.
        """
        with self._operation_lock:
            with self._state.snapshot_barrier():
                if self._recovering(onion):
                    return MessageOperationReason.ACTIVE_LIVE_CONTEXT, 0
                pending = self._messages.get_pending_live_outbox(onion)
                if pending and not cancel_pending:
                    return MessageOperationReason.OUTBOUND_PENDING_LIVE, 0
                cancelled: list[PendingLiveRecord] = []
                if cancel_pending and pending:
                    result = self._messages.discard_pending_live(
                        onion, [record.msg_id for record in pending]
                    )
                    if result is None:
                        return MessageOperationReason.INVALID_SELECTION, 0
                    cancelled = result
                    msg_ids = [record.msg_id for record in cancelled]
                    self._state.invalidate_live_generations(onion, msg_ids)
                    for msg_id in msg_ids:
                        self._state.remove_unacked_message(onion, msg_id)
                    self._state.forget_cancelled_live_requests(onion, msg_ids)
                removed = self._messages.dismiss_inbound_live(onion)
                self._state.forget_ended_live_context(onion)
            if cancelled:
                self._cancel_voice(onion, cancelled)
            self._dismiss_voice(onion)
            return None, removed + len(cancelled)
