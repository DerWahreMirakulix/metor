"""Physical input and destructive lifecycle orchestration over typed platform ports."""

from collections import deque
import secrets
import threading
import time
from typing import TYPE_CHECKING

from metor.client.platform import (
    ButtonSample,
    HapticPattern,
    IndicatorState,
    InputSubscription,
    PlatformActionResult,
    PlatformBindings,
)
from metor.core.api import (
    IpcEvent,
    SelfDestructCommand,
    SelfDestructInitiatedEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.platform.buttons import ButtonAction, ButtonResult, PhysicalButtons
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from ..voice import PressSource
from .model import DevicePhase
from .feedback import HardwareFeedback
from .power import PowerFlow
from .status import HardwareStatusProjection

if TYPE_CHECKING:
    from ..controller import GuiController


class DeviceLifecycle:
    """Maps complete hardware samples to GUI intent without granting authority."""

    def __init__(
        self, controller: 'GuiController', bindings: PlatformBindings | None
    ) -> None:
        """Creates an inert adapter consumer; subscription starts explicitly.

        Args:
            controller: Current GUI and authenticated SDK owner.
            bindings: Validated physical ports, absent on desktop and simulator.
        Returns:
            None
        """
        self.controller = controller
        self.bindings = bindings
        self.buttons = PhysicalButtons()
        self.phase = DevicePhase.IDLE
        self.title = ''
        self.detail = ''
        self.progress = 0.0
        self.status = HardwareStatusProjection(
            bindings.status if bindings is not None else None
        )
        self.feedback = HardwareFeedback(
            bindings.indicator if bindings is not None else None,
            bindings.haptics if bindings is not None else None,
        )
        self._samples: deque[ButtonSample] = deque()
        self._input_lock = threading.Lock()
        self._input_lost = False
        self._subscription: InputSubscription | None = None
        self._return_route = Route('V06')
        self._return_covered = False
        self.power = PowerFlow(controller, bindings)
        self._purge_requested = False
        self._purge_shutdown_requested = False
        self._purge_shutdown_result: PlatformActionResult | None = None
        self._purge_shutdown_worker: threading.Thread | None = None
        self._purge_shutdown_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Reports whether validated physical ports exist outside simulation.

        Args:
            None
        Returns:
            bool: True only for an injected physical deployment.
        """
        return self.bindings is not None and not self.controller.simulator

    @property
    def power_available(self) -> bool:
        """Reports whether configuration exposed a fixed shutdown actuator.

        Args:
            None
        Returns:
            bool: Whether normal power and post-purge shutdown may be requested.
        """
        return (
            self.enabled
            and self.bindings is not None
            and self.bindings.shutdown is not None
        )

    @property
    def battery_status(self) -> str:
        """Returns the independent cached hardware-status presentation.

        Args:
            None
        Returns:
            str: Content-free battery summary or an empty value.
        """
        return self.status.battery_status

    @property
    def active(self) -> bool:
        """Reports whether a device-specific full-cover surface owns presentation.

        Args:
            None
        Returns:
            bool: Whether a non-idle phase is visible.
        """
        return self.phase is not DevicePhase.IDLE

    def start(self) -> bool:
        """Subscribes after configuration validation and GUI construction.

        Args:
            None
        Returns:
            bool: Whether the physical input subscription is active.
        """
        if not self.enabled or self._subscription is not None:
            return False
        assert self.bindings is not None
        try:
            self._subscription = self.bindings.inputs.subscribe(self.receive)
        except Exception:
            self._input_lost = True
            self.critical('Physical controls unavailable')
            return False
        return True

    def receive(self, sample: ButtonSample) -> None:
        """Queues one bounded driver callback without touching GUI state.

        Args:
            sample: Complete ordered PTT/Power observation.
        Returns:
            None
        """
        with self._input_lock:
            if len(self._samples) >= GuiLimits.HARDWARE_INPUT_RECORDS:
                self._samples.clear()
                self._input_lost = True
                return
            self._samples.append(sample)

    def poll(self) -> bool:
        """Drains input and lifecycle results on the GUI thread.

        Args:
            None
        Returns:
            bool: Whether visible state may have changed.
        """
        changed = False
        changed = self.status.poll(time.monotonic()) or changed
        with self._input_lock:
            samples = tuple(self._samples)
            self._samples.clear()
            lost, self._input_lost = self._input_lost, False
        if self.controller.purge.active:
            return self._poll_purge_shutdown() or changed
        if lost:
            changed |= self._apply(self.buttons.lost())
            self.critical('Physical controls unavailable')
            changed = True
        for sample in samples:
            changed |= self._apply(self.buttons.observe(sample))
        changed = self.power.poll(self) or changed
        return changed

    def _apply(self, result: ButtonResult) -> bool:
        """Applies arbiter outputs while preserving exact input ownership.

        Args:
            result: Pure timing/arbitration result for one complete sample.
        Returns:
            bool: Whether presentation state changed.
        """
        changed = False
        if self.phase is DevicePhase.PURGE_ARMING and result.progress != self.progress:
            self.progress = result.progress
            changed = True
        for action in result.actions:
            if action is ButtonAction.PTT_DOWN:
                self.controller.inputs.down(
                    PressSource.PHYSICAL, 'platform-ptt', self.controller.voice
                )
            elif action is ButtonAction.PTT_UP:
                self.controller.inputs.up(PressSource.PHYSICAL, 'platform-ptt')
            elif action is ButtonAction.STOP_CAPTURE:
                self.controller.voice.depart()
            elif action is ButtonAction.LOCK:
                self.controller.security.lock()
            elif action is ButtonAction.POWER_MENU:
                self.open_power_menu()
            elif action is ButtonAction.ARM_PURGE:
                self._arm_purge()
            elif action is ButtonAction.CANCEL_PURGE:
                self._cancel_purge()
            elif action is ButtonAction.REQUEST_PURGE:
                self._request_purge()
            changed = True
        if (
            self.phase in {DevicePhase.PURGE_CANCELLED, DevicePhase.PURGE_UNAVAILABLE}
            and not self.buttons.ptt
            and not self.buttons.power
        ):
            self.restore_return()
            changed = True
        return changed

    def open_power_menu(self) -> bool:
        """Opens the explicit Power off choice without invoking an actuator.

        Args:
            None
        Returns:
            bool: Whether the menu was opened.
        """
        return self.power.open(self)

    def request_poweroff(self) -> bool:
        """Starts local Core preparation before requesting fixed platform shutdown.

        Args:
            None
        Returns:
            bool: Whether one bounded preparation worker was admitted.
        """
        return self.power.request(self)

    def cancel(self) -> None:
        """Closes only a reversible menu or returns from a failed preparation safely.

        Args:
            None
        Returns:
            None
        """
        self.power.cancel(self)

    def install(self, update: Update) -> bool:
        """Consumes device worker completion without treating absence as success.

        Args:
            update: Current-generation GUI mailbox record.
        Returns:
            bool: Whether this lifecycle owner consumed it.
        """
        if self.power.install(update):
            return True
        if update.operation == 'device:purge':
            self.controller.state.busy = False
            if not isinstance(update.event, SelfDestructInitiatedEvent):
                self.phase = DevicePhase.PURGE_UNAVAILABLE
                self.title = 'Purge unavailable'
                self.detail = 'Keep the device powered.'
                self.critical(self.title)
            return True
        return False

    def remember_return(self) -> None:
        """Retains only presentation location and cover state for reversible input.

        Args:
            None
        Returns:
            None
        """
        self._return_route = self.controller.state.route
        self._return_covered = self.controller.state.covered

    def restore_return(self) -> None:
        """Restores a pre-arming view only before any destructive acceptance.

        Args:
            None
        Returns:
            None
        """
        self.phase = DevicePhase.IDLE
        self.progress = 0.0
        self._purge_requested = False
        state = self.controller.state
        state.route = self._return_route
        state.covered = self._return_covered
        self.feedback.indicator(IndicatorState.OFF)

    def _arm_purge(self) -> None:
        """Covers content and shows continuous-chord progress without authorization.

        Args:
            None
        Returns:
            None
        """
        if not self.enabled or self.controller.purge.active:
            return
        self.remember_return()
        self.phase = DevicePhase.PURGE_ARMING
        self.title = 'Hold both buttons'
        self.detail = 'Keep holding Power and PTT'
        self.progress = 0.0
        self.controller.state.covered = True
        self.controller.state.route = Route('V22')
        self.feedback.indicator(IndicatorState.PURGE_ARMING)
        self.feedback.haptic(HapticPattern.PURGE_ARMING)

    def _cancel_purge(self) -> None:
        """Cancels only pre-threshold arming and consumes input until release.

        Args:
            None
        Returns:
            None
        """
        if self.phase is DevicePhase.PURGE_ARMING and not self._purge_requested:
            self.phase = DevicePhase.PURGE_CANCELLED
            self.title = 'Cancelled'
            self.detail = 'Release both buttons'
            self.feedback.indicator(IndicatorState.OFF)

    def _request_purge(self) -> None:
        """Submits one exact-operation Core request; hardware supplies no proof.

        Args:
            None
        Returns:
            None
        """
        controller = self.controller
        client = controller.client
        snapshot = controller.state.snapshot
        if (
            self.phase is not DevicePhase.PURGE_ARMING
            or self._purge_requested
            or client is None
        ):
            self._purge_unavailable()
            return
        restriction = controller.security.restriction
        if self._return_covered and (
            restriction is None or not restriction.device_lifecycle
        ):
            self._purge_unavailable()
            return
        operation_id = secrets.token_hex(GuiLimits.MESSAGE_ID_BYTES)
        profile = snapshot.profile if snapshot is not None else None

        def request() -> IpcEvent | None:
            """Validates local binding before asking Core for authoritative acceptance.

            Args:
                None
            Returns:
                IpcEvent | None: Exact accepted destruction identity or no acceptance.
            """
            host_state = controller.context.host.profile_state()
            if host_state.remote or (
                profile is not None and host_state.profile != profile
            ):
                return None
            return client.request(
                SelfDestructCommand(operation_id), SelfDestructInitiatedEvent
            )

        if not controller.submit('device:purge', request):
            self._purge_unavailable()
            return
        self._purge_requested = True
        self.title = 'Purging profile'
        self.detail = 'Waiting for Core acceptance'

    def _purge_unavailable(self) -> None:
        """Shows a content-free denial without authentication details.

        Args:
            None
        Returns:
            None
        """
        self.phase = DevicePhase.PURGE_UNAVAILABLE
        self.title = 'Purge unavailable'
        self.detail = 'Release both buttons. Keep the device powered.'
        self.critical(self.title)

    def _poll_purge_shutdown(self) -> bool:
        """Requests power only after the exact operation is safe and terminal.

        Args:
            None
        Returns:
            bool: Whether a shutdown outcome changed presentation.
        """
        with self._purge_shutdown_lock:
            result, self._purge_shutdown_result = self._purge_shutdown_result, None
        if result is not None:
            self.controller.purge.record_shutdown(result)
            if result is not PlatformActionResult.ACCEPTED:
                self.critical('Power off unavailable')
            return True
        if self._purge_shutdown_requested or not self.controller.purge.shutdown_ready:
            return False
        self._purge_shutdown_requested = True
        bindings = self.bindings

        def request() -> None:
            """Invokes the fixed privileged adapter away from the native UI thread.

            Args:
                None
            Returns:
                None
            """
            outcome = PlatformActionResult.UNAVAILABLE
            if bindings is not None and bindings.shutdown is not None:
                try:
                    outcome = bindings.shutdown.request_shutdown()
                except Exception:
                    outcome = PlatformActionResult.FAILED
            with self._purge_shutdown_lock:
                self._purge_shutdown_result = outcome

        self._purge_shutdown_worker = threading.Thread(
            target=request, name='metor-gui-purge-shutdown', daemon=True
        )
        self._purge_shutdown_worker.start()
        return True

    def critical(self, status: str) -> None:
        """Applies the highest-priority non-identifying failure indication.

        Args:
            status: Safe visible status text.
        Returns:
            None
        """
        self.controller.state.status = status
        self.feedback.indicator(IndicatorState.CRITICAL_ERROR)

    def close(self) -> None:
        """Stops physical callbacks and clears actuator references idempotently.

        Args:
            None
        Returns:
            None
        """
        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            try:
                subscription.close()
            except Exception:
                pass
        with self._input_lock:
            self._samples.clear()
        self.feedback.indicator(IndicatorState.OFF)
