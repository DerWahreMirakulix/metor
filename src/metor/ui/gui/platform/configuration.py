"""Bounded, strict device configuration validation before any driver activation."""

from dataclasses import dataclass
import math
from pathlib import Path
import stat
import tomllib

from metor.client.platform import PlatformBindings
from metor.ui.gui.constants import Geometry, GuiLimits


class DeviceConfigurationError(ValueError):
    """Reports a safe field/configuration error without rendering file content."""


@dataclass(frozen=True)
class DeviceConfiguration:
    """Validated display and mode; no secrets, peer data or arbitrary drivers."""

    mode: str = 'desktop'
    width_px: int = Geometry.DEFAULT_WIDTH
    height_px: int = Geometry.DEFAULT_HEIGHT
    scale: float = 1.0
    rotation_deg: int = 0
    touch: bool = False
    indicator: bool = False
    haptics: bool = False
    power: bool = False
    source: str | None = None

    @property
    def logical_size(self) -> tuple[float, float]:
        """Returns geometry after mounting rotation and declared density.

        Args:
            None
        Returns:
            tuple[float, float]: Usable logical width and height.
        """
        width, height = self.width_px, self.height_px
        if self.rotation_deg in (90, 270):
            width, height = height, width
        return width / self.scale, height / self.scale

    def activate_platform(
        self, platform: PlatformBindings | None
    ) -> PlatformBindings | None:
        """Limits injected optional ports to capabilities declared by this file.

        Args:
            platform: Prevalidated deployment ports matching the parsed adapter ID.
        Returns:
            PlatformBindings | None: Configuration-filtered ports for the GUI.
        """
        if self.mode != 'device' or platform is None:
            return None
        return PlatformBindings(
            platform.adapter_id,
            platform.inputs,
            platform.shutdown if self.power else None,
            status=platform.status,
            indicator=platform.indicator if self.indicator else None,
            haptics=platform.haptics if self.haptics else None,
        )


def _table(value: object, allowed: set[str], name: str) -> dict[str, object]:
    """Validates an exact table shape without exposing unknown input values.

    Args:
        value: Parsed candidate table.
        allowed: Supported fields.
        name: Safe schema location.
    Returns:
        dict[str, object]: Validated table.
    """
    if not isinstance(value, dict) or any(key not in allowed for key in value):
        raise DeviceConfigurationError(f'{name}: invalid or unknown fields')
    return value


def _integer(value: object, minimum: int, maximum: int, name: str) -> int:
    """Rejects booleans and out-of-range device geometry.

    Args:
        value: Parsed value.
        minimum: Inclusive bound.
        maximum: Inclusive bound.
        name: Safe field name.
    Returns:
        int: Validated integer.
    """
    if type(value) is not int or not minimum <= value <= maximum:
        raise DeviceConfigurationError(f'{name}: invalid integer or range')
    return value


