"""Select one installed trusted adapter without importing unrelated providers."""

from dataclasses import dataclass
from importlib import metadata
import re
from typing import ContextManager, cast

from metor.client import FrontendHost
from metor.client.platform import (
    PLATFORM_ADAPTER_CONTRACT_VERSION,
    PlatformAdapterFactory,
    PlatformAdapterPlan,
    PlatformAdapterSession,
    PlatformBindings,
)

# Local Package Imports
from .configuration import DeviceConfiguration, DeviceConfigurationError


ENTRY_POINT_GROUP = 'metor.platform_adapters'
_CAPABILITIES = frozenset({'input', 'indicator', 'haptics', 'power', 'settings'})
_RESOURCE_ID = re.compile(r'[a-z][a-z0-9_.-]{0,63}')


@dataclass
class ActivePlatform:
    """Own one adapter session until all local GUI consumers have stopped."""

    session: PlatformAdapterSession
    bindings: PlatformBindings
    resource_lock: ContextManager[object] | None = None

    def close(self) -> None:
        """Release the selected provider's resources idempotently."""
        try:
            self.session.close()
        finally:
            lock, self.resource_lock = self.resource_lock, None
            if lock is not None:
                lock.__exit__(None, None, None)


def prepare_platform(
    configuration: DeviceConfiguration, injected: PlatformBindings | None
) -> PlatformAdapterPlan | None:
    """Validate the selected installed factory and parameters before device I/O.

    The owner-checked device file and installed package are deployment trust
    decisions. Metadata inspection does not import providers; only the one
    explicitly selected entry point is loaded.
    """
    if configuration.mode != 'device':
        return None
    if injected is not None:
        if configuration.adapter_parameters:
            raise DeviceConfigurationError(
                'Injected platform cannot use installed adapter parameters'
            )
        configuration.activate_platform(injected)
        return None
    adapter_id = configuration.adapter_id
    selected = [
        entry
        for entry in metadata.entry_points(group=ENTRY_POINT_GROUP)
        if entry.name == adapter_id
    ]
    if not selected:
        raise DeviceConfigurationError('Selected device adapter is not installed')
    if len(selected) != 1:
        raise DeviceConfigurationError('Device adapter identifier is ambiguous')
    try:
        provider = cast(PlatformAdapterFactory, selected[0].load())
    except Exception as exc:
        raise DeviceConfigurationError(
            'Selected device adapter could not load'
        ) from exc
    if (
        getattr(provider, 'adapter_id', None) != adapter_id
        or type(getattr(provider, 'contract_version', None)) is not int
        or provider.contract_version != PLATFORM_ADAPTER_CONTRACT_VERSION
        or not callable(getattr(provider, 'prepare', None))
    ):
        raise DeviceConfigurationError(
            'Selected device adapter contract is incompatible'
        )
    try:
        plan = provider.prepare(dict(configuration.adapter_parameters))
        capabilities = plan.capabilities
        resource_id = plan.resource_id
        exclusive = plan.exclusive
    except Exception as exc:
        raise DeviceConfigurationError(
            'Selected device adapter configuration is invalid'
        ) from exc
    if (
        not isinstance(capabilities, frozenset)
        or not capabilities <= _CAPABILITIES
        or 'input' not in capabilities
        or type(resource_id) is not str
        or _RESOURCE_ID.fullmatch(resource_id) is None
        or type(exclusive) is not bool
    ):
        raise DeviceConfigurationError(
            'Selected device adapter capabilities are invalid'
        )
    for enabled, capability in (
        (configuration.indicator, 'indicator'),
        (configuration.haptics, 'haptics'),
        (configuration.power, 'power'),
    ):
        if enabled and capability not in capabilities:
            raise DeviceConfigurationError(
                f'{capability}: selected capability unavailable'
            )
    if not callable(getattr(plan, 'open', None)):
        raise DeviceConfigurationError(
            'Selected device adapter contract is incompatible'
        )
    return plan


def open_platform(
    configuration: DeviceConfiguration,
    plan: PlatformAdapterPlan,
    host: FrontendHost,
) -> ActivePlatform:
    """Open one validated plan and release a mismatched partial session."""
    session: PlatformAdapterSession | None = None
    resource_lock: ContextManager[object] | None = None
    try:
        if plan.exclusive:
            resource_lock = host.device_resource_lock(plan.resource_id)
            try:
                resource_lock.__enter__()
            except TimeoutError as exc:
                raise DeviceConfigurationError(
                    'Selected device resource is already in use'
                ) from exc
        session = plan.open()
        raw = session.bindings
        if not isinstance(raw, PlatformBindings):
            raise DeviceConfigurationError(
                'Selected device adapter bindings are invalid'
            )
        for capability, available in (
            ('indicator', raw.indicator),
            ('haptics', raw.haptics),
            ('power', raw.shutdown),
            ('settings', raw.settings),
        ):
            if (capability in plan.capabilities) != (available is not None):
                raise DeviceConfigurationError(
                    'Selected device adapter capabilities changed during activation'
                )
        bindings = configuration.activate_platform(raw)
        assert bindings is not None
        return ActivePlatform(session, bindings, resource_lock)
    except Exception as exc:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
        if resource_lock is not None:
            resource_lock.__exit__(None, None, None)
        if isinstance(exc, DeviceConfigurationError):
            raise
        raise DeviceConfigurationError(
            'Selected device adapter could not start'
        ) from exc
