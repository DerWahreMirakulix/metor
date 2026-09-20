"""Normal device shutdown preparation kept separate from purge authorization."""

from typing import TYPE_CHECKING, Protocol

from metor.client.platform import PlatformActionResult, PlatformBindings
from metor.core.api import IpcEvent, ReleaseVoiceOwnerCommand, VoiceOwnerReleasedEvent
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from .model import DevicePhase

if TYPE_CHECKING:
    from ..controller import GuiController


class DevicePresentation(Protocol):
    """Narrow presentation surface owned by the physical input coordinator."""

    phase: DevicePhase
    title: str
    detail: str

    def remember_return(self) -> None: ...
    def restore_return(self) -> None: ...
    def critical(self, status: str) -> None: ...


class PowerFlow:
    """Prepares one local Core before invoking the fixed privileged actuator."""

    def __init__(
        self, controller: 'GuiController', bindings: PlatformBindings | None
    ) -> None:
        """Creates an inert normal-power coordinator.

        Args:
            controller: Current GUI and SDK owner.
            bindings: Validated platform capabilities.
        Returns:
            None
        """
        self.controller = controller
        self.bindings = bindings
        self._result: tuple[bool, PlatformActionResult] | None = None
        self._prepared = False

    def open(self, presentation: DevicePresentation) -> bool:
        """Opens the explicit menu without invoking Core or the actuator.

        Args:
            presentation: Device-owned full-cover state.
        Returns:
            bool: Whether the menu opened.
        """
        controller = self.controller
        if (
            self.bindings is None
            or self.bindings.shutdown is None
            or controller.simulator
            or presentation.phase is not DevicePhase.IDLE
            or controller.purge.active
        ):
            return False
        presentation.remember_return()
        self._prepared = False
        controller.state.covered = True
        controller.state.route = Route('V21')
        presentation.phase = DevicePhase.POWER_MENU
        presentation.title = 'Power off'
        presentation.detail = 'Prepare local state before powering off this device?'
        return True

    def request(self, presentation: DevicePresentation) -> bool:
        """Starts safe local preparation before fixed platform shutdown.

        Args:
            presentation: Device-owned full-cover state.
        Returns:
            bool: Whether one worker was admitted.
        """
        controller = self.controller
        client = controller.client
        snapshot = controller.state.snapshot
        bindings = self.bindings
        shutdown = bindings.shutdown if bindings is not None else None
        if (
            shutdown is not None
            and presentation.phase is DevicePhase.POWER_FAILED
            and self._prepared
        ):

            def retry() -> IpcEvent | None:
                """Retries only the fixed actuator after confirmed Core preparation.

                Args:
                    None
                Returns:
                    IpcEvent | None: No wire event; typed actuator result is retained.
                """
                try:
                    outcome = shutdown.request_shutdown()
                except Exception:
                    outcome = PlatformActionResult.FAILED
                self._result = (True, outcome)
                return None

            if not controller.submit('device:power', retry):
                return False
            presentation.phase = DevicePhase.POWER_PREPARING
            presentation.title = 'Powering off'
            presentation.detail = 'Retrying shutdown request'
            return True
        if (
            self.bindings is None
            or shutdown is None
            or controller.simulator
            or presentation.phase
            not in {DevicePhase.POWER_MENU, DevicePhase.POWER_FAILED}
            or client is None
        ):
            return False
        assert shutdown is not None
        capture = controller.voice.worker
        unresolved = controller.voice.press.phase.value == 'failed'
        owner = controller.voice_owner.token
        profile = snapshot.profile if snapshot is not None else None

        def run() -> IpcEvent | None:
            """Prepares the exact local profile and calls the bounded actuator.

            Args:
                None
            Returns:
                IpcEvent | None: No wire event; a typed local result is retained.
            """
            prepared = False
            outcome = PlatformActionResult.UNKNOWN
            try:
                host_state = controller.context.host.profile_state()
                if host_state.remote or (
                    profile is not None and host_state.profile != profile
                ):
                    outcome = PlatformActionResult.DENIED
                    return None
                profiles = controller.context.host.list_profiles()
                selected = tuple(
                    state
                    for state in profiles
                    if state.profile == host_state.profile and not state.remote
                )
                competing = tuple(
                    state
                    for state in profiles
                    if state.profile != host_state.profile
                    and not state.remote
                    and state.daemon_running
                )
                if not host_state.daemon_running or len(selected) != 1 or competing:
                    outcome = PlatformActionResult.DENIED
                    return None
                if capture is not None:
                    capture.request_stop()
                    if (
                        not capture.done.wait(GuiLimits.LIFECYCLE_CAPTURE_SECONDS)
                        or not capture.completion_confirmed
                    ):
                        return None
                elif unresolved:
                    return None
                if (
                    owner is not None
                    and client.request(
                        ReleaseVoiceOwnerCommand(owner), VoiceOwnerReleasedEvent
                    )
                    is None
                ):
                    return None
                if not client.prepare_profile_exit():
                    return None
                prepared = True
                client.disconnect()
                outcome = shutdown.request_shutdown()
            except Exception:
                outcome = PlatformActionResult.FAILED if prepared else outcome
            finally:
                self._result = (prepared, outcome)
            return None

        if not controller.submit('device:power', run):
            return False
        controller.voice.depart()
        controller.playback.stop()
        controller.inputs.focus_lost()
        presentation.phase = DevicePhase.POWER_PREPARING
        presentation.title = 'Saving local state'
        presentation.detail = (
            'Finishing recording' if capture is not None else 'Preparing profile'
        )
        controller.state.status = presentation.title
        return True

    def poll(self, presentation: DevicePresentation) -> bool:
        """Installs one completed worker outcome on the GUI thread.

        Args:
            presentation: Device-owned full-cover state.
        Returns:
            bool: Whether an outcome was installed.
        """
        if self._result is None:
            return False
        prepared, result = self._result
        self._result = None
        self._prepared = prepared
        controller = self.controller
        controller.state.busy = False
        if prepared:
            controller.client = None
            controller.voice_owner.token = None
            controller.close()
            controller.state.covered = True
            controller.state.route = Route('V21')
        if prepared and result is PlatformActionResult.ACCEPTED:
            presentation.phase = DevicePhase.POWERING_OFF
            presentation.title = 'Powering off'
            presentation.detail = 'Shutdown request accepted'
        else:
            presentation.phase = DevicePhase.POWER_FAILED
            presentation.title = 'Power off unavailable'
            presentation.detail = (
                'Local state is safe. The device remains powered.'
                if prepared
                else 'Could not confirm local state preservation. Keep the device powered.'
            )
            presentation.critical(presentation.title)
        controller.state.status = presentation.title
        return True

    def cancel(self, presentation: DevicePresentation) -> None:
        """Closes a reversible menu or leaves uncertain Core state covered.

        Args:
            presentation: Device-owned full-cover state.
        Returns:
            None
        """
        if presentation.phase is DevicePhase.POWER_MENU:
            presentation.restore_return()
        elif presentation.phase is DevicePhase.POWER_FAILED:
            self.controller.close()
            presentation.phase = DevicePhase.IDLE
            self.controller.state.route = Route('V02')
            self.controller.profiles.reload()

    def install(self, update: Update) -> bool:
        """Consumes only the normal-power worker mailbox marker.

        Args:
            update: Current-generation worker result.
        Returns:
            bool: Whether this flow consumed it.
        """
        if update.operation != 'device:power':
            return False
        self.controller.state.busy = False
        return True
