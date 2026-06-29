"""Managed-daemon startup status enums exposed outside the IPC boundary."""

from enum import Enum


class DaemonStatus(str, Enum):
    """Enumeration of local managed-daemon startup states."""

    LOCKED_MODE = 'locked_mode'
    ACTIVE = 'active'
    RUNTIME_ERROR = 'runtime_error'
