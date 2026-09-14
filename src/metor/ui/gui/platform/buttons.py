"""Atomic physical PTT/Power arbitration with continuous timing and consumed release barriers."""

from dataclasses import dataclass
from enum import Enum
import math

from metor.ui.gui.constants import GuiLimits


class ButtonAction(str, Enum):
    """Semantic requests; hardware observations never grant lifecycle authorization."""

    PTT_DOWN = 'ptt_down'
    PTT_UP = 'ptt_up'
    STOP_CAPTURE = 'stop_capture'
    LOCK = 'lock'
    POWER_MENU = 'power_menu'
    ARM_PURGE = 'arm_purge'
    CANCEL_PURGE = 'cancel_purge'
    REQUEST_PURGE = 'request_purge'


@dataclass(frozen=True)
class ButtonResult:
    """Finite actions produced by a single complete physical state observation."""

    actions: tuple[ButtonAction, ...] = ()
    progress: float = 0.0
    release_required: bool = False


class PhysicalButtons:
    """Consumes chord edges before ordinary actions; adapters supply monotonic complete state."""

    def __init__(self) -> None:
        """Creates released input state without registering an OS key or opening a driver.

        Args:
            None
        Returns:
            None
        """
        self.ptt = False
        self.power = False
        self._power_since: float | None = None
        self._chord_since: float | None = None
        self._menu_opened = False
        self._consumed = False
        self._triggered = False
        self._last_time = 0.0

    def sample(self, *, ptt: bool, power: bool, now: float) -> ButtonResult:
        """Processes one fresh adapter snapshot, including repeats and poll ticks.

        Args:
            ptt: Current physical PTT level, not an inferred keyboard shortcut.
            power: Current distinct physical Power level.
            now: Monotonic timestamp from the input owner.
        Returns:
            ButtonResult: At most one arming/trigger sequence; cancelled edges stay consumed.
        """
        if not math.isfinite(now) or now < self._last_time:
            return self.lost()
        self._last_time = now
        previous_ptt, previous_power = self.ptt, self.power
        self.ptt, self.power = ptt, power
        if self._consumed:
            if not ptt and not power:
                self._reset()
            return ButtonResult(release_required=self._consumed)
        if self._chord_since is not None:
            if not (ptt and power):
                self._consumed = True
                self._chord_since = None
                if not ptt and not power:
                    self._reset()
                return ButtonResult(
                    (ButtonAction.CANCEL_PURGE,), release_required=self._consumed
                )
            progress = min(1.0, (now - self._chord_since) / GuiLimits.PURGE_SECONDS)
            if progress == 1.0:
                self._triggered = True
                self._consumed = True
                return ButtonResult((ButtonAction.REQUEST_PURGE,), progress, True)
            return ButtonResult(progress=progress, release_required=True)
        if ptt and power:
            self._chord_since = now
            self._power_since = None
            return ButtonResult(
                (ButtonAction.STOP_CAPTURE, ButtonAction.ARM_PURGE),
                release_required=True,
            )
        actions: list[ButtonAction] = []
        if ptt and not previous_ptt:
            actions.append(ButtonAction.PTT_DOWN)
        elif previous_ptt and not ptt:
            actions.append(ButtonAction.PTT_UP)
        if power and not previous_power:
            self._power_since = now
            self._menu_opened = False
        if power and self._power_since is not None and not self._menu_opened:
            if now - self._power_since >= GuiLimits.POWER_SECONDS:
                self._menu_opened = True
                actions.append(ButtonAction.POWER_MENU)
        elif previous_power and not power:
            if not self._menu_opened:
                actions.append(ButtonAction.LOCK)
            self._power_since = None
            self._menu_opened = False
        return ButtonResult(tuple(actions))

    def lost(self) -> ButtonResult:
        """Stops unsafe input on unplug/focus loss without inventing a released physical state.

        Args:
            None
        Returns:
            ButtonResult: Stop and optional arming cancellation; real release is still required.
        """
        actions = [ButtonAction.STOP_CAPTURE]
        if self._chord_since is not None and not self._triggered:
            actions.append(ButtonAction.CANCEL_PURGE)
        self._consumed = True
        self._chord_since = None
        self._power_since = None
        return ButtonResult(tuple(actions), release_required=True)

    def _reset(self) -> None:
        """Rearms only after an explicit complete snapshot reports both controls released.

        Args:
            None
        Returns:
            None
        """
        self._consumed = False
        self._triggered = False
        self._chord_since = None
        self._power_since = None
        self._menu_opened = False