def read_configuration(
    path: str | None,
    simulator: bool,
    platform: PlatformBindings | None = None,
) -> DeviceConfiguration:
    """Resolves explicit mode and validates before host work or driver creation.

    Args:
        path: Absolute requested file, or no file for desktop defaults.
        simulator: Explicit simulator flag; never inferred from a file.
        platform: Prevalidated physical ports supplied by the deployment owner.
    Returns:
        DeviceConfiguration: Safe description; physical support fails closed.
    """
    if path is None:
        if platform is not None:
            raise DeviceConfigurationError(
                'Physical platform bindings require an explicit device configuration.'
            )
        return DeviceConfiguration(mode='simulator' if simulator else 'desktop')
    if simulator and platform is not None:
        raise DeviceConfigurationError(
            'Simulator cannot activate physical platform bindings.'
        )
    if not path.strip():
        raise DeviceConfigurationError('Device configuration path must not be empty')
    location = Path(path)
    try:
        metadata = location.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise DeviceConfigurationError(
                'Device configuration must be a regular file'
            )
        if metadata.st_mode & stat.S_IWOTH:
            raise DeviceConfigurationError('Device configuration is world-writable')
        with location.open('rb') as source:
            data = source.read(GuiLimits.DEVICE_BYTES + 1)
        if len(data) > GuiLimits.DEVICE_BYTES:
            raise DeviceConfigurationError('Device configuration exceeds 64 KiB')
        parsed = tomllib.loads(data.decode('utf-8'))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise DeviceConfigurationError(
            f'Device configuration could not be read: {location}. '
            'Device mode was requested; desktop fallback is disabled.'
        ) from exc
    tables = _table(
        parsed,
        {
            'schema_version',
            'display',
            'input',
            'audio',
            'camera',
            'indicator',
            'haptics',
            'power',
            'clipboard',
            'drivers',
        },
        'device',
    )
    _integer(tables.get('schema_version'), 1, 1, 'schema_version')
    display = _table(
        tables.get('display'),
        {
            'adapter',
            'width_px',
            'height_px',
            'rotation_deg',
            'scale',
            'output',
        },
        'display',
    )
    inputs = _table(
        tables.get('input'),
        {
            'adapter',
            'ptt_binding',
            'power_binding',
            'touch',
        },
        'input',
    )
    expected_adapter = (
        'simulator'
        if simulator
        else (platform.adapter_id if platform is not None else None)
    )
    for table in (display, inputs):
        if table.get('adapter') != expected_adapter:
            raise DeviceConfigurationError('Unsupported device adapter')
    for key in ('ptt_binding', 'power_binding'):
        if inputs.get(key) != {'ptt_binding': 'ptt', 'power_binding': 'power'}[key]:
            raise DeviceConfigurationError(f'input.{key}: unsupported binding')
    touch = inputs.get('touch', False)
    if type(touch) is not bool:
        raise DeviceConfigurationError('input.touch: boolean required')
    rotation = _integer(display.get('rotation_deg', 0), 0, 270, 'display.rotation_deg')
    if rotation not in (0, 90, 180, 270):
        raise DeviceConfigurationError('display.rotation_deg: unsupported rotation')
    scale = display.get('scale', 1.0)
    if type(scale) not in (int, float) or not isinstance(scale, (int, float)):
        raise DeviceConfigurationError('display.scale: finite number required')
    if (
        not math.isfinite(scale)
        or not GuiLimits.MIN_SCALE <= scale <= GuiLimits.MAX_SCALE
    ):
        raise DeviceConfigurationError('display.scale: unsupported range')
    if 'output' in display:
        raise DeviceConfigurationError('display.output: unsupported simulator output')
    optional_ports = {
        'indicator': platform.indicator if platform is not None else None,
        'haptics': platform.haptics if platform is not None else None,
        'power': platform.shutdown if platform is not None else None,
    }
    enabled_ports: dict[str, bool] = {}
    for key in ('audio', 'camera', 'indicator', 'haptics', 'power'):
        enabled_ports[key] = False
        if key in tables:
            optional = _table(tables[key], {'adapter'}, key)
            supported = (
                expected_adapter
                if key in optional_ports and optional_ports[key] is not None
                else 'none'
            )
            if optional.get('adapter') != supported:
                raise DeviceConfigurationError(f'{key}: unsupported adapter')
            enabled_ports[key] = optional.get('adapter') == expected_adapter
    if 'clipboard' in tables:
        clipboard = _table(tables['clipboard'], {'policy'}, 'clipboard')
        if clipboard.get('policy') != 'disabled':
            raise DeviceConfigurationError('clipboard: unsupported policy')
    if 'drivers' in tables:
        _table(tables['drivers'], set(), 'drivers')
    config = DeviceConfiguration(
        mode='simulator' if simulator else 'device',
        width_px=_integer(
            display.get('width_px'), 1, GuiLimits.MAX_PIXELS, 'display.width_px'
        ),
        height_px=_integer(
            display.get('height_px'), 1, GuiLimits.MAX_PIXELS, 'display.height_px'
        ),
        rotation_deg=rotation,
        scale=float(scale),
        touch=touch,
        indicator=enabled_ports['indicator'],
        haptics=enabled_ports['haptics'],
        power=enabled_ports['power'],
        source=str(location),
    )
    width, height = config.logical_size
    if width < Geometry.MIN_WIDTH or height < Geometry.MIN_HEIGHT:
        raise DeviceConfigurationError(
            'Display requires at least 360 × 640 logical units'
        )
    if not simulator and platform is None:
        raise DeviceConfigurationError(
            'Physical device adapter is not installed. Simulator requires --simulator.'
        )
    return config
