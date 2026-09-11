"""Frontend-neutral orchestration for changing active profile runtimes."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from metor.client.session import MetorClient
from metor.core.api import RuntimeSnapshotEvent


@dataclass(frozen=True)
class ProfileSwitchResult:
    """Successful profile transition and the new authoritative state."""

    previous_snapshot: RuntimeSnapshotEvent
    current_snapshot: RuntimeSnapshotEvent


class ProfileSwitchPhase(str, Enum):
    """Stable failure phases for frontend profile-switch recovery."""

    SOURCE_SNAPSHOT = 'source_snapshot'
    CAPTURE_FINALIZATION = 'capture_finalization'
    SOURCE_PREPARATION = 'source_preparation'
    SOURCE_RELEASE = 'source_release'
    TARGET_FACTORY = 'target_factory'
    TARGET_BOOTSTRAP = 'target_bootstrap'
    TARGET_SNAPSHOT = 'target_snapshot'


class ProfileSwitchError(RuntimeError):
    """Reports exactly where a profile transition stopped."""

    def __init__(
        self,
        phase: ProfileSwitchPhase,
        message: str,
        *,
        source_released: bool = False,
    ) -> None:
        """Initializes a phase-aware profile transition failure.

        Args:
            phase (ProfileSwitchPhase): Phase that did not complete.
            message (str): Safe user-facing explanation.
            source_released (bool): Whether the old client was confirmed detached.

        Returns:
            None
        """
        super().__init__(message)
        self.phase = phase
        self.source_released = source_released


class ProfileRuntimeCoordinator:
    """Coordinates safe profile exit and authenticated attachment to another runtime."""

    def __init__(
        self,
        client: MetorClient,
        client_factory: Callable[[str], MetorClient],
    ) -> None:
        """Initializes the coordinator around one currently attached client.

        Args:
            client (MetorClient): Current authenticated profile client.
            client_factory (Callable[[str], MetorClient]): Starts or locates the
                requested profile runtime and returns its client.

        Returns:
            None
        """
        self._client = client
        self._client_factory = client_factory

    @property
    def client(self) -> MetorClient:
        """Returns the client for the currently selected profile runtime."""
        return self._client

    def switch(
        self,
        target_profile: str,
        *,
        finalize_active_capture: Optional[Callable[[], None]] = None,
    ) -> ProfileSwitchResult:
        """Performs the canonical reliability-preserving profile transition.

        The caller can inspect the current snapshot before invoking this method
        when it needs a confirmation prompt. Any frontend-owned active capture
        is finalized by the supplied callback before Core starts its exit phase.

        Args:
            target_profile (str): Profile to start/select through the factory.
            finalize_active_capture (Optional[Callable[[], None]]): Frontend
                capture-finalization hook.

        Returns:
            ProfileSwitchResult: Both confirmed boundary snapshots.

        Raises:
            ProfileSwitchError: With the exact failed transition phase.
        """
        try:
            previous = self._client.runtime_snapshot()
        except Exception as exc:
            raise ProfileSwitchError(
                ProfileSwitchPhase.SOURCE_SNAPSHOT,
                'The current runtime snapshot raised an exception.',
            ) from exc
        if previous is None:
            raise ProfileSwitchError(
                ProfileSwitchPhase.SOURCE_SNAPSHOT,
                'The current runtime snapshot could not be confirmed.',
            )
        if finalize_active_capture is not None:
            try:
                finalize_active_capture()
            except Exception as exc:
                raise ProfileSwitchError(
                    ProfileSwitchPhase.CAPTURE_FINALIZATION,
                    'Active capture finalization failed.',
                ) from exc
        try:
            source_prepared = self._client.prepare_profile_exit()
        except Exception as exc:
            raise ProfileSwitchError(
                ProfileSwitchPhase.SOURCE_PREPARATION,
                'The current runtime profile-exit preparation raised an exception.',
            ) from exc
        if not source_prepared:
            raise ProfileSwitchError(
                ProfileSwitchPhase.SOURCE_PREPARATION,
                'The current runtime did not confirm profile-exit preparation.',
            )

        try:
            self._client.disconnect()
        except Exception as exc:
            raise ProfileSwitchError(
                ProfileSwitchPhase.SOURCE_RELEASE,
                'The current runtime client could not confirm release.',
            ) from exc
        try:
            next_client = self._client_factory(target_profile)
        except Exception as exc:
            raise ProfileSwitchError(
                ProfileSwitchPhase.TARGET_FACTORY,
                'The target runtime client could not be created.',
                source_released=True,
            ) from exc

        def dispose_candidate() -> None:
            """Disposes the partial candidate without masking transition failure.

            Args:
                None

            Returns:
                None
            """
            try:
                next_client.disconnect()
            except Exception:
                pass

        try:
            if next_client.bootstrap() is None:
                raise ProfileSwitchError(
                    ProfileSwitchPhase.TARGET_BOOTSTRAP,
                    'The target runtime did not complete bootstrap.',
                    source_released=True,
                )
        except ProfileSwitchError:
            dispose_candidate()
            raise
        except Exception as exc:
            dispose_candidate()
            raise ProfileSwitchError(
                ProfileSwitchPhase.TARGET_BOOTSTRAP,
                'The target runtime bootstrap raised an exception.',
                source_released=True,
            ) from exc
        try:
            current = next_client.runtime_snapshot()
        except Exception as exc:
            dispose_candidate()
            raise ProfileSwitchError(
                ProfileSwitchPhase.TARGET_SNAPSHOT,
                'The target runtime snapshot raised an exception.',
                source_released=True,
            ) from exc
        if current is None:
            dispose_candidate()
            raise ProfileSwitchError(
                ProfileSwitchPhase.TARGET_SNAPSHOT,
                'The target runtime snapshot could not be confirmed.',
                source_released=True,
            )
        self._client = next_client
        return ProfileSwitchResult(
            previous_snapshot=previous,
            current_snapshot=current,
        )
