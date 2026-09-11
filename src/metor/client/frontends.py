"""Typed discovery and launch contract for independently installed frontends."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import metadata
import threading
from typing import Optional, Protocol, cast


FRONTEND_ENTRY_POINT_GROUP: str = 'metor.ui_frontends'
FRONTEND_LAUNCH_CONTRACT_VERSION: int = 2


class FrontendLaunchError(RuntimeError):
    """Reports an unavailable, conflicting, or broken frontend installation."""


class FrontendBootstrapReason(str, Enum):
    """Machine-readable outcomes for a recoverable bootstrap attempt."""

    MISSING_PROFILE = 'missing_profile'
    INVALID_CONFIGURATION = 'invalid_configuration'
    CANCELLED = 'cancelled'
    UNREACHABLE = 'unreachable'
    START_FAILED = 'start_failed'
    INCOMPATIBLE = 'incompatible'
    BUSY = 'busy'


class FrontendBootstrapError(RuntimeError):
    """Reports a user-visible host bootstrap outcome with its process status."""

    def __init__(
        self,
        message: str,
        exit_code: int = 1,
        *,
        reason: FrontendBootstrapReason = FrontendBootstrapReason.START_FAILED,
    ) -> None:
        """Initializes one typed frontend bootstrap failure.

        Args:
            message (str): Safe user-facing failure text.
            exit_code (int): Process status returned by the selected frontend.

        Returns:
            None
        """
        super().__init__(message)
        self.exit_code = exit_code
        self.reason = reason


class FrontendInteractions(Protocol):
    """Frontend-owned prompts and status output requested by the base host."""

    def confirm_daemon_start(self) -> Optional[bool]:
        """Returns the frontend-owned daemon-start decision.

        Args:
            None

        Returns:
            Optional[bool]: Yes/no, or None when the user cancelled.
        """
        ...

    def request_session_auth_secret(self) -> Optional[str]:
        """Returns startup authentication input.

        Args:
            None

        Returns:
            Optional[str]: Secret text, or None when the user cancelled.
        """
        ...

    def show_status(self, message: str) -> None:
        """Displays one non-secret bootstrap status message.

        Args:
            message (str): Safe status text from the base host.

        Returns:
            None
        """
        ...


class OneUseSecretProvider:
    """Owns one in-memory startup secret and irreversibly consumes it once."""

    def __init__(self, secret: Optional[str]) -> None:
        """Initializes one consumable in-memory secret reference.

        Args:
            secret (Optional[str]): Startup secret or no secret.

        Returns:
            None
        """
        self._secret = secret
        self._lock = threading.Lock()

    def take(self) -> Optional[str]:
        """Returns and clears the startup secret exactly once.

        Args:
            None

        Returns:
            Optional[str]: Previously held secret, if still available.
        """
        with self._lock:
            secret = self._secret
            self._secret = None
            return secret


class FrontendProfileSecurity(str, Enum):
    """Frontend-neutral local profile storage choices."""

    ENCRYPTED = 'encrypted'
    PLAINTEXT = 'plaintext'


@dataclass(frozen=True)
class FrontendProfileCreateRequest:
    """Non-secret profile-creation inputs accepted by the local base host."""

    profile: str
    remote: bool = False
    port: int | None = None
    security: FrontendProfileSecurity = FrontendProfileSecurity.ENCRYPTED


@dataclass(frozen=True)
class FrontendProfileOperationResult:
    """Stable frontend-facing result for a local profile operation."""

    success: bool
    code: str
    profile: str


@dataclass(frozen=True)
class FrontendBootstrapResult:
    """Non-visual host state established after frontend-controlled bootstrap."""

    profile: str
    remote: bool
    port: int
    daemon_started_by_launcher: bool
    session_auth: OneUseSecretProvider
    config: FrontendSettings
    encrypted: bool

    def get_daemon_port(self) -> int:
        """Returns the endpoint resolved by base bootstrap."""
        return self.port

    def uses_encrypted_storage(self) -> bool:
        """Returns only the non-secret credential prompt mode."""
        return self.encrypted


class FrontendSettings(Protocol):
    """Bounded local client/UI values service; base owns validation and persistence."""

    def get_int(self, key: str) -> int: ...
    def get_float(self, key: str) -> float: ...
    def get_namespace_str(self, key: str) -> str: ...
    def get_namespace_int(self, key: str) -> int: ...
    def get_namespace_bool(self, key: str) -> bool: ...
    def get_namespace_float(self, key: str) -> float: ...

    def set_client_value(self, key: str, value: str | int | float | bool) -> None:
        """Sets a validated selected-profile client override; never daemon policy."""
        ...

    def set_ui_value(self, key: str, value: str | int | float | bool) -> None:
        """Sets a validated selected-profile official frontend override."""
        ...


@dataclass(frozen=True)
class FrontendProfileState:
    """Read-only pre-bootstrap profile state for first-run frontend routing."""

    profile: str
    exists: bool
    remote: bool
    daemon_running: bool


class FrontendHost(Protocol):
    """Base-distribution service boundary exposed to installed frontends."""

    contract_version: int

    def profile_state(self) -> FrontendProfileState:
        """Returns non-secret first-run state without starting work.

        Args:
            None

        Returns:
            FrontendProfileState: Current selected-profile metadata.
        """
        ...

    def list_profiles(self) -> tuple[FrontendProfileState, ...]:
        """Enumerates local profile metadata without starting it.

        Args:
            None

        Returns:
            tuple[FrontendProfileState, ...]: Available profile states.
        """
        ...

    def select_profile(self, profile: str) -> FrontendProfileState:
        """Selects one existing or first-run profile before bootstrap.

        Args:
            profile (str): Profile name routed through base validation.

        Returns:
            FrontendProfileState: Newly selected profile state.
        """
        ...

    def create_profile(
        self,
        request: FrontendProfileCreateRequest,
        secret: OneUseSecretProvider | None = None,
    ) -> FrontendProfileOperationResult:
        """Creates a profile through base services without retaining its secret.

        Args:
            request (FrontendProfileCreateRequest): Non-secret creation options.
            secret (OneUseSecretProvider | None): Consumable creation secret.

        Returns:
            FrontendProfileOperationResult: Stable creation outcome.
        """
        ...

    def bootstrap(self, interactions: FrontendInteractions) -> FrontendBootstrapResult:
        """Performs profile checks and optional daemon startup on demand.

        Args:
            interactions (FrontendInteractions): Frontend-owned interaction adapter.

        Returns:
            FrontendBootstrapResult: Established local or remote endpoint state.
        """
        ...


@dataclass(frozen=True)
class FrontendLaunchContext:
    """Carries frontend-neutral bootstrap state into one selected UI.

    Args:
        profile (str): Active profile name.
        host (FrontendHost): Deferred base-distribution bootstrap service.
        start_daemon (bool | None): Invocation-specific daemon autostart override.
        contract_version (int): Public frontend launch-contract generation.

    Returns:
        None
    """

    profile: str
    host: FrontendHost
    start_daemon: bool | None = None
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
