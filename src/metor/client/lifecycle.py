"""Frontend-neutral orchestration for changing active profile runtimes."""

from dataclasses import dataclass
from typing import Callable, Optional

from metor.client.session import MetorClient
from metor.core.api import RuntimeSnapshotEvent


@dataclass(frozen=True)
class ProfileSwitchResult:
    """Successful profile transition and the new authoritative state."""

    previous_snapshot: RuntimeSnapshotEvent
    current_snapshot: RuntimeSnapshotEvent


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
    ) -> Optional[ProfileSwitchResult]:
        """Performs the canonical reliability-preserving profile transition.

        The caller can inspect the current snapshot before invoking this method
        when it needs a confirmation prompt. Any frontend-owned active capture
        is finalized by the supplied callback before Core starts its exit phase.

        Args:
            target_profile (str): Profile to start/select through the factory.
            finalize_active_capture (Optional[Callable[[], None]]): Frontend
                capture-finalization hook.

        Returns:
            Optional[ProfileSwitchResult]: Both boundary snapshots, or None if
                preparation/bootstrap could not be confirmed.
        """
        previous = self._client.runtime_snapshot()
        if previous is None:
            return None
        if finalize_active_capture is not None:
            finalize_active_capture()
        if not self._client.prepare_profile_exit():
            return None

        self._client.disconnect()
        next_client = self._client_factory(target_profile)
        self._client = next_client
        if next_client.bootstrap() is None:
            return None
        current = next_client.runtime_snapshot()
        if current is None:
            return None
        return ProfileSwitchResult(
            previous_snapshot=previous,
            current_snapshot=current,
        )
