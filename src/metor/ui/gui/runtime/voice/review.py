"""Exact-ID DROP review actions and reconciliation of uncertain commit outcomes."""

from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    GetMessageOutcomeCommand,
    MessageDirectionCode,
    MessageOutcomeEvent,
    MessageStatusCode,
    VoiceCancelledEvent,
    VoiceCommittedEvent,
)
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from .controller import VoiceController


class ReviewActions:
    """Uses the existing recording identity and Core lease for every review action."""

    def __init__(self, voice: 'VoiceController') -> None:
        """Binds review commands to their volatile current-activation metadata.

        Args:
            voice: GUI recording and review presentation owner.
        Returns:
            None
        """
        self.voice = voice
        self._checks: set[str] = set()

    def act(self, peer: str, *, send: bool) -> bool:
        """Explicitly commits or cancels one known owned DROP review.

        Args:
            peer: Canonical review peer captured by the control.
            send: True commits the existing ID; False cancels it.
        Returns:
            bool: Whether the exact action was admitted.
        """
        controller = self.voice.controller
        review = self.voice.reviews.get(peer)
        client, owner = controller.client, controller.voice_owner.token
        if (
            review is None
            or review.unknown
            or client is None
            or owner is None
            or controller.state.covered
            or self.voice.press.active
        ):
            return False
        binding = review.binding
        if binding.generation != controller.state.generation:
            return False
        kind = 'commit' if send else 'cancel'
        return controller.submit(
            'review:' + kind + ':' + binding.msg_id,
            lambda: (
                client.commit_voice(peer, binding.msg_id, owner_token=owner)
                if send
                else client.cancel_voice(peer, binding.msg_id, owner_token=owner)
            ),
        )

    def check(self, peer: str) -> bool:
        """Reads the exact receipt without retrying a send or discarding uncertain data.

        Args:
            peer: Canonical review peer.
        Returns:
            bool: Whether read-only reconciliation was admitted.
        """
        controller = self.voice.controller
        review = self.voice.reviews.get(peer)
        client = controller.client
        if review is None or client is None or controller.state.covered:
            return False
        binding = review.binding
        return controller.submit(
            'review:check:' + binding.msg_id,
            lambda: client.request(
                GetMessageOutcomeCommand(
                    peer, binding.msg_id, MessageDirectionCode.OUT
                ),
                MessageOutcomeEvent,
            ),
        )

    def poll(self) -> None:
        """Schedules one bounded reconciliation after an unconfirmed mutation.

        Args:
            None
        Returns:
            None
        """
        if not self._checks:
            return
        peer = next(iter(self._checks))
        if peer not in self.voice.reviews or self.check(peer):
            self._checks.discard(peer)

    def install(self, update: Update) -> bool:
        """Applies positive exact results and preserves unknown-result barriers.

        Args:
            update: Current-generation operation response.
        Returns:
            bool: Whether the update belongs to DROP review orchestration.
        """
        if not update.operation.startswith('review:'):
            return False
        _, kind, msg_id = update.operation.split(':', 2)
        review = next(
            (
                review
                for review in self.voice.reviews.values()
                if review.binding.msg_id == msg_id
            ),
            None,
        )
        if review is None:
            return True
        peer = review.binding.peer
        event = update.event
        confirmed = (
            isinstance(event, (VoiceCommittedEvent, VoiceCancelledEvent))
            and event.msg_id == msg_id
            and event.onion == peer
        )
        if (
            isinstance(event, MessageOutcomeEvent)
            and event.msg_id == msg_id
            and event.onion == peer
            and event.direction is MessageDirectionCode.OUT
            and event.delivery is Delivery.DROP
        ):
            if event.status is MessageStatusCode.DRAFT:
                review.unknown = False
                self.voice.controller.state.status = 'Recording is still unsent'
                return True
            confirmed = event.status in {
                MessageStatusCode.PENDING,
                MessageStatusCode.DELIVERED,
                MessageStatusCode.READ,
            }
        if confirmed:
            playback = self.voice.controller.playback
            target = playback.target(
                peer, Delivery.DROP, MessageDirectionCode.OUT, msg_id, review=True
            )
            if target is not None:
                playback.cache.discard(target)
            self.voice.reviews.pop(peer, None)
            self._checks.discard(peer)
            self.voice.controller.state.status = (
                'Recording deleted'
                if isinstance(event, VoiceCancelledEvent)
                else 'Drop read'
                if isinstance(event, MessageOutcomeEvent)
                and event.status is MessageStatusCode.READ
                else 'Drop delivered'
                if isinstance(event, MessageOutcomeEvent)
                and event.status is MessageStatusCode.DELIVERED
                else 'Drop queued'
            )
            self.voice.controller.refresh_state()
        else:
            review.unknown = True
            self.voice.controller.state.status = (
                'Recording outcome is unconfirmed. Recheck before sending again.'
            )
            if kind != 'check':
                self._checks.add(peer)
        return True
