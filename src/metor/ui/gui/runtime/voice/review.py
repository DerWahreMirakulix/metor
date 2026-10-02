"""Exact-ID DROP/LIVE review actions and reconciliation of uncertain commit outcomes."""

from typing import TYPE_CHECKING

from metor.core.api import (
    Delivery,
    GetMessageOutcomeCommand,
    MessageDirectionCode,
    MessageOutcomeEvent,
    MessageStatusCode,
    VoiceCancelledEvent,
    VoiceCommittedEvent,
    VoiceOperationRejectedEvent,
)
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.state.media import PlaybackTarget
from metor.ui.gui.constants import GuiLimits

# Local Package Imports
from .models import LocalVoiceTurn, VoiceReview

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

    def act(self, peer: str, *, send: bool, delivery: Delivery | None = None) -> bool:
        """Explicitly publishes or cancels an exact owned message review.

        Args:
            peer: Canonical review peer captured by the control.
            send: True publishes the existing ID; False cancels it.
            delivery: Explicit DROP conversion, or the recording's original mode.
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
        selected = delivery or binding.delivery
        if selected not in {binding.delivery, Delivery.DROP}:
            return False
        if send and selected is Delivery.LIVE and not self.live_ready(review):
            controller.state.status = (
                'Reconnect this Live chat or send the recording as Drop'
            )
            return False
        kind = 'commit' if send else 'cancel'
        return controller.submit(
            'review:' + kind + ':' + binding.msg_id,
            lambda: (
                client.commit_voice(
                    peer,
                    binding.msg_id,
                    owner_token=owner,
                    delivery=selected,
                    context_generation=binding.context_generation,
                )
                if send
                else client.cancel_voice(peer, binding.msg_id, owner_token=owner)
            ),
        )

    def live_ready(self, review: VoiceReview) -> bool:
        """Checks the original chat identity without authorizing or opening a transport.

        Args:
            review: Exact draft whose target cannot follow a replaced chat.
        Returns:
            bool: Whether the same confirmed logical chat can publish now.
        """
        snapshot = self.voice.controller.state.snapshot
        return bool(
            snapshot
            and review.binding.context_generation is not None
            and any(
                item.onion == review.binding.peer
                and item.context_generation == review.binding.context_generation
                and item.session_state == 'connected'
                for item in snapshot.live_contexts
            )
        )

    def _publish_cache(self, staged: PlaybackTarget) -> None:
        """Retains confirmed local replay bytes only after actual LIVE publication.

        Args:
            staged: Exact-owner preview cache identity.
        Returns:
            None
        """
        cache = self.voice.controller.playback.cache
        size = cache.complete_size(staged)
        if size is None:
            return
        published = PlaybackTarget(
            staged.generation,
            staged.profile_instance,
            staged.epoch,
            staged.peer,
            Delivery.LIVE,
            staged.direction,
            staged.msg_id,
        )
        offset = 0
        while offset < size:
            retained = cache.read(staged, offset, GuiLimits.MEDIA_CACHE_BLOCK_BYTES)
            if retained is None:
                return
            payload, _size = retained
            if not payload:
                return
            if not cache.append(published, offset, payload, complete=False):
                return
            offset += len(payload)
        cache.mark_complete(published, size)

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
            background=True,
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
            bool: Whether the update belongs to message review orchestration.
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
        if (
            isinstance(event, VoiceOperationRejectedEvent)
            and event.msg_id == msg_id
            and event.onion == peer
        ):
            review.unknown = False
            self.voice.controller.state.status = (
                'Recording remains unsent. Reconnect or explicitly send as Drop.'
                if review.binding.delivery is Delivery.LIVE
                else 'Recording remains unsent'
            )
            return True
        if confirmed:
            playback = self.voice.controller.playback
            target = playback.target(
                peer,
                review.binding.delivery,
                MessageDirectionCode.OUT,
                msg_id,
                review=True,
            )
            delivery = (
                event.delivery
                if isinstance(event, (VoiceCommittedEvent, MessageOutcomeEvent))
                else review.binding.delivery
            )
            if delivery is Delivery.LIVE and not isinstance(event, VoiceCancelledEvent):
                self.voice.live_turns[msg_id] = LocalVoiceTurn(
                    review.binding,
                    review.size_bytes,
                    review.duration_ms,
                    finalized=True,
                    order=self.voice.controller.transcript.next_order(),
                )
                if target is not None:
                    self._publish_cache(target)
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
                else 'Live voice message sent'
                if delivery is Delivery.LIVE
                else 'Drop queued'
            )
            if (
                delivery is Delivery.DROP
                and review.binding.delivery is Delivery.LIVE
                and not isinstance(event, VoiceCancelledEvent)
                and self.voice.controller.state.route
                == Route('V09', peer, Delivery.LIVE)
            ):
                self.voice.controller.navigate(Route('V08', peer, Delivery.DROP))
            self.voice.controller.refresh_state()
        else:
            review.unknown = True
            self.voice.controller.state.status = (
                'Recording outcome is unconfirmed. Recheck before sending again.'
            )
            if kind != 'check':
                self._checks.add(peer)
        return True
