"""Base-owned deferred bootstrap services for independently installed frontends."""

from typing import Optional
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
import threading
import os
import subprocess

import psutil

from metor.client import (
    FRONTEND_LAUNCH_CONTRACT_VERSION,
    FrontendBootstrapError,
    FrontendBootstrapReason,
    FrontendBootstrapResult,
    FrontendHost,
    FrontendInteractions,
    FrontendProfileCreateRequest,
    FrontendProfileOperationResult,
    FrontendProfileSecurity,
    FrontendProfileState,
    FrontendSelection,
    FrontendSelectionKind,
    FrontendProfileAction,
    FrontendProfileCatalog,
    FrontendProfileChange,
    valid_frontend_profile_name,
    OneUseSecretProvider,
    FrontendProfileAddressRequest,
)
from metor.data import (
    ChatDaemonAutostartPolicy,
    ProfileManager,
    ProfileSecurityMode,
    SettingKey,
)
from metor.utils import Constants, FileLock, TypeCaster, ProcessManager
from metor.data.profile.catalog import (
    get_unavailable_profile_names,
    resolve_initial_profile,
    valid_default_profile,
)

# Local Package Imports
from ..runtime import (
    DaemonStartDiagnostics,
    PlaintextLockedDaemonError,
    start_managed_daemon_process,
)
from .settings import LocalFrontendSettings
from .identity import profile_address


def _resolve_autostart_policy(
    profile: ProfileManager,
    override: Optional[bool],
) -> ChatDaemonAutostartPolicy:
    """Resolves invocation, profile, and default daemon-start policy.

    Args:
        profile (ProfileManager): Selected local profile service.
        override (Optional[bool]): Invocation-specific startup decision.

    Returns:
        ChatDaemonAutostartPolicy: Effective startup policy.
    """
    if override is True:
        return ChatDaemonAutostartPolicy.ALWAYS
    if override is False:
        return ChatDaemonAutostartPolicy.NEVER
    return TypeCaster.to_enum(
        ChatDaemonAutostartPolicy,
        profile.config.get_str(SettingKey.CHAT_DAEMON_AUTOSTART),
        ChatDaemonAutostartPolicy.ASK,
    )


def _offline_hint() -> str:
    """Returns frontend-neutral local daemon startup guidance.

    Args:
        None

    Returns:
        str: Safe user-facing offline guidance.
    """
    return (
        "Daemon is not running! Use 'metor daemon' to start it or rerun with "
        "'metor chat --start-daemon'."
    )


