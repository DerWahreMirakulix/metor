"""Current Core facts projected into a volatile notification center without previews."""

from collections.abc import Iterator
import hashlib
import json
import time
from typing import TYPE_CHECKING

from metor.core.api import (
    AutoFallbackQueuedEvent,
    ConnectionRetryEvent,
    FallbackSuccessEvent,
    IpcEvent,
    RuntimeSnapshotEvent,
    InboxNotificationEvent,
    NotificationPrivacy,
    Delivery,
    MessageReceivedEvent,
    VoiceIncomingStartedEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route
from metor.ui.gui.state.notifications import Notice, NoticeKind, NotificationStore

if TYPE_CHECKING:
    from .controller import GuiController


def fingerprint(values: tuple[object, ...]) -> str:
    """Bounds exact source-state identity without keeping arbitrary details.

    Args:
        values: Permitted canonical generation/count facts only.
    Returns:
        str: Fixed-size local dismissal identity.
    """
    return hashlib.sha256(json.dumps(values).encode('utf-8')).hexdigest()


class Notifications:
    """Derives current actionable facts and consumes no text or Voice payload."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates a profile-scoped volatile model, not a durable notification database.

        Args:
            controller: Current authorized public-service state.
        Returns:
            None
        """
        self.controller = controller
        self.store = NotificationStore()
        self._snapshot: RuntimeSnapshotEvent | None = None
        self._revision = -1
        self.locked_activity: set[Delivery] = set()
        self._open_after_unlock = False

    def begin_lock(self) -> None:
        """Resets only the permitted current-cycle cue without manufacturing a historical count.

        Args:
            None
        Returns:
            None
        """
        self.locked_activity.clear()
        self._open_after_unlock = False

    def open_locked(self) -> None:
        """Requests normal reauthorization before opening current notification state.

        Args:
            None
        Returns:
            None
        """
        if not self.locked_activity or not self.controller.state.covered:
            return
        self._open_after_unlock = True
        self.controller.state.status = 'Unlock to view notifications'

    def poll(self) -> bool:
        """Reconciles current facts only under normal authorization.

        Args:
            None
        Returns:
            bool: Whether notification presentation changed.
        """
        state = self.controller.state
        snapshot = state.snapshot
        if not state.covered and snapshot is not None and self._open_after_unlock:
            self._open_after_unlock = False
            self.controller.navigate(Route('V16'))
        if (
            not state.covered
            and snapshot is not None
            and snapshot is not self._snapshot
        ):
            self._snapshot = snapshot
            self.store.reconcile(self._facts(snapshot))
        changed = self._revision != self.store.revision
        self._revision = self.store.revision
        return changed

    def _facts(self, snapshot: RuntimeSnapshotEvent) -> Iterator[Notice]:
        """Streams candidate notices without copying an entire large contact/state list.

        Args:
            snapshot: Current authoritative public projection.
        Returns:
            Iterator[Notice]: Content-free fact candidates.
        """
        for drop in snapshot.conversations:
            if drop.unread_count:
                yield Notice(
                    NoticeKind.DROP,
                    drop.onion,
                    fingerprint(
                        (
                            snapshot.epoch,
                            drop.unread_count,
                            self.store.source_hints.get((NoticeKind.DROP, drop.onion)),
                        )
                    ),
                    drop.unread_count,
                )
        for live in snapshot.live_contexts:
            if live.unseen_count:
                yield Notice(
                    NoticeKind.LIVE,
                    live.onion,
                    fingerprint(
                        (
                            snapshot.epoch,
                            live.context_generation,
                            live.unseen_count,
                            self.store.source_hints.get((NoticeKind.LIVE, live.onion)),
                        )
                    ),
                    live.unseen_count,
                )
            if (
                live.pending_outbound_count
                and live.session_state == 'disconnected'
                and not live.recovery_eligible
            ):
                yield Notice(
                    NoticeKind.PENDING,
                    live.onion,
                    fingerprint(
                        (
                            snapshot.epoch,
                            live.context_generation,
                            live.pending_outbound_count,
                        )
                    ),
                    live.pending_outbound_count,
                )
        for call in snapshot.pending:
            if call.onion:
                yield Notice(
                    NoticeKind.CALL,
                    call.onion,
                    fingerprint((snapshot.epoch, call.action_handle, call.expires_at)),
                )

    def observe(self, event: IpcEvent) -> None:
        """Admits only enumerated non-content observations from current authorized events.

        Args:
            event: Current-generation typed event; message bodies are never inspected.
        Returns:
            None
        """
        if self.controller.state.covered:
            security = self.controller.security
            if (
                security.restriction is not None
                and security.notification_privacy is not NotificationPrivacy.OFF
                and isinstance(event, InboxNotificationEvent)
            ):
                self.locked_activity.add(event.delivery)
            return
        if (
            isinstance(
                event,
                (
                    InboxNotificationEvent,
                    MessageReceivedEvent,
                    VoiceIncomingStartedEvent,
                ),
            )
            and event.onion
        ):
            source = (
                event.source_id
                if isinstance(event, InboxNotificationEvent)
                else event.msg_id
            )
            if source:
                kind = (
                    NoticeKind.DROP
                    if event.delivery is Delivery.DROP
                    else NoticeKind.LIVE
                )
                self.store.hint((kind, event.onion), fingerprint((event.epoch, source)))
        if (
            isinstance(event, (FallbackSuccessEvent, AutoFallbackQueuedEvent))
            and event.onion
        ):
            self.store.put(
                Notice(
                    NoticeKind.FALLBACK,
                    event.onion,
                    fingerprint(
                        (
                            event.epoch,
                            event.revision,
                            event.msg_ids
                            if isinstance(event, FallbackSuccessEvent)
                            else event.msg_id,
                        )
                    ),
                    event.count if isinstance(event, FallbackSuccessEvent) else 1,
                    actionable=False,
                )
            )
        elif isinstance(event, ConnectionRetryEvent) and event.onion:
            source = fingerprint((event.epoch, event.revision))
            prior = self.store.items.get((NoticeKind.UNSTABLE, event.onion))
            if prior and prior.source == source:
                return
            coalesce = (
                prior is not None
                and time.time() - prior.created_at
                <= GuiLimits.NOTIFICATION_COALESCE_SECONDS
            )
            self.store.put(
                Notice(
                    NoticeKind.UNSTABLE,
                    event.onion,
                    source,
                    min(prior.count + 1, GuiLimits.LIVE_ITEMS)
                    if prior and coalesce
                    else 1,
                    actionable=False,
                    created_at=prior.created_at if prior and coalesce else 0,
                )
            )

    def open(self, key: tuple[NoticeKind, str]) -> None:
        """Navigates to current permitted context without accepting, reconnecting or consuming Voice.

        Args:
            key: Explicitly activated center entry.
        Returns:
            None
        """
        state = self.controller.state
        entry, snapshot = self.store.items.get(key), state.snapshot
        if entry is None or snapshot is None or state.covered:
            return
        peers = (
            {item.onion for item in snapshot.conversations}
            | {item.onion for item in snapshot.live_contexts}
            | {item.onion for item in snapshot.pending}
        )
        if entry.peer not in peers:
            self.store.dismiss({key})
            state.status = 'Item no longer available'
            return
        if entry.kind is NoticeKind.CALL:
            call = next(
                (item for item in snapshot.pending if item.onion == entry.peer), None
            )
            if call is not None and call.action_handle is not None:
                self.controller.calls.show(call.action_handle)
                return
        self.controller.navigate(
            Route(
                'V08' if entry.delivery.value == 'drop' else 'V09',
                entry.peer,
                entry.delivery,
            )
        )
