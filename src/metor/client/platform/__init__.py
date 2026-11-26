"""Frontend-independent typed platform contracts, with no drivers or toolkit imports."""

from .actions import (
    HapticPattern,
    HapticsPort,
    IndicatorPort,
    IndicatorState,
    PlatformActionResult,
    ShutdownPort,
)
from .adapter import (
    AdapterParameter,
    PLATFORM_ADAPTER_CONTRACT_VERSION,
    PlatformAdapterFactory,
    PlatformAdapterPlan,
    PlatformAdapterSession,
)
from .audio import AudioCapabilities, AudioEndpoint, CapturePort, OutputPort
from .bindings import PlatformBindings
from .inputs import ButtonSample, HardwareInputPort, InputSubscription
from .status import (
    BatteryStatus,
    HardwareAvailability,
    HardwareStatus,
    HardwareStatusPort,
)
from .settings import (
    DeviceSettingDescriptor,
    DeviceSettingKind,
    DeviceSettingResult,
    DeviceSettingStatus,
    DeviceSettingValue,
    HardwareSettingsPort,
    MAX_DEVICE_SETTINGS,
    validate_descriptors,
)

__all__ = [
    'AdapterParameter',
    'AudioCapabilities',
    'AudioEndpoint',
    'BatteryStatus',
    'ButtonSample',
    'CapturePort',
    'DeviceSettingDescriptor',
    'DeviceSettingKind',
    'DeviceSettingResult',
    'DeviceSettingStatus',
    'DeviceSettingValue',
    'HardwareAvailability',
    'HardwareInputPort',
    'HardwareStatus',
    'HardwareStatusPort',
    'HardwareSettingsPort',
    'HapticPattern',
    'HapticsPort',
    'IndicatorPort',
    'IndicatorState',
    'InputSubscription',
    'OutputPort',
    'PLATFORM_ADAPTER_CONTRACT_VERSION',
    'PlatformActionResult',
    'PlatformBindings',
    'PlatformAdapterFactory',
    'PlatformAdapterPlan',
    'PlatformAdapterSession',
    'MAX_DEVICE_SETTINGS',
    'ShutdownPort',
    'validate_descriptors',
]