class LocalFrontendHost:
    """Deferred profile and daemon bootstrap exposed to one selected frontend."""

    contract_version = FRONTEND_LAUNCH_CONTRACT_VERSION

    def __init__(
        self,
        profile: ProfileManager | None,
        start_daemon_override: Optional[bool],
        requested_name: str | None = None,
    ) -> None:
        """Initializes one deferred host for a selected profile.

        Args:
            profile (ProfileManager): Initially selected profile service.
            start_daemon_override (Optional[bool]): Invocation startup override.
            requested_name: Original explicit request, if any.

        Returns:
            None
        """
        self._profile = profile
        self._unavailable_name: str | None = None
        self._requested_name = requested_name
        self._catalog_unavailable = False
        self._start_daemon_override = start_daemon_override
        self._attempt_lock = threading.Lock()
        self._closed = threading.Event()
        self._started_processes: dict[str, int | None] = {}
        self._owned_processes: dict[str, subprocess.Popen[bytes]] = {}

    def _close_owned_profile(self, profile: str) -> None:
        """Stop only the child process spawned by this invocation for a profile.

        Args:
            profile: Exact owned profile identity.
        Returns:
            None
        """
        process = self._owned_processes.get(profile)
        if process is None:
            return
        if process.poll() is None:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    if process.poll() is None:
                        raise
                try:
                    process.wait(timeout=Constants.OWNED_DAEMON_SHUTDOWN_TIMEOUT_SEC)
                except subprocess.TimeoutExpired:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=Constants.TOR_KILL_TIMEOUT_SEC)
        self._owned_processes.pop(profile, None)
        self._started_processes.pop(profile, None)

    def close(self) -> None:
        """Release every exact daemon child created by this chat invocation.

        Args:
            None
        Returns:
            None
        """
        self._closed.set()
        with self._attempt_lock:
            failures: list[Exception] = []
            for profile in tuple(self._owned_processes):
                try:
                    self._close_owned_profile(profile)
                except (OSError, subprocess.SubprocessError) as exc:
                    failures.append(exc)
            if failures:
                raise OSError('Owned daemon cleanup could not be confirmed.')

    def initial_selection(self) -> FrontendSelection:
        """Classify the selected profile against current safe catalog facts.

        Args:
            None
        Returns:
            FrontendSelection: Typed initial state without catalog contents.
        """
        requested = self._requested_name
        if self._catalog_unavailable:
            return FrontendSelection(
                FrontendSelectionKind.UNAVAILABLE, requested, None, None
            )
        try:
            boundary = (
                FileLock(Constants.DATA / '.profile-catalog')
                if Constants.DATA.exists()
                else nullcontext()
            )
            with boundary:
                selected = self.profile_state()
                names = ProfileManager.get_all_profiles()
                unavailable = get_unavailable_profile_names()
                default = valid_default_profile(names)
        except (OSError, ValueError):
            return FrontendSelection(
                FrontendSelectionKind.UNAVAILABLE, requested, None, None
            )
        if selected is not None:
            if selected.issue or selected.profile in unavailable:
                kind = FrontendSelectionKind.UNAVAILABLE
            elif selected.exists and selected.profile in names:
                kind = FrontendSelectionKind.RESOLVED
            else:
                kind = FrontendSelectionKind.REQUESTED_MISSING
            return FrontendSelection(
                kind,
                requested,
                selected.profile if kind is FrontendSelectionKind.RESOLVED else None,
                default,
            )
        kind = (
            FrontendSelectionKind.UNAVAILABLE
            if unavailable
            else FrontendSelectionKind.CHOICE_REQUIRED
            if names
            else FrontendSelectionKind.EMPTY
        )
        return FrontendSelection(kind, requested, None, default)

    def profile_state(self) -> FrontendProfileState | None:
        """Returns read-only state for a frontend first-run route.

        Args:
            None

        Returns:
            FrontendProfileState: Selected profile metadata.
        """
        if self._profile is None:
            if self._unavailable_name is None:
                return None
            return FrontendProfileState(
                self._unavailable_name, True, False, False, 'invalid_storage'
            )
        return self._catalog_state(self._profile.profile_name)

    @staticmethod
    def _catalog_state(name: str) -> FrontendProfileState:
        """Read one safe profile fact without treating damage as absence.

        Args:
            name: Syntactically valid profile name.
        Returns:
            FrontendProfileState: Usable, missing, or safely unavailable entry.
        """
        try:
            candidate = ProfileManager(name)
            exists = candidate.exists()
            return FrontendProfileState(
                name,
                exists,
                candidate.is_remote() if exists else False,
                candidate.is_daemon_running() if exists else False,
            )
        except (ValueError, OSError):
            return FrontendProfileState(name, True, False, False, 'invalid_storage')

    def _ensure_unused(self) -> None:
        """Rejects concurrent routing while bootstrap owns the selection boundary.

        Args:
            None

        Returns:
            None
        """
        if self._closed.is_set() or self._attempt_lock.locked():
            raise FrontendBootstrapError(
                'Frontend bootstrap is already running.',
                reason=FrontendBootstrapReason.BUSY,
            )

    def list_profiles(self) -> tuple[FrontendProfileState, ...]:
        """Returns public state for every local profile.

        Args:
            None

        Returns:
            tuple[FrontendProfileState, ...]: Available profile states.
        """
        self._ensure_unused()
        names = set(ProfileManager.get_all_profiles())
        names.update(get_unavailable_profile_names())
        return tuple(self._catalog_state(name) for name in sorted(names))

    def select_profile(self, profile: str) -> FrontendProfileState:
        """Selects a profile through the public base profile manager.

        Args:
            profile (str): Profile name to select.

        Returns:
            FrontendProfileState: State for the new selection.
        """
        if not valid_frontend_profile_name(profile):
            raise FrontendBootstrapError(
                'Invalid profile name.',
                reason=FrontendBootstrapReason.INVALID_CONFIGURATION,
            )
        if not self._attempt_lock.acquire(blocking=False):
            raise FrontendBootstrapError(
                'Frontend bootstrap is already running.',
                reason=FrontendBootstrapReason.BUSY,
            )
        try:
            self._require_open()
            if self._profile is not None and self._profile.profile_name != profile:
                self._close_owned_profile(self._profile.profile_name)
            selected = self._catalog_state(profile)
            if not selected.exists or selected.issue:
                raise FrontendBootstrapError(
                    'Selected profile is missing or unavailable.',
                    reason=FrontendBootstrapReason.MISSING_PROFILE,
                )
            self._profile = ProfileManager(profile)
            self._unavailable_name = None
            return selected
        except ValueError:
            raise FrontendBootstrapError(
                'Invalid profile configuration.',
                reason=FrontendBootstrapReason.INVALID_CONFIGURATION,
            ) from None
        finally:
            self._attempt_lock.release()

    def create_profile(
        self,
        request: FrontendProfileCreateRequest,
        secret: OneUseSecretProvider | None = None,
    ) -> FrontendProfileOperationResult:
        """Creates a profile through existing lifecycle services.

        Args:
            request (FrontendProfileCreateRequest): Non-secret creation options.
            secret (OneUseSecretProvider | None): Consumable master password.

        Returns:
            FrontendProfileOperationResult: Public creation result.
        """
        try:
            with self._catalog_boundary():
                return self._create_profile(request, secret)
        finally:
            if secret is not None:
                secret.take()

    def _create_profile(
        self,
        request: FrontendProfileCreateRequest,
        secret: OneUseSecretProvider | None,
        *,
        select: bool = True,
    ) -> FrontendProfileOperationResult:
        """Creates a profile while owning the selection/bootstrap transition.

        Args:
            request: Explicit public creation inputs.
            secret: One-use creation password.
            select: Whether creation also selects the new first-run profile.
        Returns:
            FrontendProfileOperationResult: Actual creation outcome.
        """
        password = secret.take() if secret is not None else None
        if not valid_frontend_profile_name(request.profile):
            return FrontendProfileOperationResult(
                False, 'invalid_name', request.profile
            )
        security = (
            ProfileSecurityMode.ENCRYPTED
            if request.security is FrontendProfileSecurity.ENCRYPTED
            else ProfileSecurityMode.PLAINTEXT
        )
        result = ProfileManager.add_profile_folder(
            request.profile,
            is_remote=request.remote,
            port=request.port,
            security_mode=security,
            master_password=password,
        )
        if result.success and select:
            self._profile = ProfileManager(request.profile)
        return FrontendProfileOperationResult(
            success=result.success,
            code=result.operation_type.value,
            profile=request.profile,
        )

    def profile_catalog(
        self,
        after: str | None = None,
        limit: int = Constants.FRONTEND_PROFILE_PAGE_ITEMS,
    ) -> FrontendProfileCatalog:
        """Returns a finite local profile page through the existing catalog owner.

        Args:
            after: Exclusive profile-name bookmark; deletion does not retarget it.
            limit: Maximum entries, bounded independently of local catalog size.
        Returns:
            FrontendProfileCatalog: Current selected/default metadata and next bookmark.
        """
        if (
            type(limit) is not int
            or not 1 <= limit <= Constants.FRONTEND_PROFILE_PAGE_ITEMS
        ):
            raise ValueError('Invalid profile page size')
        if after is not None and not valid_frontend_profile_name(after):
            raise ValueError('Invalid profile bookmark')
        with self._catalog_boundary():
            boundary = (
                FileLock(Constants.DATA / '.profile-catalog')
                if Constants.DATA.exists()
                else nullcontext()
            )
            with boundary:
                names = sorted(
                    name
                    for name in set(ProfileManager.get_all_profiles())
                    | set(get_unavailable_profile_names())
                    if valid_frontend_profile_name(name)
                    and (after is None or name > after)
                )
                entries = tuple(self._catalog_state(name) for name in names[:limit])
                return FrontendProfileCatalog(
                    entries,
                    self._profile.profile_name
                    if self._profile is not None
                    else self._unavailable_name,
                    valid_default_profile(),
                    names[limit - 1] if len(names) > limit else None,
                )

    def manage_profile(
        self, change: FrontendProfileChange
    ) -> FrontendProfileOperationResult:
        """Routes exact local catalog changes without stopping a running runtime.

        Args:
            change: Confirmed target and original host selection.
        Returns:
            FrontendProfileOperationResult: Existing base eligibility result or stale context refusal.
        """
        change.__post_init__()
        with self._catalog_boundary():
            if (
                self._profile is None
                or change.selected_profile != self._profile.profile_name
            ):
                return FrontendProfileOperationResult(
                    False, 'selection_changed', change.profile
                )
            if change.action is FrontendProfileAction.SET_DEFAULT:
                result = ProfileManager.set_default_profile(change.profile)
            elif change.action is FrontendProfileAction.REMOVE:
                result = ProfileManager.remove_profile_folder(
                    change.profile, self._profile.profile_name
                )
            elif change.action is FrontendProfileAction.RENAME and change.new_name:
                renamed = ProfileManager(change.new_name)
                result = ProfileManager.rename_profile_folder(
                    change.profile, change.new_name
                )
                if result.success and self._profile.profile_name == change.profile:
                    self._profile = renamed
            else:
                return FrontendProfileOperationResult(
                    False, 'unsupported', change.profile
                )
            return FrontendProfileOperationResult(
                result.success,
                result.operation_type.value,
                change.new_name
                if (
                    result.success
                    or result.operation_type.value == 'renamed_default_unconfirmed'
                )
                and change.action is FrontendProfileAction.RENAME
                and change.new_name
                else change.profile,
            )

    def create_profile_entry(
        self,
        request: FrontendProfileCreateRequest,
        secret: OneUseSecretProvider | None = None,
    ) -> FrontendProfileOperationResult:
        """Creates through the existing lifecycle while retaining current host selection.

        Args:
            request: Explicit creation inputs.
            secret: One-use creation credential.
        Returns:
            FrontendProfileOperationResult: Existing base creation result.
        """
        try:
            with self._catalog_boundary():
                return self._create_profile(request, secret, select=False)
        finally:
            if secret is not None:
                secret.take()

    def profile_address(
        self, request: FrontendProfileAddressRequest, secret: OneUseSecretProvider
    ) -> FrontendProfileOperationResult:
        """Generates or checks a stopped local profile through its existing authenticated Core owner.

        Args:
            request: Original selection, exact target and explicit generate/read intent.
            secret: One-use full target password; consumed on every exit path.
        Returns:
            FrontendProfileOperationResult: Actual Core outcome and permitted public address.
        """
        try:
            request.__post_init__()
            with self._catalog_boundary():
                if (
                    self._profile is None
                    or request.selected_profile != self._profile.profile_name
                ):
                    return FrontendProfileOperationResult(
                        False, 'selection_changed', request.profile
                    )
                return profile_address(request, secret.take())
        finally:
            secret.take()

    @contextmanager
    def _catalog_boundary(self) -> Iterator[None]:
        """Rejects concurrent catalog changes while bootstrap owns the host selection.

        Args:
            None
        Returns:
            Iterator[None]: Held profile/selection boundary for one local operation.
        """
        if not self._attempt_lock.acquire(blocking=False):
            raise FrontendBootstrapError(
                'Frontend bootstrap is already running.',
                reason=FrontendBootstrapReason.BUSY,
            )
        try:
            self._require_open()
            yield
        finally:
            self._attempt_lock.release()

    def bootstrap(self, interactions: FrontendInteractions) -> FrontendBootstrapResult:
        """Performs one retryable bootstrap attempt after the frontend has started.

        Args:
            interactions (FrontendInteractions): Frontend-owned interaction adapter.

        Returns:
            FrontendBootstrapResult: Resolved endpoint and one-use secret transfer.
        """
        if not self._attempt_lock.acquire(blocking=False):
            raise FrontendBootstrapError(
                'Frontend bootstrap is already running.',
                reason=FrontendBootstrapReason.BUSY,
            )
        try:
            self._require_open()
            return self._bootstrap_attempt(interactions)
        except FrontendBootstrapError:
            raise
        except ValueError:
            raise FrontendBootstrapError(
                'The frontend profile configuration is invalid.',
                reason=FrontendBootstrapReason.INVALID_CONFIGURATION,
            ) from None
        except OSError:
            raise FrontendBootstrapError(
                'The frontend endpoint could not be resolved.',
                reason=FrontendBootstrapReason.UNREACHABLE,
            ) from None
        finally:
            self._attempt_lock.release()

    def _require_open(self) -> None:
        """Reject new activity after the invocation begins closing.

        Args:
            None
        Returns:
            None
        """
        if self._closed.is_set():
            raise FrontendBootstrapError(
                'Frontend host is closing.', reason=FrontendBootstrapReason.CANCELLED
            )

    def _bootstrap_attempt(
        self, interactions: FrontendInteractions
    ) -> FrontendBootstrapResult:
        """Resolves one attempt; credentials never survive a failed attempt.

        Args:
            interactions (FrontendInteractions): The interactions input.

        Returns:
            FrontendBootstrapResult: The resulting value.
        """
        self._require_open()
        profile = self._profile
        if profile is None:
            raise FrontendBootstrapError(
                'No profiles exist yet.',
                reason=FrontendBootstrapReason.MISSING_PROFILE,
            )
        if not profile.exists():
            raise FrontendBootstrapError(
                f"Profile '{profile.profile_name}' does not exist.",
                reason=FrontendBootstrapReason.MISSING_PROFILE,
            )

        startup_secret: Optional[str] = None
        daemon_started = False
        confirmed_start = profile.profile_name in self._started_processes
        started_pid = self._started_processes.get(profile.profile_name)
        if (
            confirmed_start
            and started_pid is not None
            and ProcessManager.is_pid_running(started_pid) is False
        ):
            self._started_processes.pop(profile.profile_name, None)
            confirmed_start = False
        if (
            not profile.is_remote()
            and not profile.is_daemon_running()
            and not confirmed_start
        ):
            policy = _resolve_autostart_policy(profile, self._start_daemon_override)
            if policy is ChatDaemonAutostartPolicy.NEVER:
                raise FrontendBootstrapError(_offline_hint())
            if policy is ChatDaemonAutostartPolicy.ASK:
                confirmation = interactions.confirm_daemon_start()
                if confirmation is None:
                    raise FrontendBootstrapError(
                        '', 130, reason=FrontendBootstrapReason.CANCELLED
                    )
                if not confirmation:
                    raise FrontendBootstrapError(_offline_hint())
            self._require_open()
            if profile.uses_plaintext_storage() and profile.config.get_bool(
                SettingKey.REQUIRE_LOCAL_AUTH
            ):
                startup_secret = interactions.request_session_auth_secret()
                if startup_secret is None:
                    raise FrontendBootstrapError(
                        'Aborted.', 130, reason=FrontendBootstrapReason.CANCELLED
                    )
            self._require_open()
            interactions.show_status('Starting local daemon...')
            self._require_open()
            diagnostics = DaemonStartDiagnostics()
            owner = psutil.Process(os.getpid())
            try:
                daemon_started = start_managed_daemon_process(
                    profile,
                    start_locked=profile.uses_encrypted_storage(),
                    session_auth_password=startup_secret,
                    diagnostics=diagnostics,
                    chat_owner=(owner.pid, owner.create_time()),
                )
            except PlaintextLockedDaemonError as exc:
                startup_secret = None
                raise FrontendBootstrapError(
                    'Plaintext profiles cannot be started in locked mode.'
                ) from exc
            except ValueError as exc:
                startup_secret = None
                raise FrontendBootstrapError(
                    'The local daemon configuration is invalid.',
                    reason=FrontendBootstrapReason.INVALID_CONFIGURATION,
                ) from exc
            except OSError:
                startup_secret = None
                raise FrontendBootstrapError(
                    'The local daemon could not be started.',
                    reason=FrontendBootstrapReason.START_FAILED,
                ) from None
            if not daemon_started:
                startup_secret = None
                status = (
                    f', status {diagnostics.return_code}'
                    if diagnostics.return_code is not None
                    else ''
                )
                raise FrontendBootstrapError(
                    f'Could not start the local daemon [{diagnostics.phase}{status}]. '
                    "Run 'metor daemon' to inspect foreground startup errors."
                )
            if diagnostics.process is not None:
                self._owned_processes[profile.profile_name] = diagnostics.process
            self._started_processes[profile.profile_name] = profile.get_daemon_pid()
            self._require_open()
        port = profile.get_daemon_port()
        if type(port) is not int or not 0 < port < 65536:
            startup_secret = None
            raise FrontendBootstrapError(
                'No active daemon endpoint is available.',
                reason=FrontendBootstrapReason.UNREACHABLE,
            )
        retries = profile.config.get_int(SettingKey.MAX_TOR_RETRIES)
        unlock_timeout = min(
            Constants.MAX_UNLOCK_INITIALIZATION_WAIT_SEC,
            max(
                profile.config.get_float(SettingKey.IPC_TIMEOUT),
                retries * Constants.UNIX_TOR_TIMEOUT
                + max(0, retries - 1) * Constants.TOR_BOOTSTRAP_RETRY_SEC
                + Constants.TOR_HOSTNAME_POLL_RETRIES * Constants.TOR_BOOTSTRAP_POLL_SEC
                + Constants.TOR_PROXY_READY_ATTEMPTS
                * (
                    Constants.TOR_PROXY_READY_TIMEOUT_SEC
                    + Constants.TOR_PROXY_READY_RETRY_SEC
                )
                + Constants.LISTENER_READY_TIMEOUT,
            ),
        )
        self._require_open()
        return FrontendBootstrapResult(
            profile=profile.profile_name,
            remote=profile.is_remote(),
            port=port,
            daemon_started_by_launcher=daemon_started,
            session_auth=OneUseSecretProvider(startup_secret),
            config=LocalFrontendSettings(profile.config),
            encrypted=profile.uses_encrypted_storage(),
            unlock_timeout=unlock_timeout,
        )


def create_local_frontend_host(
    profile: str | ProfileManager | None = None,
    start_daemon_override: Optional[bool] = None,
) -> FrontendHost:
    """Creates the public deferred host implemented by the base distribution.

    Args:
        profile (ProfileManager): Initially selected profile service.
        start_daemon_override (Optional[bool]): Invocation startup override.

    Returns:
        FrontendHost: Versioned frontend-neutral host boundary.
    """
    requested_name = (
        profile
        if isinstance(profile, str)
        else profile.profile_name
        if profile is not None
        else None
    )
    if profile is None:
        try:
            profile = resolve_initial_profile()
        except (OSError, ValueError):
            host = LocalFrontendHost(None, start_daemon_override)
            host._catalog_unavailable = True
            return host
    if isinstance(profile, str):
        try:
            selected = ProfileManager(profile)
        except (ValueError, OSError):
            host = LocalFrontendHost(None, start_daemon_override, requested_name)
            host._unavailable_name = profile
            return host
        return LocalFrontendHost(selected, start_daemon_override, requested_name)
    return LocalFrontendHost(profile, start_daemon_override, requested_name)
