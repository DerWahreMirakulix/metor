"""Covered, phase-aware profile switch and GUI-only desktop exit through public SDK owners."""

import threading
from typing import TYPE_CHECKING

from metor.client import (
    MetorClient,
    ProfileRuntimeCoordinator,
    ProfileSwitchError,
    ProfileSwitchPhase,
)
from metor.core.api import (
    DaemonLockedEvent,
    IpcEvent,
    ReleaseVoiceOwnerCommand,
    SelfDestructInitiatedEvent,
    VoiceOwnerReleasedEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

from ..activation import ActivatedProfile
from ..interaction import Interactions
from ..voice.press import PressPhase

if TYPE_CHECKING:
    from ..controller import GuiController


class ProfileTransition:
    """Owns one source/target transaction without interpreting transport loss as success."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an inert lifecycle coordinator independent of native window callbacks.

        Args:
            controller: Current public GUI service owner.
        Returns:
            None
        """
        self.controller = controller
        self.active = False
        self.failed = False
        self.exit_ready = False
        self.exit_requested = False
        self.return_available = False
        self.owner_loss_supported = False
        self.phase = ''
        self._cancelled = threading.Event()
        self._candidate: ActivatedProfile | None = None
        self._interactions: Interactions | None = None
        self._error: ProfileSwitchError | None = None
        self._source_invalid = False
        self._owner_release_attempted = False
        self._return_route = Route('V06')

    def start(self, target: str | None = None) -> bool:
        """Freezes producers and starts an explicitly confirmed switch or GUI-only exit.

        Args:
            target: Exact target profile, or None to detach this GUI only.
        Returns:
            bool: Whether the single lifecycle transaction was admitted.
        """
        controller, state = self.controller, self.controller.state
        if self.active or state.busy or (state.covered and target is not None):
            return False
        client = controller.client
        if client is None:
            if target is None:
                self.exit_ready = True
                return True
            return False
        if controller.simulator:
            self.exit_ready = target is None
            return self.exit_ready
        generation = state.generation
        owner = controller.voice_owner.token
        capture = controller.voice.worker
        unresolved = controller.voice.press.phase is PressPhase.FAILED
        self._cancelled.clear()
        self._candidate = None
        self._interactions = None
        self._error = None
        self._source_invalid = False
        self._owner_release_attempted = False
        self.owner_loss_supported = (
            'disposable_voice_owner' in state.capabilities and owner is not None
        )
        self._return_route = state.route

        def phase(value: ProfileSwitchPhase) -> None:
            """Reports an actual coordinator phase before its public operation starts.

            Args:
                value: Actual source or target lifecycle phase.
            Returns:
                None
            """
            controller.mailbox.put(Update(generation, 'lifecycle:phase:' + value.value))

        def finish_capture() -> None:
            """Waits for this GUI's accepted finalization before releasing its staging owner.

            Args:
                None
            Returns:
                None
            """
            if self._cancelled.is_set():
                raise RuntimeError('Lifecycle cancelled')
            if capture is not None:
                capture.request_stop()
                if (
                    not capture.done.wait(GuiLimits.LIFECYCLE_CAPTURE_SECONDS)
                    or not capture.completion_confirmed
                ):
                    raise RuntimeError('Capture preservation unconfirmed')
            elif unresolved:
                raise RuntimeError('Capture preservation unconfirmed')
            if owner is not None:
                self._owner_release_attempted = True
                result = client.request(
                    ReleaseVoiceOwnerCommand(owner), VoiceOwnerReleasedEvent
                )
                if result is None:
                    raise RuntimeError('Owner release unconfirmed')
            if self._cancelled.is_set():
                raise RuntimeError('Lifecycle cancelled')

        def factory(name: str) -> MetorClient:
            """Selects the target only after Core confirms source preparation and detach.

            Args:
                name: Exact user-selected target.
            Returns:
                MetorClient: Inert candidate with its own authentication bridge.
            """
            if self._cancelled.is_set() or state.generation != generation:
                raise RuntimeError('Activation abandoned')
            selected = controller.context.host.select_profile(name)
            if not selected.exists:
                raise RuntimeError('Selected profile no longer exists')
            interactions = Interactions(generation + 1, controller.mailbox)
            self._interactions = interactions
            if self._cancelled.is_set() or state.generation != generation:
                interactions.cancel()
                raise RuntimeError('Activation abandoned')
            controller.interactions.cancel()
            controller.interactions = interactions
            return controller.activation.connect(generation + 1, interactions)

        def run() -> IpcEvent | None:
            """Executes public lifecycle operations off the GUI thread and captures phase truth.

            Args:
                None
            Returns:
                IpcEvent | None: Completion is installed by the lifecycle owner.
            """
            candidate: MetorClient | None = None
            try:
                if target is None:
                    phase(ProfileSwitchPhase.CAPTURE_FINALIZATION)
                    try:
                        finish_capture()
                    except Exception as exc:
                        raise ProfileSwitchError(
                            ProfileSwitchPhase.CAPTURE_FINALIZATION,
                            'Could not confirm recording preservation.',
                        ) from exc
                    phase(ProfileSwitchPhase.SOURCE_RELEASE)
                    client.disconnect()
                else:
                    coordinator = ProfileRuntimeCoordinator(client, factory)
                    coordinator.switch(
                        target, finalize_active_capture=finish_capture, on_phase=phase
                    )
                    candidate = coordinator.client
                    initialized = candidate.init_event
                    if initialized is None:
                        raise RuntimeError('Candidate initialization unavailable')
                    self._candidate = controller.activation.hydrate(
                        candidate, initialized
                    )
            except ProfileSwitchError as exc:
                self._error = exc
            except Exception:
                self._error = ProfileSwitchError(
                    ProfileSwitchPhase.TARGET_SNAPSHOT
                    if target is not None
                    else ProfileSwitchPhase.SOURCE_RELEASE,
                    'Profile transition could not be confirmed.',
                    source_released=target is not None,
                )
            finally:
                if self._interactions is not None:
                    self._interactions.startup_secret(None)
                if candidate is not None and (
                    self._error is not None or self._cancelled.is_set()
                ):
                    candidate.disconnect()
                    self._candidate = None
            return None

        if not controller.submit('lifecycle:complete', run):
            return False
        self.active, self.failed = True, False
        self.exit_requested = target is None
        self.return_available = False
        controller.voice.depart()
        controller.playback.stop()
        controller.inputs.focus_lost()
        controller.calls.clear()
        state.covered = True
        state.route = Route('V21' if target is None else 'V20')
        self.phase = (
            'Finishing recording' if capture is not None else 'Preparing profile'
        )
        state.status = self.phase
        return True

    def install(self, update: Update) -> bool:
        """Fences old-source callbacks and installs only a completely hydrated candidate.

        Args:
            update: Current generation's worker or source event.
        Returns:
            bool: Whether the lifecycle owner consumed this update.
        """
        if not self.active:
            return False
        controller, state = self.controller, self.controller.state
        if isinstance(update.event, SelfDestructInitiatedEvent):
            self.cancel()
            controller.close(purging=True)
            return True
        if update.operation == 'lost' or isinstance(update.event, DaemonLockedEvent):
            self._source_invalid = True
            return True
        if update.operation.startswith('voice-'):
            return False
        if update.operation.startswith('lifecycle:phase:'):
            self.phase = {
                'source_snapshot': 'Checking current profile',
                'capture_finalization': 'Finishing recording',
                'source_preparation': 'Preserving queued messages',
                'source_release': 'Closing this GUI'
                if self.exit_requested
                else 'Closing profile',
                'target_factory': 'Opening profile',
                'target_bootstrap': 'Opening profile',
                'target_snapshot': 'Loading profile',
            }[update.operation.rsplit(':', 1)[-1]]
            state.status = self.phase
            if update.operation.endswith(':source_release'):
                state.drafts.clear()
                state.snapshot = None
                state.preferences = None
                controller.transcript.clear()
                controller.messages = None
            return True
        if update.operation != 'lifecycle:complete':
            return True
        state.busy = False
        self.active = False
        if self._owner_release_attempted:
            controller.voice_owner.token = None
        if self._error is not None or update.status:
            self.failed = True
            error = self._error
            self.return_available = (
                not self._source_invalid
                and client_connected(controller)
                and error is not None
                and error.phase is ProfileSwitchPhase.CAPTURE_FINALIZATION
                and not self._owner_release_attempted
                and not self._return_route.view == 'V05'
            )
            state.status = (
                'Could not confirm recording preservation. Accepted audio remains managed by Metor.'
                if error is not None
                and error.phase is ProfileSwitchPhase.CAPTURE_FINALIZATION
                else 'The previous profile is locked. Could not open the selected profile.'
                if error is not None and error.source_prepared
                else 'Profile transition is unconfirmed. Open a profile explicitly to continue.'
            )
            return True
        if self.exit_requested:
            controller.client = None
            controller.voice_owner.token = None
            controller.close()
            self.exit_ready = True
            return True
        candidate, interactions = self._candidate, self._interactions
        if candidate is None or interactions is None:
            self.failed = True
            state.status = (
                'Could not install the selected profile. Choose a profile to continue.'
            )
            return True
        controller.client = None
        controller.voice_owner.token = None
        controller.close(preserve_interactions=interactions)
        controller.client = candidate.client
        if not candidate.client.is_connected:
            self._candidate = None
            self._interactions = None
            controller.close()
            state.status = 'The selected profile disconnected before entry completed. Open profile to retry.'
            return True
        controller.activation.publish(candidate, state.generation)
        controller.mailbox.put(
            Update(state.generation, 'bootstrap', candidate.snapshot)
        )
        self._candidate = None
        self._interactions = None
        return True

    def return_to_source(self) -> None:
        """Removes the transition cover only when no source preparation was attempted.

        Args:
            None
        Returns:
            None
        """
        if self.failed and self.return_available and client_connected(self.controller):
            self.failed = False
            self.controller.state.covered = False
            self.controller.state.route = self._return_route
            self.controller.refresh_state()

    def choose_profile(self) -> None:
        """Detaches uncertain source state before explicit fresh entry; never auto-unlocks it.

        Args:
            None
        Returns:
            None
        """
        if self.failed:
            self.failed = False
            self.controller.close()
            self.controller.state.route = Route('V02')
            self.controller.profiles.reload()

    def exit_anyway(self) -> None:
        """Uses only the advertised durable owner-loss contract after explicit user choice.

        Args:
            None
        Returns:
            None
        """
        if self.failed and self.exit_requested and self.owner_loss_supported:
            self.failed = False
            self.controller.close()
            self.exit_ready = True

    def cancel(self) -> None:
        """Revokes a departed operation without retrying or rolling back Core preparation.

        Args:
            None
        Returns:
            None
        """
        if self.active:
            self._cancelled.set()
            if self._interactions is not None:
                self._interactions.cancel()
        self.active = False
        self.failed = False
        self.return_available = False


def client_connected(controller: 'GuiController') -> bool:
    """Checks only current connection state without authentication or runtime mutation.

    Args:
        controller: Current public GUI service owner.
    Returns:
        bool: Whether its existing SDK client remains attached.
    """
    return controller.client is not None and controller.client.is_connected
