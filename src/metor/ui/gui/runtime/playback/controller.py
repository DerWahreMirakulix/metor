"""Single-output arbitration and route-qualified manual playback over public SDK IO."""

from typing import TYPE_CHECKING

from metor.core.api import Delivery, MessageDirectionCode, VoiceIncomingStartedEvent
from metor.ui.gui.platform.audio import HeadsetAudio, PcmVoice
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.state.media import MediaCache, PlaybackProgress, PlaybackTarget

# Local Package Imports
from .worker import OutputPort, PlaybackWorker
from .eligibility import AutoPlayback

if TYPE_CHECKING:
    from ..controller import GuiController


class PlaybackController:
    """Arbitrates one audible stream independently of capture and the action worker."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates inert output ownership for one GUI activation.

        Args:
            controller: Owning public-service coordinator.
        Returns:
            None
        """
        self.controller = controller
        self.audio: OutputPort | None = None
        self.worker: PlaybackWorker | None = None
        self.progress: PlaybackProgress | None = None
        self.cache = MediaCache()
        self._serial = 0
        self._pending: tuple[PlaybackTarget, int] | None = None
        self.auto = AutoPlayback(self)

    @property
    def running(self) -> bool:
        """Reports actual output worker ownership rather than presentation status.

        Args:
            None
        Returns:
            bool: Whether a worker still owns the native output.
        """
        return self.worker is not None and not self.worker.done.is_set()

    def configure(self, endpoint: int) -> bool:
        """Selects an inert headset output route while no output is active.

        Args:
            endpoint: Explicit enumerated and user-confirmed native endpoint.
        Returns:
            bool: Whether the output route was safely installed.
        """
        if self.running:
            return False
        self.audio = HeadsetAudio(output_device=endpoint)
        return True

    def target(
        self,
        peer: str,
        delivery: Delivery,
        direction: MessageDirectionCode,
        msg_id: str,
        *,
        review: bool = False,
    ) -> PlaybackTarget | None:
        """Qualifies a media control using the current profile-instance and epoch.

        Args:
            peer: Canonical immutable source peer.
            delivery: Visible source projection.
            direction: Exact local source direction.
            msg_id: Stable message identity.
            review: Whether preview requires this GUI's staging lease.
        Returns:
            PlaybackTarget | None: Exact authorized target or unavailable state.
        """
        state = self.controller.state
        if state.covered:
            scope = self.controller.security.continuation.scope
            if (
                scope is None
                or peer != scope.peer
                or delivery is not Delivery.LIVE
                or direction is not MessageDirectionCode.IN
                or review
            ):
                return None
            return PlaybackTarget(
                state.generation,
                scope.profile_instance,
                scope.epoch,
                peer,
                delivery,
                direction,
                msg_id,
            )
        snapshot = state.snapshot
        if snapshot is None or not snapshot.profile_instance_id or not snapshot.epoch:
            return None
        return PlaybackTarget(
            state.generation,
            snapshot.profile_instance_id,
            snapshot.epoch,
            peer,
            delivery,
            direction,
            msg_id,
            self.controller.voice_owner.token if review else None,
        )

    def _scope_allows(self, target: PlaybackTarget) -> bool:
        """Revalidates the permitted foreground or continued target before opening output.

        Args:
            target: Exact queued output identity.
        Returns:
            bool: Whether current presentation authority still covers that target.
        """
        state = self.controller.state
        if state.covered:
            scope = self.controller.security.continuation.scope
            return bool(
                scope is not None
                and self.controller.security.restriction is not None
                and target.profile_instance == scope.profile_instance
                and target.epoch == scope.epoch
                and target.peer == scope.peer
                and target.delivery is Delivery.LIVE
                and target.direction is MessageDirectionCode.IN
            )
        return (
            state.route.peer == target.peer and state.route.delivery is target.delivery
        )

    def play(
        self, target: PlaybackTarget, *, offset: int = 0, automatic: bool = False
    ) -> bool:
        """Starts explicit playback or safely preempts the previous output owner.

        Args:
            target: Exact source captured by a deliberate Play control.
            offset: Safe PCM seek offset; nonzero cannot fabricate full coverage.
            automatic: Whether a newly beginning eligible turn requested output.
        Returns:
            bool: Whether this route's manual playback was admitted.
        """
        state = self.controller.state
        if (
            self.controller.purge.active
            or (state.covered and not automatic)
            or not self._scope_allows(target)
            or self.audio is None
            or self.controller.client is None
            or target.generation != state.generation
            or offset < 0
            or offset % PcmVoice.SAMPLE_BYTES
        ):
            return False
        self._pending = (target, offset)
        if not automatic:
            self.auto.queue.clear()
            self.auto.manual = True
        if self.running and self.worker is not None:
            self.worker.stop()
        self.poll()
        return True

    def incoming(self, event: VoiceIncomingStartedEvent) -> None:
        """Offers a newly beginning turn to the foreground eligibility policy.

        Args:
            event: Current activation's ordered inbound Voice start.
        Returns:
            None
        """
        self.auto.incoming(event)

    def forget(
        self,
        peer: str | None,
        delivery: Delivery,
        msg_id: str | None = None,
        direction: MessageDirectionCode | None = None,
    ) -> None:
        """Revokes only cleared non-review sources, including reads not yet cached.

        Args:
            peer: Explicit peer or all peers in the acknowledged projection.
            delivery: Projection whose local copies were cleared.
            msg_id: Optional exact message identity.
            direction: Optional exact direction qualifier.
        Returns:
            None
        """

        def matches(target: PlaybackTarget) -> bool:
            """Checks the complete approved local cleanup scope.

            Args:
                target: Existing worker or queued source.
            Returns:
                bool: Whether the target is a cleared non-review copy.
            """
            return (
                target.owner_token is None
                and target.delivery is delivery
                and (peer is None or target.peer == peer)
                and (msg_id is None or target.msg_id == msg_id)
                and (direction is None or target.direction is direction)
            )

        if self._pending is not None and matches(self._pending[0]):
            self.cache.discard(self._pending[0])
            self._pending = None
        if self.worker is not None and matches(self.worker.target):
            self.worker.stop()
            self.cache.discard(self.worker.target)
            self._serial += 1
        if self.progress is not None and matches(self.progress.target):
            self.cache.discard(self.progress.target)
            self.progress = None
        self.cache.discard_scope(peer, delivery, msg_id, direction)

    def stop(self) -> None:
        """Revokes queued and active playback on pause or route/focus departure.

        Args:
            None
        Returns:
            None
        """
        self._pending = None
        self.auto.queue.clear()
        if self.worker is not None:
            self.worker.stop()

    def poll(self) -> None:
        """Starts the next explicit source only after the previous output closes.

        Args:
            None
        Returns:
            None
        """
        if self.running or self._pending is None:
            return
        target, offset = self._pending
        self._pending = None
        state, client = self.controller.state, self.controller.client
        if (
            not self._scope_allows(target)
            or client is None
            or self.audio is None
            or target.generation != state.generation
        ):
            return
        self._serial += 1
        self.worker = PlaybackWorker(
            client,
            target,
            self._serial,
            self.audio,
            self.controller.mailbox,
            self.cache,
            offset=offset,
        )
        self.progress = PlaybackProgress(target, self._serial)
        self.worker.start()

    def install(self, update: Update) -> bool:
        """Installs only the current output owner's local progress.

        Args:
            update: Generation-validated mailbox record.
        Returns:
            bool: Whether playback owns this update.
        """
        if update.playback is not None:
            if update.playback.serial == self._serial:
                self.progress = update.playback
            return True
        return update.operation == 'playback-done'

    def abandon(self) -> None:
        """Stops output and releases all retained profile media on owner loss.

        Args:
            None
        Returns:
            None
        """
        self.stop()
        self.cache.clear()
        self.auto.overrides.clear()
        self.progress = None
        self.audio = None
