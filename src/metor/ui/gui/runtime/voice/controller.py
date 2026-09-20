"""GUI PTT eligibility, bounded review state and generation-safe capture results."""

from dataclasses import asdict, dataclass
import json
import secrets
from typing import TYPE_CHECKING

from metor.client.platform import CapturePort
from metor.core.api import (
    Delivery,
    MessageDirectionCode,
    MessageStatusCode,
    RetainedMessagesEvent,
    VoiceChunkAcceptedEvent,
    VoiceFinalizedEvent,
    VoiceResourceLimitEvent,
    VoiceResourcePressureEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from .capture import CaptureWorker
from .press import CaptureBinding, PressMachine, PressPhase, PressSource
from .review import ReviewActions
from .recovery import CaptureRecovery
from .routes import AudioRoutes

if TYPE_CHECKING:
    from ..controller import GuiController


@dataclass
class VoiceReview:
    """Volatile exact-owner review metadata, never a local audio file or sent message."""

    binding: CaptureBinding
    size_bytes: int
    duration_ms: int | None
    unknown: bool = False


@dataclass
class LocalVoiceTurn:
    """Stable same-runtime LIVE placeholder and canonical capture metadata."""

    binding: CaptureBinding
    size_bytes: int = 0
    duration_ms: int | None = None
    finalized: bool = False
    actual_delivery: Delivery = Delivery.LIVE
    status: MessageStatusCode = MessageStatusCode.PENDING
    order: int = 0


class VoiceController:
    """Keeps microphone interactions separate from the GUI's serial action worker."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an inert media controller without probing or opening devices.

        Args:
            controller: Public-service GUI owner for this activation.
        Returns:
            None
        """
        self.controller = controller
        self.press = PressMachine()
        self.worker: CaptureWorker | None = None
        self.audio: CapturePort | None = None
        self.headset_confirmed = False
        self.reviews: dict[str, VoiceReview] = {}
        self.live_turns: dict[str, LocalVoiceTurn] = {}
        self.accepted_bytes = 0
        self.review_actions = ReviewActions(self)
        self.recovery = CaptureRecovery(self)
        self.routes = AudioRoutes(self)

    @property
    def running(self) -> bool:
        """Reports active worker lifetime independently of displayed recording phase.

        Args:
            None
        Returns:
            bool: Whether a capture worker still owns its input port.
        """
        return self.worker is not None and not self.worker.done.is_set()

    def configure(self, audio: CapturePort, *, headset_confirmed: bool) -> bool:
        """Installs an explicitly chosen supported headset route while idle.

        Args:
            audio: Inert native route adapter.
            headset_confirmed: User confirmation of headset routing, never inferred AEC.
        Returns:
            bool: Whether the route was safely installed.
        """
        if self.running or self.press.active:
            return False
        self.audio = audio
        self.headset_confirmed = headset_confirmed
        return True

    @staticmethod
    def _turn_size(turn: LocalVoiceTurn) -> int:
        """Accounts for bounded metadata growth before admitting a capture turn.

        Args:
            turn: Exact local capture metadata.
        Returns:
            int: Serialized metadata reservation including growth headroom.
        """
        return max(
            GuiLimits.TEXT_HANDOFF_ITEM_BYTES,
            len(json.dumps(asdict(turn)).encode('utf-8')),
        )

    def presentation_usage(self) -> tuple[int, int]:
        """Counts accepted turns and the in-flight Core admission before its callback.

        Args:
            None
        Returns:
            tuple[int, int]: Aggregate capture presentation items and bytes.
        """
        count = len(self.live_turns)
        size = sum(self._turn_size(turn) for turn in self.live_turns.values())
        binding = self.press.binding
        if (
            binding is not None
            and binding.delivery is Delivery.LIVE
            and binding.msg_id not in self.live_turns
        ):
            count += 1
            size += self._turn_size(LocalVoiceTurn(binding))
        return count, size

    def _scope(self) -> tuple[str, str, str, Delivery, int | None] | None:
        """Reads a foreground or explicitly continued public media scope.

        Args:
            None
        Returns:
            tuple[str, str, str, Delivery, int | None] | None: Profile, epoch, peer, delivery and logical context.
        """
        controller, state = self.controller, self.controller.state
        if state.covered:
            scope = controller.security.continuation.scope
            if (
                scope is None
                or controller.security.restriction is None
                or controller.security.restoring
            ):
                return None
            if scope.session_state in {'disconnected', 'pending'}:
                return None
            return (
                scope.profile_instance,
                scope.epoch,
                scope.peer,
                Delivery.LIVE,
                scope.context_generation,
            )
        route, snapshot = state.route, state.snapshot
        if (
            snapshot is None
            or not snapshot.profile_instance_id
            or not snapshot.epoch
            or route.peer is None
            or route.view not in {'V08', 'V09'}
        ):
            return None
        if route.delivery is Delivery.DROP:
            return (
                snapshot.profile_instance_id,
                snapshot.epoch,
                route.peer,
                Delivery.DROP,
                None,
            )
        context = next(
            (item for item in snapshot.live_contexts if item.onion == route.peer), None
        )
        if (
            context is None
            or context.context_generation is None
            or not (context.session_state == 'connected' or context.recovery_eligible)
            or context.session_state in {'disconnected', 'pending'}
        ):
            return None
        return (
            snapshot.profile_instance_id,
            snapshot.epoch,
            route.peer,
            Delivery.LIVE,
            context.context_generation,
        )

    def available(self) -> bool:
        """Checks exact public scope, independent media readiness and aggregate capacity.

        Args:
            None
        Returns:
            bool: Whether a fresh press may attempt Core admission.
        """
        controller, state = self.controller, self.controller.state
        scope = self._scope()
        if (
            scope is None
            or controller.purge.active
            or state.busy
            or controller.client is None
            or controller.voice_owner.token is None
            or self.audio is None
            or not self.headset_confirmed
            or self.running
            or self.press.phase is not PressPhase.IDLE
            or 'disposable_voice_owner' not in state.capabilities
            or 'retained_message_identity' not in state.capabilities
        ):
            return False
        peer, delivery = scope[2], scope[3]
        if delivery is Delivery.DROP:
            return (
                peer not in self.reviews
                and len(self.reviews) < GuiLimits.REVIEW_CONTEXTS
            )
        return (
            controller.transcript.capacity()[0] > 0
            and 'live_context_identity' in state.capabilities
        )

    def down(self, source: PressSource) -> bool:
        """Binds one fresh input down to the current exact recording target.

        Args:
            source: Adapter that owns the actual physical/pointer/key identity.
        Returns:
            bool: Whether a capture admission worker started.
        """
        controller, state = self.controller, self.controller.state
        route = state.route
        scope = self._scope() or ('', '', route.peer or '', route.delivery, None)
        binding = CaptureBinding(
            scope[0],
            scope[1],
            state.generation,
            scope[2],
            scope[3],
            secrets.token_hex(GuiLimits.MESSAGE_ID_BYTES),
            scope[4],
        )
        metadata_fits = binding.delivery is Delivery.DROP or (
            self._turn_size(LocalVoiceTurn(binding))
            <= controller.transcript.capacity()[1]
        )
        if not self.press.down(source, binding, self.available() and metadata_fits):
            state.status = (
                'Send or delete this recording first'
                if route.delivery is Delivery.DROP and route.peer in self.reviews
                else 'Release PTT'
                if self.press.held
                else 'Recording is unavailable'
            )
            return False
        client, owner, audio = (
            controller.client,
            controller.voice_owner.token,
            self.audio,
        )
        assert client is not None and owner is not None and audio is not None
        self.accepted_bytes = 0
        state.status = 'Starting recording…'
        self.worker = CaptureWorker(
            client, owner, binding, audio, controller.mailbox, controller.playback.cache
        )
        self.worker.start()
        return True

    def up(self, source: PressSource) -> None:
        """Releases only the initiating source and asynchronously stops its microphone.

        Args:
            source: Source whose actual release was verified by its adapter.
        Returns:
            None
        """
        if self.press.up(source) and self.worker is not None:
            self.worker.request_stop()

    def depart(self, *, purge: bool = False) -> None:
        """Stops a bound recording on context/focus departure without retargeting it.

        Args:
            purge: Accepted Core purge preempts normal finalization.
        Returns:
            None
        """
        if self.press.depart(purge=purge) and self.worker is not None:
            self.worker.request_stop(purge=purge)

    def install(self, update: Update) -> bool:
        """Installs matching worker results while preserving the press identity barrier.

        Args:
            update: Generation-validated bounded mailbox record.
        Returns:
            bool: Whether this update belongs to local capture handling.
        """
        if (
            self.routes.install(update)
            or self.review_actions.install(update)
            or self.recovery.install(update)
        ):
            return True
        binding = self.press.binding
        event = update.event
        if binding is None:
            return update.operation.startswith('voice-')
        if (
            isinstance(event, (VoiceResourceLimitEvent, VoiceResourcePressureEvent))
            and event.msg_id == binding.msg_id
        ):
            if isinstance(event, VoiceResourceLimitEvent):
                self.depart()
                self.controller.state.status = (
                    'Voice buffer full; finishing accepted audio'
                )
            else:
                self.controller.state.status = 'Voice buffer almost full'
            return True
        if not update.operation.endswith(
            ':' + binding.msg_id
        ) or not update.operation.startswith('voice-'):
            return False
        operation = update.operation.split(':', 1)[0]
        if operation == 'voice-start':
            self.press.accepted(binding)
            if binding.delivery is Delivery.LIVE:
                self.live_turns.setdefault(
                    binding.msg_id,
                    LocalVoiceTurn(
                        binding, order=self.controller.transcript.next_order()
                    ),
                )
            self.controller.state.status = 'Recording…'
        elif operation == 'voice-progress' and isinstance(
            event, VoiceChunkAcceptedEvent
        ):
            self.accepted_bytes = event.next_offset
            if binding.msg_id in self.live_turns:
                self.live_turns[binding.msg_id].size_bytes = event.next_offset
        elif operation == 'voice-finished':
            size: int | None = None
            duration: int | None = None
            actual_delivery = binding.delivery
            if (
                isinstance(event, VoiceFinalizedEvent)
                and event.msg_id == binding.msg_id
                and event.onion == binding.peer
            ):
                size, duration = event.size_bytes, event.duration_ms
                actual_delivery = event.delivery or binding.delivery
            elif isinstance(event, RetainedMessagesEvent):
                item = next(
                    (
                        item
                        for item in event.messages
                        if item.msg_id == binding.msg_id
                        and item.onion == binding.peer
                        and item.direction is MessageDirectionCode.OUT
                        and item.finalized
                    ),
                    None,
                )
                if item is not None:
                    size, duration = item.size_bytes, item.duration_ms
                    actual_delivery = item.delivery
            if size is None:
                self.press.complete(binding, confirmed=False)
                return True
            self.accepted_bytes = size
            if binding.delivery is Delivery.DROP and size > 0:
                self.reviews[binding.peer] = VoiceReview(binding, size, duration)
            if binding.msg_id in self.live_turns:
                turn = self.live_turns[binding.msg_id]
                turn.size_bytes, turn.duration_ms, turn.finalized = size, duration, True
                turn.actual_delivery = actual_delivery
            self.press.complete(binding, confirmed=True)
            self.controller.state.status = update.status or (
                'Recording ready to review'
                if binding.delivery is Delivery.DROP and size > 0
                else 'Recording finished'
            )
        elif operation in {'voice-empty', 'voice-rejected'}:
            self.press.complete(binding, confirmed=True)
            self.controller.state.status = update.status
        elif operation == 'voice-error':
            self.press.complete(binding, confirmed=False)
            self.controller.state.status = update.status
        return True

    def abandon(self, *, purge: bool = False) -> None:
        """Stops native capture and drops departed profile presentation references.

        Args:
            purge: Accepted destructive preemption, distinct from ordinary close.
        Returns:
            None
        """
        self.depart(purge=purge)
        self.reviews.clear()
        self.live_turns.clear()
        self.review_actions = ReviewActions(self)
        self.recovery = CaptureRecovery(self)
        self.routes = AudioRoutes(self)
        self.press = PressMachine()
        self.audio = None
        self.headset_confirmed = False
        self.worker = None
        self.accepted_bytes = 0
