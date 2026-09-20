"""Bounded read-only observation of Core destruction while all normal GUI state is covered."""

from dataclasses import dataclass, replace
import threading
import time
from typing import TYPE_CHECKING

from metor.client import MetorClient, valid_frontend_profile_name
from metor.client.platform import PlatformActionResult
from metor.core.api import (
    IpcEvent,
    SelfDestructInitiatedEvent,
    SelfDestructKeyDestroyedEvent,
    SelfDestructRuntimeReleasedEvent,
    SelfDestructSafeEvent,
    SelfDestructCompletedEvent,
    SelfDestructCleanupFailedEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route

if TYPE_CHECKING:
    from .controller import GuiController


@dataclass(frozen=True)
class PurgeFacts:
    """Finite facts for one original transport activation and operation; no payload or credentials."""

    generation: int
    profile: str | None
    operation_id: str | None
    started_at: float
    key_destroyed: bool = False
    runtime_released: bool = False
    safe_at: float | None = None
    completed: bool = False
    failed: bool = False
    lost: bool = False
    transport_lost: bool = False


class PurgeMonitor:
    """Keeps milestone observation separate from the ordinary GUI queue and its privacy teardown.

    This owner cannot request destruction, authorize a device or shut down a host.
    """

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an inert observer without retaining a client or activating hardware.

        Args:
            controller: Current GUI presentation owner.
        Returns:
            None
        """
        self.controller = controller
        self._lock = threading.Lock()
        self._facts: PurgeFacts | None = None
        self._client: MetorClient | None = None
        self._covered = False
        self._revision = 0
        self._rendered = -1
        self._disposed = False
        self.title = ''
        self.detail = ''
        self._shutdown_result: PlatformActionResult | None = None

    @property
    def active(self) -> bool:
        """Reports whether the original destruction still owns the privacy surface.

        Args:
            None
        Returns:
            bool: True includes terminal and unknown outcomes until explicit GUI exit.
        """
        with self._lock:
            return self._facts is not None and not self._disposed

    def observe(self, generation: int, event: IpcEvent) -> bool:
        """Retains fixed-size lifecycle facts before normal mailbox admission can lose them.

        Args:
            generation: Activation captured by the original authenticated SDK callback.
            event: Actual typed Core event; observing it grants no destructive rights.
        Returns:
            bool: Whether the event is consumed by the destructive privacy boundary.
        """
        with self._lock:
            if self._disposed:
                return False
            facts = self._facts
            if facts is None:
                if not isinstance(
                    event,
                    (
                        SelfDestructInitiatedEvent,
                        SelfDestructKeyDestroyedEvent,
                        SelfDestructRuntimeReleasedEvent,
                        SelfDestructSafeEvent,
                        SelfDestructCompletedEvent,
                        SelfDestructCleanupFailedEvent,
                    ),
                ):
                    return False
                if generation != self.controller.state.generation:
                    return True
                snapshot = self.controller.state.snapshot
                if snapshot is not None and event.profile not in (
                    None,
                    snapshot.profile,
                ):
                    return True
                facts = self._facts = PurgeFacts(
                    generation,
                    event.profile
                    if isinstance(event.profile, str)
                    and valid_frontend_profile_name(event.profile)
                    else None,
                    event.operation_id
                    if isinstance(event.operation_id, str)
                    and len(event.operation_id) == 2 * GuiLimits.MESSAGE_ID_BYTES
                    and all(
                        character in '0123456789abcdef'
                        for character in event.operation_id
                    )
                    else None,
                    time.monotonic(),
                )
                self._revision += 1
                capture = self.controller.voice.worker
                if capture is not None:
                    capture.request_stop(purge=True)
                playback = self.controller.playback.worker
                if playback is not None:
                    playback.stop()
                resend = self.controller.resend.current
                if resend is not None:
                    resend.cancelled.set()
            if generation != facts.generation:
                return True
            if (
                not facts.operation_id
                or not facts.profile
                or getattr(event, 'operation_id', None) != facts.operation_id
                or getattr(event, 'profile', None) != facts.profile
            ):
                return True
            if isinstance(event, SelfDestructKeyDestroyedEvent):
                facts = replace(facts, key_destroyed=True)
            elif isinstance(event, SelfDestructRuntimeReleasedEvent):
                facts = replace(facts, runtime_released=True)
            elif isinstance(event, SelfDestructSafeEvent):
                facts = replace(
                    facts,
                    safe_at=facts.safe_at or time.monotonic(),
                    lost=False if not (facts.completed or facts.failed) else facts.lost,
                )
            elif isinstance(event, SelfDestructCompletedEvent):
                facts = replace(facts, completed=True)
            elif isinstance(event, SelfDestructCleanupFailedEvent):
                facts = replace(facts, failed=True)
            if facts != self._facts:
                self._facts = facts
                self._revision += 1
            return True

    def lost(self, generation: int) -> bool:
        """Records transport loss without interpreting EOF as successful destruction.

        Args:
            generation: Activation captured by the disconnect callback.
        Returns:
            bool: Whether this observer owns the lost transport's outcome.
        """
        with self._lock:
            if self._facts is None or self._disposed:
                return False
            if generation == self._facts.generation and not self._facts.transport_lost:
                self._facts = replace(
                    self._facts,
                    lost=self._facts.safe_at is None,
                    transport_lost=True,
                )
                self._revision += 1
            return True

    def poll(self, *, now: float | None = None) -> bool:
        """Covers immediately on the UI tick and renders only confirmed operation milestones.

        Args:
            now: Optional deterministic monotonic clock for tests.
        Returns:
            bool: Whether the covered presentation changed.
        """
        current = time.monotonic() if now is None else now
        with self._lock:
            facts = self._facts
            if facts is None or self._disposed:
                return False
            deadline = (
                facts.safe_at + GuiLimits.PURGE_CLEANUP_SECONDS
                if facts.safe_at is not None
                else facts.started_at + GuiLimits.PURGE_OBSERVE_SECONDS
            )
            if current >= deadline and not (
                facts.completed or facts.failed or facts.lost
            ):
                facts = self._facts = replace(facts, lost=True)
                self._revision += 1
            changed = self._revision != self._rendered
            self._rendered = self._revision
        if not self._covered:
            self._covered = True
            controller = self.controller
            self._client, controller.client = controller.client, None
            controller.close(purging=True, preserve_purge=True)
            controller.state.route = Route('V22')
            changed = True
        terminal = facts.completed or facts.failed or facts.lost
        if facts.safe_at is not None:
            self.title = 'Profile access destroyed'
            self.detail = (
                'Powering off.'
                if self._shutdown_result is PlatformActionResult.ACCEPTED
                else 'Power off request failed. Keep the device powered.'
                if self._shutdown_result is not None
                else 'File cleanup is incomplete.'
                if facts.failed
                else 'File cleanup completed.'
                if facts.completed
                else 'File cleanup could not be confirmed.'
                if facts.lost
                else 'Removing encrypted profile files…'
            )
        elif terminal:
            self.title = 'Destruction not confirmed'
            self.detail = 'Keep the device powered. Profile access destruction could not be confirmed.'
        else:
            self.title = 'Purging profile'
            self.detail = (
                'Persistent key protection removed. Waiting for confirmed runtime release.'
                if facts.key_destroyed
                else 'Runtime access released. Waiting for confirmed key protection removal.'
                if facts.runtime_released
                else 'Waiting for confirmed profile access destruction.'
            )
        self.controller.state.status = self.title
        if terminal:
            self._detach()
        return changed

    @property
    def shutdown_ready(self) -> bool:
        """Reports exact-operation safety plus terminal cleanup knowledge or bounded loss.

        Args:
            None
        Returns:
            bool: Whether local shutdown may now be requested once.
        """
        with self._lock:
            facts = self._facts
            return bool(
                facts is not None
                and facts.safe_at is not None
                and (facts.completed or facts.failed or facts.lost)
                and self._shutdown_result is None
            )

    def record_shutdown(self, result: PlatformActionResult) -> None:
        """Records actuator admission separately from destruction safety.

        Args:
            result: Typed local shutdown request outcome.
        Returns:
            None
        """
        if not isinstance(result, PlatformActionResult):
            raise ValueError('Invalid shutdown result')
        with self._lock:
            facts = self._facts
            if (
                facts is None
                or facts.safe_at is None
                or not (facts.completed or facts.failed or facts.lost)
                or self._shutdown_result is not None
            ):
                return
            self._shutdown_result = result
            self._revision += 1

    def _detach(self) -> None:
        """Releases only the observed IPC client after a terminal outcome or bounded wait.

        Args:
            None
        Returns:
            None
        """
        with self._lock:
            client, self._client = self._client, None
        if client is None:
            return

        def disconnect() -> None:
            """Closes transport without any owner release, profile unlock or normal exit command.

            Args:
                None
            Returns:
                None
            """
            try:
                client.disconnect()
            except Exception:
                pass

        threading.Thread(
            target=disconnect, name='metor-gui-purge-detach', daemon=True
        ).start()

    def dispose(self) -> None:
        """Drops operation references when this GUI explicitly closes; never changes destruction truth.

        Args:
            None
        Returns:
            None
        """
        with self._lock:
            self._disposed = True
            self._facts = None
        self._detach()
