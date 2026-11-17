"""Public platform capability and device-description boundary for the GUI."""

from .configuration import (
    DeviceConfiguration,
    DeviceConfigurationError,
    read_configuration,
)
from .providers import ActivePlatform, open_platform, prepare_platform

__all__ = [
    'ActivePlatform',
    'DeviceConfiguration',
    'DeviceConfigurationError',
    'open_platform',
    'prepare_platform',
    'read_configuration',
]
