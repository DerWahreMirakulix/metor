"""Ordered physical input observations; hardware events do not grant authorization."""

from collections.abc import Callable
from dataclasses import dataclass
import math
from typing import Protocol


@dataclass(frozen=True)
class ButtonSample:
    """Complete physical levels; sequence gaps or invalidity require safe cancellation."""

    sequence: int
    observed_at: float
    ptt: bool
    power: bool
    valid: bool = True

    def __post_init__(self) -> None:
        """Validates complete levels without interpreting them as semantic actions.

        Args:
            None
        Returns:
            None
        """
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError('Invalid input sequence')
        if (
            type(self.observed_at) not in (int, float)
            or not math.isfinite(self.observed_at)
            or self.observed_at < 0
        ):
            raise ValueError('Invalid input timestamp')
        if any(type(value) is not bool for value in (self.ptt, self.power, self.valid)):
            raise ValueError('Invalid input levels')


class InputSubscription(Protocol):
    """Owns one input subscription; closing invalidates further callback delivery."""

    def close(self) -> None:
        """Stops delivery and releases adapter input resources idempotently.

        Args:
            None
        Returns:
            None
        """
        ...


class HardwareInputPort(Protocol):
    """Delivers serialized complete samples, including explicit input loss."""

    def subscribe(self, receive: Callable[[ButtonSample], None]) -> InputSubscription:
        """Starts ordered delivery to a bounded consumer with an initial level sample.

        Args:
            receive: Fast receiver; loss/overflow must invalidate the input session.
        Returns:
            InputSubscription: Explicit ownership of this subscription.
        """
        ...
