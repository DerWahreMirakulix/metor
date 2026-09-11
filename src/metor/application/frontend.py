"""Base-owned deferred bootstrap services for independently installed frontends."""

from typing import Optional

from metor.client import (
    FRONTEND_LAUNCH_CONTRACT_VERSION,
    FrontendBootstrapError,
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
from metor.utils import TypeCaster

# Local Package Imports
from .runtime import PlaintextLockedDaemonError, start_managed_daemon_process


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
        self._used = False

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
        """Rejects profile routing after the one-shot bootstrap boundary.

        Args:
            None

        Returns:
            None
        """
        if self._used:
            raise FrontendBootstrapError('Frontend bootstrap was already consumed.')

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
        self._ensure_unused()
        self._profile = ProfileManager(profile)
        return self.profile_state()

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
        self._ensure_unused()
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
        """Performs bootstrap once, after the frontend has started.

        Args:
            interactions (FrontendInteractions): Frontend-owned interaction adapter.

        Returns:
            FrontendBootstrapResult: Established endpoint and secret transfer.
        """
        self._ensure_unused()
        self._used = True
        profile = self._profile
        if not profile.exists():
            raise FrontendBootstrapError(
                f"Profile '{profile.profile_name}' does not exist."
            )

        startup_secret: Optional[str] = None
        daemon_started = False
        if not profile.is_daemon_running():
            if profile.is_remote():
                raise FrontendBootstrapError('The remote daemon is offline.')
            policy = _resolve_autostart_policy(profile, self._start_daemon_override)
            if policy is ChatDaemonAutostartPolicy.NEVER:
                raise FrontendBootstrapError(_offline_hint())
            if policy is ChatDaemonAutostartPolicy.ASK:
                confirmation = interactions.confirm_daemon_start()
                if confirmation is None:
                    raise FrontendBootstrapError('', 130)
                if not confirmation:
                    raise FrontendBootstrapError(_offline_hint())
            if profile.uses_plaintext_storage() and profile.config.get_bool(
                SettingKey.REQUIRE_LOCAL_AUTH
            ):
                startup_secret = interactions.request_session_auth_secret()
                if startup_secret is None:
                    raise FrontendBootstrapError('Aborted.', 130)
            interactions.show_status('Starting local daemon...')
            try:
                daemon_started = start_managed_daemon_process(
                    profile,
                    start_locked=profile.uses_encrypted_storage(),
                    session_auth_password=startup_secret,
                )
            except PlaintextLockedDaemonError as exc:
                raise FrontendBootstrapError(
                    'Plaintext profiles cannot be started in locked mode.'
                ) from exc
            except ValueError as exc:
                raise FrontendBootstrapError(
                    'The local daemon configuration is invalid.'
                ) from exc
            if not daemon_started:
                raise FrontendBootstrapError(
                    "Could not start the local daemon. Run 'metor daemon' to "
                    'inspect foreground startup errors.'
                )
        return FrontendBootstrapResult(
            profile=profile.profile_name,
            remote=profile.is_remote(),
            port=profile.get_static_port(),
            daemon_started_by_launcher=daemon_started,
            session_auth=OneUseSecretProvider(startup_secret),
        )


def create_local_frontend_host(
    profile: ProfileManager,
    start_daemon_override: Optional[bool],
) -> FrontendHost:
    """Creates the public deferred host implemented by the base distribution.

    Args:
        profile (ProfileManager): Initially selected profile service.
        start_daemon_override (Optional[bool]): Invocation startup override.

    Returns:
        FrontendHost: Versioned frontend-neutral host boundary.
    """
    return LocalFrontendHost(profile, start_daemon_override)
