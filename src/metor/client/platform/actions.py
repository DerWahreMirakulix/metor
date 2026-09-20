"""Typed actuator requests; status and input contracts carry no actuator methods."""

from enum import Enum
from typing import Protocol


class PlatformActionResult(str, Enum):
    """Explicit outcome; acceptance never proves host power-off or Core preparation."""

    ACCEPTED = 'accepted'
    UNAVAILABLE = 'unavailable'
    DENIED = 'denied'
    FAILED = 'failed'
    UNKNOWN = 'unknown'


class IndicatorState(str, Enum):
    """Content-free output semantics after the caller's privacy filtering."""

    OFF = 'off'
    LOCKED_LIVE_ACTIVE = 'locked_live_active'
    TRANSMITTING = 'transmitting'
    RECEIVING = 'receiving'
    DUPLEX = 'duplex'
    PURGE_ARMING = 'purge_arming'
    CRITICAL_ERROR = 'critical_error'


class HapticPattern(str, Enum):
    """Finite semantic feedback, mapped to approved cadence by the adapter."""

    CAPTURE_ADMITTED = 'capture_admitted'
    CAPTURE_REJECTED = 'capture_rejected'
    PURGE_ARMING = 'purge_arming'


class IndicatorPort(Protocol):
    """Controls an optional indicator through nonblocking semantic requests."""

    def set_state(self, state: IndicatorState) -> PlatformActionResult:
        """Requests one privacy-filtered semantic indicator state.

        Args:
            state: Permitted content-free indication.
        Returns:
            PlatformActionResult: Immediate local admission outcome.
        """
        ...


class HapticsPort(Protocol):
    """Controls optional haptics through nonblocking finite requests."""

    def pulse(self, pattern: HapticPattern) -> PlatformActionResult:
        """Requests one permitted finite feedback pattern.

        Args:
            pattern: Semantic pattern, never an arbitrary command or timing payload.
        Returns:
            PlatformActionResult: Immediate local admission outcome.
        """
        ...


class ShutdownPort(Protocol):
    """Privileged local actuator, supplied only to an authorized lifecycle coordinator.

    Implementations enforce local deployment authority. Callers must first confirm
    Core preparation and exclusive host/runtime ownership. This protocol itself
    provides neither authorization nor a claim that shutdown has completed.
    """

    def request_shutdown(self) -> PlatformActionResult:
        """Requests the fixed authorized local operation without accepting shell text.

        Args:
            None
        Returns:
            PlatformActionResult: Admission outcome, not a power-off observation.
        """
        ...
