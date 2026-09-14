"""Foreground-only automatic playback eligibility and bounded logical-context overrides."""

from collections import deque
from typing import TYPE_CHECKING

from metor.core.api import Delivery, MessageDirectionCode, VoiceIncomingStartedEvent
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state.media import PlaybackTarget

if TYPE_CHECKING:
    from .controller import PlaybackController


class AutoPlayback:
    """Queues only newly beginning eligible turns and never promotes old backlog."""

    def __init__(self, playback: 'PlaybackController') -> None:
        """Creates an Off-by-default context map with no inferred foreground permission.

        Args:
            playback: Single-output arbitration owner.
        Returns:
            None
        """
        self.playback = playback
        self.focused = True
        self.overrides: dict[tuple[str, int], bool] = {}
        self.queue: deque[tuple[PlaybackTarget, tuple[str, int]]] = deque()
        self.manual = False

    def context(self, peer: str) -> tuple[str, int] | None:
        """Resolves an existing logical context without starting communication.

        Args:
            peer: Canonical route peer.
        Returns:
            tuple[str, int] | None: Public logical generation, or unavailable context.
        """
        controller = self.playback.controller
        if controller.state.covered:
            scope = controller.security.continuation.scope
            return (
                (scope.peer, scope.context_generation)
                if scope is not None and scope.peer == peer
                else None
            )
        snapshot = controller.state.snapshot
        entry = (
            next((item for item in snapshot.live_contexts if item.onion == peer), None)
            if snapshot
            else None
        )
        if entry is None or entry.context_generation is None:
            return None
        return peer, entry.context_generation

    def reconcile(self) -> None:
        """Copies the protected default only when a new logical context first appears.

        Args:
            None
        Returns:
            None
        """
        state = self.playback.controller.state
        snapshot = state.snapshot
        if state.covered or snapshot is None:
            return
        keys = {
            (entry.onion, entry.context_generation)
            for entry in snapshot.live_contexts
            if entry.context_generation is not None
        }
        for key in tuple(self.overrides):
            if key not in keys:
                self.overrides.pop(key, None)
        default = (
            state.preferences.preferences.auto_play if state.preferences else False
        )
        for key in keys:
            if len(self.overrides) < GuiLimits.LIVE_ITEMS:
                self.overrides.setdefault(key, default)

    def enabled(self, peer: str) -> bool:
        """Reads the current context override without mutating the protected default.

        Args:
            peer: Canonical route peer.
        Returns:
            bool: Whether this logical context's override is On.
        """
        key = self.context(peer)
        return self.overrides.get(key, False) if key is not None else False

    def toggle(self, peer: str) -> None:
        """Changes only this logical context and leaves existing backlog silent.

        Args:
            peer: Explicitly selected context peer.
        Returns:
            None
        """
        self.reconcile()
        key = self.context(peer)
        if key is not None and key in self.overrides:
            self.overrides[key] = not self.overrides[key]
            if not self.overrides[key]:
                self.queue.clear()
                if not self.manual:
                    self.playback.stop()

    def eligible(self, target: PlaybackTarget) -> bool:
        """Checks foreground, exact projection and current context policy.

        Args:
            target: Exact newly beginning incoming turn.
        Returns:
            bool: Whether automatic output is currently permitted.
        """
        state = self.playback.controller.state
        if state.covered:
            scope = self.playback.controller.security.continuation.scope
            return bool(
                scope is not None
                and scope.session_state not in {'disconnected', 'pending'}
                and self.focused
                and self.playback.audio is not None
                and scope.peer == target.peer
                and target.delivery is Delivery.LIVE
                and target.direction is MessageDirectionCode.IN
                and self.enabled(target.peer)
            )
        snapshot = state.snapshot
        active = bool(
            snapshot
            and any(
                entry.onion == target.peer
                and (entry.session_state == 'connected' or entry.recovery_eligible)
                for entry in snapshot.live_contexts
            )
        )
        return (
            not state.covered
            and active
            and self.focused
            and self.playback.audio is not None
            and state.route.view == 'V09'
            and state.route.peer == target.peer
            and state.route.delivery is Delivery.LIVE
            and target.delivery is Delivery.LIVE
            and self.enabled(target.peer)
        )

    def incoming(self, event: VoiceIncomingStartedEvent) -> None:
        """Admits a new turn at its beginning; returning to a view never calls this.

        Args:
            event: Ordered public event for one newly beginning incoming turn.
        Returns:
            None
        """
        if not event.onion or event.next_offset != 0:
            return
        target = self.playback.target(
            event.onion, event.delivery, MessageDirectionCode.IN, event.msg_id
        )
        if (
            target is None
            or not self.eligible(target)
            or self.manual
            and self.playback.running
        ):
            return
        if len(self.queue) < GuiLimits.PLAYBACK_QUEUE:
            context = self.context(target.peer)
            if context is not None:
                self.queue.append((target, context))

    def poll(self) -> None:
        """Starts the next eligible turn in stable order after output ownership ends.

        Args:
            None
        Returns:
            None
        """
        self.reconcile()
        if self.playback.running:
            return
        self.manual = False
        while self.queue:
            target, context = self.queue.popleft()
            if self.eligible(target) and context == self.context(target.peer):
                self.playback.play(target, automatic=True)
                return
