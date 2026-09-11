"""Typed discovery and launch contract for independently installed frontends."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import Protocol, cast


FRONTEND_ENTRY_POINT_GROUP: str = 'metor.ui_frontends'
FRONTEND_LAUNCH_CONTRACT_VERSION: int = 1


class FrontendLaunchError(RuntimeError):
    """Reports an unavailable, conflicting, or broken frontend installation."""


@dataclass(frozen=True)
class FrontendLaunchContext:
    """Carries frontend-neutral bootstrap state into one selected UI.

    Args:
        profile (str): Active profile name.
        remote (bool): Whether the profile connects to a remote daemon.
        port (int | None): Resolved daemon IPC port override, when supplied.
        start_daemon (bool | None): Invocation-specific daemon autostart override.
        daemon_started_by_launcher (bool): Whether the base CLI started the daemon.
        session_auth_secret (str | None): One-use startup credential retained only
            in process memory for the selected frontend.
        contract_version (int): Public frontend launch-contract generation.

    Returns:
        None
    """

    profile: str
    remote: bool = False
    port: int | None = None
    start_daemon: bool | None = None
    daemon_started_by_launcher: bool = False
    session_auth_secret: str | None = field(default=None, repr=False)
    contract_version: int = FRONTEND_LAUNCH_CONTRACT_VERSION


class FrontendEntry(Protocol):
    """Defines the callable published by a frontend distribution."""

    contract_version: int

    def __call__(self, context: FrontendLaunchContext) -> int:
        """Launches the frontend with one versioned context.

        Args:
            context (FrontendLaunchContext): Base-CLI bootstrap context.

        Returns:
            int: Process exit status.
        """
        ...


@dataclass(frozen=True)
class FrontendDescriptor:
    """Describes one installed frontend without importing its implementation.

    Args:
        frontend_id (str): Stable CLI selection identifier.
        distribution (str): Distribution that registered the entry point.
        value (str): Import metadata value, retained for diagnostics.

    Returns:
        None
    """

    frontend_id: str
    distribution: str
    value: str


@dataclass(frozen=True)
class LoadedFrontend:
    """Holds one validated selected frontend entry point.

    Args:
        descriptor (FrontendDescriptor): Safe installed-package metadata.
        entry (FrontendEntry): Selected callable after contract validation.

    Returns:
        None
    """

    descriptor: FrontendDescriptor
    entry: FrontendEntry


def _frontend_entry_points() -> tuple[metadata.EntryPoint, ...]:
    """Returns installed frontend metadata without loading implementations.

    Args:
        None

    Returns:
        tuple[metadata.EntryPoint, ...]: Installed frontend entry points.
    """
    return tuple(metadata.entry_points().select(group=FRONTEND_ENTRY_POINT_GROUP))


def _discover_frontend_entries() -> dict[
    str, tuple[FrontendDescriptor, metadata.EntryPoint]
]:
    """Captures one internally consistent entry-point discovery snapshot."""
    discovered: dict[str, tuple[FrontendDescriptor, metadata.EntryPoint]] = {}
    for entry_point in _frontend_entry_points():
        distribution: str = (
            entry_point.dist.name
            if entry_point.dist is not None
            else 'unknown distribution'
        )
        descriptor = FrontendDescriptor(
            frontend_id=entry_point.name,
            distribution=distribution,
            value=entry_point.value,
        )
        previous = discovered.get(entry_point.name)
        if previous is not None:
            raise FrontendLaunchError(
                f"Frontend ID '{entry_point.name}' is registered by both "
                f"'{previous[0].distribution}' and '{distribution}'."
            )
        discovered[entry_point.name] = (descriptor, entry_point)
    return discovered


def discover_frontends() -> dict[str, FrontendDescriptor]:
    """Builds a unique installed-frontend inventory without importing UIs.

    Args:
        None

    Raises:
        FrontendLaunchError: If multiple distributions claim the same frontend ID.

    Returns:
        dict[str, FrontendDescriptor]: Descriptor indexed by stable frontend ID.
    """
    return {
        frontend_id: descriptor
        for frontend_id, (descriptor, _) in _discover_frontend_entries().items()
    }


def load_frontend(frontend_id: str) -> LoadedFrontend:
    """Loads and validates only the selected installed frontend.

    Args:
        frontend_id (str): Explicitly resolved frontend identifier.

    Raises:
        FrontendLaunchError: If the frontend is absent, conflicting, broken, or
            uses an incompatible public launch contract.

    Returns:
        LoadedFrontend: Validated callable and diagnostic metadata.
    """
    discovered = _discover_frontend_entries()
    selected = discovered.get(frontend_id)
    if selected is None:
        raise FrontendLaunchError(
            f"Frontend '{frontend_id}' is not installed. Install the matching "
            f"'metor-ui-{frontend_id}' distribution."
        )
    descriptor, entry_point = selected
    try:
        raw_entry = entry_point.load()
    except Exception as exc:
        raise FrontendLaunchError(
            f"Frontend '{frontend_id}' could not be loaded from "
            f"'{descriptor.distribution}': {exc.__class__.__name__}. "
            'Reinstall it with its optional runtime dependencies.'
        ) from exc
    if not callable(raw_entry):
        raise FrontendLaunchError(
            f"Frontend '{frontend_id}' from '{descriptor.distribution}' does not "
            'expose a callable launcher.'
        )
    contract_version = getattr(raw_entry, 'contract_version', None)
    if type(contract_version) is not int or (
        contract_version != FRONTEND_LAUNCH_CONTRACT_VERSION
    ):
        raise FrontendLaunchError(
            f"Frontend '{frontend_id}' from '{descriptor.distribution}' uses an "
            'incompatible or missing launch-contract version.'
        )
    return LoadedFrontend(descriptor, cast(FrontendEntry, raw_entry))


def invoke_frontend(frontend: LoadedFrontend, context: FrontendLaunchContext) -> int:
    """Invokes one already validated frontend without rediscovering plugins."""
    frontend_id = frontend.descriptor.frontend_id
    try:
        status = frontend.entry(context)
    except FrontendLaunchError:
        raise
    except Exception as exc:
        raise FrontendLaunchError(
            f"Frontend '{frontend_id}' failed to start: {exc.__class__.__name__}."
        ) from exc
    if type(status) is not int:
        raise FrontendLaunchError(
            f"Frontend '{frontend_id}' returned an invalid launch status."
        )
    return status


def launch_frontend(frontend_id: str, context: FrontendLaunchContext) -> int:
    """Loads only the selected frontend and invokes its typed entry point.

    Args:
        frontend_id (str): Explicitly resolved frontend identifier.
        context (FrontendLaunchContext): Versioned base-CLI bootstrap context.

    Raises:
        FrontendLaunchError: If metadata is missing, conflicting, unloadable, or
            does not expose the public callable contract.

    Returns:
        int: Frontend process exit status.
    """
    return invoke_frontend(load_frontend(frontend_id), context)
