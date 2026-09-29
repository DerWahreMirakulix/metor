"""Trusted local adapter factory and session lifecycle contracts."""

from collections.abc import Mapping
from typing import Protocol, TypeAlias

from .bindings import PlatformBindings


PLATFORM_ADAPTER_CONTRACT_VERSION = 1
AdapterParameter: TypeAlias = bool | int | float | str


class PlatformAdapterSession(Protocol):
    """Owns local device resources independently of the communication profile.

    Implementations serialize close against in-flight port calls and bound both
    calls and cleanup. GUI worker threads cannot interrupt a hung driver.
    """

    @property
    def bindings(self) -> PlatformBindings:
        """Expose typed, nonprivileged ports for the selected adapter."""
        ...

    def close(self) -> None:
        """Release resources idempotently and safely with an in-flight port call."""
        ...


class PlatformAdapterPlan(Protocol):
    """Validated deployment parameters and declared capabilities before I/O."""

    @property
    def capabilities(self) -> frozenset[str]:
        """Declare supported display, input and optional local capabilities."""
        ...

    @property
    def resource_id(self) -> str:
        """Name one local device resource independently of profile or adapter ID."""
        ...

    @property
    def exclusive(self) -> bool:
        """Request a host-held cross-process lease for this local resource."""
        ...

    def open(self) -> PlatformAdapterSession:
        """Activate only validated resources, releasing any partial start on error."""
        ...


class PlatformAdapterFactory(Protocol):
    """Installed trusted provider; importing it must not activate hardware."""

    adapter_id: str
    contract_version: int

    def prepare(
        self, parameters: Mapping[str, AdapterParameter]
    ) -> PlatformAdapterPlan:
        """Validate the bounded adapter-specific TOML area without device I/O."""
        ...
