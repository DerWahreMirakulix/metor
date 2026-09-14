"""Base-owned deferred bootstrap services for independently installed frontends."""

from typing import Optional
from collections.abc import Iterator
from contextlib import contextmanager
import threading

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
    FrontendProfileAction,
    FrontendProfileCatalog,
    FrontendProfileChange,
    valid_frontend_profile_name,
    OneUseSecretProvider,
)
from metor.data import (
    ChatDaemonAutostartPolicy,
    ProfileManager,
    ProfileSecurityMode,
    SettingKey,
    Settings,
    SettingValidationError,
)
from metor.utils import Constants, TypeCaster, ProcessManager

# Local Package Imports
from .runtime import PlaintextLockedDaemonError, start_managed_daemon_process
from .frontend_settings import LocalFrontendSettings


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
        self, profile: ProfileManager, start_daemon_override: Optional[bool]
    ) -> None:
        """Initializes one deferred host for a selected profile.

        Args:
            profile (ProfileManager): Initially selected profile service.
            start_daemon_override (Optional[bool]): Invocation startup override.

        Returns:
            None
        """
        self._profile = profile
        self._start_daemon_override = start_daemon_override
        self._attempt_lock = threading.Lock()
        self._started_processes: dict[str, int | None] = {}

    def profile_state(self) -> FrontendProfileState:
        """Returns read-only state for a frontend first-run route.

        Args:
            None

        Returns:
            FrontendProfileState: Selected profile metadata.
        """
        exists = self._profile.exists()
        return FrontendProfileState(
            profile=self._profile.profile_name,
            exists=exists,
            remote=self._profile.is_remote() if exists else False,
            daemon_running=self._profile.is_daemon_running() if exists else False,
        )

    def _ensure_unused(self) -> None:
        """Rejects concurrent routing while bootstrap owns the selection boundary.

        Args:
            None

        Returns:
            None
        """
        if self._attempt_lock.locked():
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
        states = []
        for profile_name in ProfileManager.get_all_profiles():
            candidate = ProfileManager(profile_name)
            states.append(
                FrontendProfileState(
                    profile=profile_name,
                    exists=candidate.exists(),
                    remote=candidate.is_remote(),
                    daemon_running=candidate.is_daemon_running(),
                )
            )
        return tuple(states)

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
            self._profile = ProfileManager(profile)
            return self.profile_state()
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
            names = [
                name
                for name in ProfileManager.get_all_profiles()
                if valid_frontend_profile_name(name) and (after is None or name > after)
            ]
            entries = []
            for name in names[:limit]:
                profile = ProfileManager(name)
                entries.append(
                    FrontendProfileState(
                        name,
                        profile.exists(),
                        profile.is_remote(),
                        profile.is_daemon_running(),
                    )
                )
            return FrontendProfileCatalog(
                tuple(entries),
                self._profile.profile_name,
                ProfileManager.load_default_profile(),
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
            if change.selected_profile != self._profile.profile_name:
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
                if result.success:
                    try:
                        Settings.set(
                            SettingKey.DEFAULT_PROFILE,
                            change.new_name,
                            expected_value=change.profile,
                        )
                    except SettingValidationError:
                        pass
                    except Exception:
                        return FrontendProfileOperationResult(
                            False, 'renamed_default_unconfirmed', change.new_name
                        )
            else:
                return FrontendProfileOperationResult(
                    False, 'unsupported', change.profile
                )
            return FrontendProfileOperationResult(
                result.success,
                result.operation_type.value,
                change.new_name
                if result.success
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

    def _bootstrap_attempt(
        self, interactions: FrontendInteractions
    ) -> FrontendBootstrapResult:
        """Resolves one attempt; credentials never survive a failed attempt."""
        profile = self._profile
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
            and not ProcessManager.is_pid_running(started_pid)
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
            if profile.uses_plaintext_storage() and profile.config.get_bool(
                SettingKey.REQUIRE_LOCAL_AUTH
            ):
                startup_secret = interactions.request_session_auth_secret()
                if startup_secret is None:
                    raise FrontendBootstrapError(
                        'Aborted.', 130, reason=FrontendBootstrapReason.CANCELLED
                    )
            interactions.show_status('Starting local daemon...')
            try:
                daemon_started = start_managed_daemon_process(
                    profile,
                    start_locked=profile.uses_encrypted_storage(),
                    session_auth_password=startup_secret,
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
                raise FrontendBootstrapError(
                    "Could not start the local daemon. Run 'metor daemon' to "
                    'inspect foreground startup errors.'
                )
            self._started_processes[profile.profile_name] = profile.get_daemon_pid()
        port = profile.get_daemon_port()
        if type(port) is not int or not 0 < port < 65536:
            startup_secret = None
            raise FrontendBootstrapError(
                'No active daemon endpoint is available.',
                reason=FrontendBootstrapReason.UNREACHABLE,
            )
        return FrontendBootstrapResult(
            profile=profile.profile_name,
            remote=profile.is_remote(),
            port=port,
            daemon_started_by_launcher=daemon_started,
            session_auth=OneUseSecretProvider(startup_secret),
            config=LocalFrontendSettings(profile.config),
            encrypted=profile.uses_encrypted_storage(),
        )


def create_local_frontend_host(
    profile: str | ProfileManager = 'default',
    start_daemon_override: Optional[bool] = None,
) -> FrontendHost:
    """Creates the public deferred host implemented by the base distribution.

    Args:
        profile (ProfileManager): Initially selected profile service.
        start_daemon_override (Optional[bool]): Invocation startup override.

    Returns:
        FrontendHost: Versioned frontend-neutral host boundary.
    """
    return LocalFrontendHost(
        ProfileManager(profile) if isinstance(profile, str) else profile,
        start_daemon_override,
    )
