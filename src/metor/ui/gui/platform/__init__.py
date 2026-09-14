"""Public platform capability and device-description boundary for the GUI."""

from .configuration import (
    DeviceConfiguration,
    DeviceConfigurationError,
    read_configuration,
)

__all__ = ['DeviceConfiguration', 'DeviceConfigurationError', 'read_configuration']
