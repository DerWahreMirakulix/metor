"""Content-free hardware feedback actions, independent of status and input."""

from metor.client.platform import (
    HapticPattern,
    HapticsPort,
    IndicatorPort,
    IndicatorState,
)


class HardwareFeedback:
    """Requests finite indicator and haptic actions without notification fallback."""

    def __init__(
        self, indicator: IndicatorPort | None, haptics: HapticsPort | None
    ) -> None:
        """Retains only optional capability-specific action ports.

        Args:
            indicator: Privacy-filtered semantic indicator interface.
            haptics: Finite semantic haptic interface.
        Returns:
            None
        """
        self._indicator = indicator
        self._haptics = haptics

    def indicator(self, state: IndicatorState) -> None:
        """Requests a permitted semantic indicator state.

        Args:
            state: Content-free state selected after privacy filtering.
        Returns:
            None
        """
        if self._indicator is not None:
            try:
                self._indicator.set_state(state)
            except Exception:
                pass

    def haptic(self, pattern: HapticPattern) -> None:
        """Requests one finite haptic pattern.

        Args:
            pattern: Permitted semantic feedback pattern.
        Returns:
            None
        """
        if self._haptics is not None:
            try:
                self._haptics.pulse(pattern)
            except Exception:
                pass
