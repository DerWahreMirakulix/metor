"""Finite device lifecycle presentation states without toolkit dependencies."""

from enum import Enum


class DevicePhase(str, Enum):
    """Visible phases that never imply Core or OS success by themselves."""

    IDLE = 'idle'
    POWER_MENU = 'power_menu'
    POWER_PREPARING = 'power_preparing'
    POWER_FAILED = 'power_failed'
    POWERING_OFF = 'powering_off'
    PURGE_ARMING = 'purge_arming'
    PURGE_CANCELLED = 'purge_cancelled'
    PURGE_UNAVAILABLE = 'purge_unavailable'
