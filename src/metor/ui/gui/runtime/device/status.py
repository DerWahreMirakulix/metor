"""Cached hardware-status projection kept separate from input and actions."""

from metor.client.platform import HardwareAvailability, HardwareStatusPort
from metor.ui.gui.constants import GuiLimits


class HardwareStatusProjection:
    """Polls only a nonblocking cached status port at the bounded GUI cadence."""

    def __init__(self, port: HardwareStatusPort | None) -> None:
        """Creates an empty projection without activating hardware.

        Args:
            port: Independent read-only cached status interface.
        Returns:
            None
        """
        self._port = port
        self._next = 0.0
        self.battery_status = ''

    def poll(self, now: float) -> bool:
        """Refreshes content-free battery text when the cadence permits.

        Args:
            now: Current monotonic time in the status snapshot's clock domain.
        Returns:
            bool: Whether the displayed status changed.
        """
        if now < self._next:
            return False
        self._next = now + GuiLimits.HARDWARE_STATUS_SECONDS
        text = ''
        if self._port is not None:
            try:
                snapshot = self._port.snapshot()
                battery = (
                    snapshot.current_battery(now) if snapshot is not None else None
                )
                if (
                    battery is not None
                    and battery.availability is HardwareAvailability.AVAILABLE
                    and battery.charge_fraction is not None
                ):
                    text = f'Battery {round(battery.charge_fraction * 100)}%'
                    if battery.charging is True:
                        text += ' · Charging'
                    elif battery.external_power is False:
                        text += ' · On battery'
                elif battery is not None:
                    text = 'Battery status unavailable'
            except Exception:
                text = 'Battery status unavailable'
        if text == self.battery_status:
            return False
        self.battery_status = text
        return True
