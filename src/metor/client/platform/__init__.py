"""Frontend-independent typed platform contracts, with no drivers or toolkit imports."""

from .actions import (
    HapticPattern,
    HapticsPort,
    IndicatorPort,
    IndicatorState,
    PlatformActionResult,
    ShutdownPort,
)
from .audio import AudioCapabilities, AudioEndpoint, CapturePort, OutputPort
from .inputs import ButtonSample, HardwareInputPort, InputSubscription
from .status import (
    BatteryStatus,
    HardwareAvailability,
    HardwareStatus,
    HardwareStatusPort,
)

__all__ = [
    'AudioCapabilities',
    'AudioEndpoint',
    'BatteryStatus',
    'ButtonSample',
    'CapturePort',
    'HardwareAvailability',
    'HardwareInputPort',
    'HardwareStatus',
    'HardwareStatusPort',
    'HapticPattern',
    'HapticsPort',
    'IndicatorPort',
    'IndicatorState',
    'InputSubscription',
    'OutputPort',
    'PlatformActionResult',
    'ShutdownPort',
]
