"""One-source, one-target PTT interaction with a release barrier after interruption."""

from dataclasses import dataclass
from enum import Enum

from metor.core.api import Delivery


class PressPhase(str, Enum):
    """Local interaction phases; acceptance and persistence remain Core facts."""

    IDLE = 'idle'
    STARTING = 'starting'
    RECORDING = 'recording'
    FINALIZING = 'finalizing'
    RELEASE_REQUIRED = 'release_required'
    FAILED = 'failed'


class PressSource(str, Enum):
    """Registered input channels; each adapter owns its pointer/key identity."""

    POINTER = 'pointer'
    KEYBOARD = 'keyboard'
    PHYSICAL = 'physical'


@dataclass(frozen=True)
class CaptureBinding:
    """Immutable recording target captured on the initiating valid down event."""

    profile_instance: str
    epoch: str
    generation: int
    peer: str
    delivery: Delivery
    msg_id: str
    context_generation: int | None = None


class PressMachine:
    """Normalizes input while leaving recording/transport on independent workers."""

    def __init__(self) -> None:
        """Creates a released inert input machine.

        Args:
            None
        Returns:
            None
        """
        self.phase = PressPhase.IDLE
        self.held: set[PressSource] = set()
        self.source: PressSource | None = None
        self.binding: CaptureBinding | None = None
        self.stop_requested = False
        self.aborted = False

    @property
    def active(self) -> bool:
        """Reports whether the local recording interaction owns the composer.

        Args:
            None
        Returns:
            bool: Starting, recording or finalizing interaction.
        """
        return self.phase in {
            PressPhase.STARTING,
            PressPhase.RECORDING,
            PressPhase.FINALIZING,
        }

    def down(
        self, source: PressSource, binding: CaptureBinding, eligible: bool
    ) -> bool:
        """Admits one fresh press without allowing repeat or source theft.

        Args:
            source: Registered input adapter retaining its exact physical identity.
            binding: Immutable target and activation captured by the caller.
            eligible: Current public capability, context, microphone and review checks.
        Returns:
            bool: Whether to start one local admission worker.
        """
        if source in self.held:
            return False
        was_released = not self.held
        self.held.add(source)
        if not was_released or self.phase is not PressPhase.IDLE or not eligible:
            if self.phase is PressPhase.IDLE:
                self.phase = PressPhase.RELEASE_REQUIRED
            return False
        self.source = source
        self.binding = binding
        self.stop_requested = False
        self.aborted = False
        self.phase = PressPhase.STARTING
        return True

    def accepted(self, binding: CaptureBinding) -> bool:
        """Installs matching local Begin acceptance without reviving an old press.

        Args:
            binding: Exact worker identity returned after Core admission.
        Returns:
            bool: Whether the admitted turn still belongs to this machine.
        """
        if self.binding != binding or self.aborted or not self.active:
            return False
        self.phase = (
            PressPhase.FINALIZING if self.stop_requested else PressPhase.RECORDING
        )
        return True

    def up(self, source: PressSource) -> bool:
        """Stops only the owning press; all releases are required before rearming.

        Args:
            source: Exact source whose release its adapter verified.
        Returns:
            bool: Whether an active recording must stop/finalize.
        """
        self.held.discard(source)
        stop = source is self.source and self.active
        if stop:
            self.depart()
        if not self.held and self.phase is PressPhase.RELEASE_REQUIRED:
            self.phase = PressPhase.IDLE
        return stop

    def depart(self, *, purge: bool = False) -> bool:
        """Consumes a held press on context/focus departure or authorized purge.

        Args:
            purge: True only after Core accepts purge; normal finalization is forbidden.
        Returns:
            bool: Whether an active capture worker needs a stop signal.
        """
        active = self.active
        self.stop_requested = True
        self.aborted = self.aborted or purge
        if active:
            self.phase = PressPhase.FINALIZING
        elif self.held and self.phase is not PressPhase.FAILED:
            self.phase = PressPhase.RELEASE_REQUIRED
        return active

    def complete(self, binding: CaptureBinding, *, confirmed: bool) -> bool:
        """Finishes one interaction while preserving unknown-result and held-input barriers.

        Args:
            binding: Exact completed worker identity.
            confirmed: Canonical completion/cancellation was confirmed by Core.
        Returns:
            bool: Whether the completion matches the current recording.
        """
        if binding != self.binding:
            return False
        self.phase = (
            PressPhase.FAILED
            if not confirmed
            else PressPhase.RELEASE_REQUIRED
            if self.held
            else PressPhase.IDLE
        )
        self.source = None
        if confirmed:
            self.binding = None
        return True
