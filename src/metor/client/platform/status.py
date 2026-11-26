"""Read-only hardware observations, separate from input and actuator authority."""

from dataclasses import dataclass
from enum import Enum
import math
from typing import Protocol


class HardwareAvailability(str, Enum):
    """Distinguishes absent, stale and failed observations from usable information."""

    UNKNOWN = 'unknown'
    AVAILABLE = 'available'
    UNAVAILABLE = 'unavailable'
    PERMISSION_DENIED = 'permission_denied'
    FAILED = 'failed'


@dataclass(frozen=True)
class BatteryStatus:
    """Optional power facts; unknown values never imply an empty or full battery."""

    availability: HardwareAvailability = HardwareAvailability.UNKNOWN
    charge_fraction: float | None = None
    charging: bool | None = None
    external_power: bool | None = None

    def __post_init__(self) -> None:
        """Rejects malformed facts and values attached to unavailable observations.

        Args:
            None
        Returns:
            None
        """
        if not isinstance(self.availability, HardwareAvailability):
            raise ValueError('Invalid hardware availability')
        charge = self.charge_fraction
        if charge is not None and (
            type(charge) not in (int, float)
            or not math.isfinite(charge)
            or not 0 <= charge <= 1
        ):
            raise ValueError('Invalid battery charge fraction')
        if any(
            value is not None and type(value) is not bool
            for value in (self.charging, self.external_power)
        ):
            raise ValueError('Invalid power observation')
        if self.availability is not HardwareAvailability.AVAILABLE and any(
            value is not None for value in (charge, self.charging, self.external_power)
        ):
            raise ValueError('Unavailable hardware cannot supply current facts')


@dataclass(frozen=True)
class HardwareStatus:
    """One atomic observation with an explicit monotonic freshness deadline."""

    observed_at: float
    valid_until: float
    battery: BatteryStatus = BatteryStatus()

    def __post_init__(self) -> None:
        """Rejects non-finite or inverted observation intervals.

        Args:
            None
        Returns:
            None
        """
        if (
            any(
                type(value) not in (int, float) or not math.isfinite(value)
                for value in (self.observed_at, self.valid_until)
            )
            or not 0 <= self.observed_at <= self.valid_until
        ):
            raise ValueError('Invalid hardware observation interval')
        if not isinstance(self.battery, BatteryStatus):
            raise ValueError('Invalid battery observation')

    def current_battery(self, now: float) -> BatteryStatus:
        """Returns unknown after expiry or a clock discontinuity.

        Args:
            now: Consumer's monotonic time from the same clock domain.
        Returns:
            BatteryStatus: Current facts or an explicit unknown observation.
        """
        if (
            type(now) not in (int, float)
            or not math.isfinite(now)
            or not self.observed_at <= now < self.valid_until
        ):
            return BatteryStatus()
        return self.battery


class HardwareStatusPort(Protocol):
    """Returns a cached snapshot; driver I/O never blocks the frontend loop."""

    def snapshot(self) -> HardwareStatus | None:
        """Reads the latest observation without activating hardware or requesting power.

        Args:
            None
        Returns:
            HardwareStatus | None: Cached facts; none means no observation yet.
        """
        ...
