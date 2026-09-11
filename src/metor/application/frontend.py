"""Base-owned deferred bootstrap services for independently installed frontends."""

from typing import Optional
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
    OneUseSecretProvider,
)
from metor.data import (
    ChatDaemonAutostartPolicy,
    ProfileManager,
    ProfileSecurityMode,
    SettingKey,
)
from metor.utils import TypeCaster, ProcessManager

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
        if not self._attempt_lock.acquire(blocking=False):
            raise FrontendBootstrapError(
                'Frontend bootstrap is already running.',
                reason=FrontendBootstrapReason.BUSY,
            )
        try:
            return self._create_profile(request, secret)
        finally:
            self._attempt_lock.release()

    def _create_profile(
        self, request: FrontendProfileCreateRequest, secret: OneUseSecretProvider | None
    ) -> FrontendProfileOperationResult:
        """Creates a profile while owning the selection/bootstrap transition."""
        password = secret.take() if secret is not None else None
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
        if result.success:
            self._profile = ProfileManager(request.profile)
        return FrontendProfileOperationResult(
            success=result.success,
            code=result.operation_type.value,
            profile=request.profile,
        )

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
