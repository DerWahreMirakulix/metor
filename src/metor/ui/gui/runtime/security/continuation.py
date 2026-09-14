"""Current Core-issued continuation with bounded read-only restricted-state refresh."""

from dataclasses import dataclass
import time
from typing import TYPE_CHECKING

from metor.core.api import (
    ClientRestrictedEvent,
    GetRestrictedClientStateCommand,
    GuiPreferences,
    IpcEvent,
    RestrictedClientStateEvent,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route

if TYPE_CHECKING:
    from .controller import SecurityController


@dataclass(frozen=True)
class ContinuedScope:
    """Exact media identity granted by Core, containing no display alias or message text."""

    profile_instance: str
    epoch: str
    peer: str
    context_generation: int
    session_state: str = 'connected'


class ContinuedLive:
    """Retains only explicitly requested scope and never chooses a background peer."""

    def __init__(self, security: 'SecurityController') -> None:
        """Creates an inactive continued-media owner for one GUI lock coordinator.

        Args:
            security: Same-client lock and reauthorization owner.
        Returns:
            None
        """
        self.security = security
        self.requested: ContinuedScope | None = None
        self.scope: ContinuedScope | None = None
        self._pending = False
        self._next_refresh = 0.0
        self.revision = 0

    def prepare(
        self,
        snapshot: RuntimeSnapshotEvent | None,
        route: Route,
        preferences: GuiPreferences,
    ) -> None:
        """Captures only the deliberate eligible foreground before the privacy cover.

        Args:
            snapshot: Last authorized public runtime projection.
            route: Exact foreground route at the lock action.
            preferences: Protected effective GUI policy.
        Returns:
            None
        """
        self.requested = self.scope = None
        self._pending = False
        self._next_refresh = 0.0
        controller = self.security.controller
        if (
            not preferences.keep_live_locked
            or 'restricted_live_projection' not in controller.state.capabilities
            or snapshot is None
            or not snapshot.profile_instance_id
            or not snapshot.epoch
            or route.view != 'V09'
            or route.peer is None
        ):
            return
        context = next(
            (item for item in snapshot.live_contexts if item.onion == route.peer), None
        )
        if (
            context is not None
            and context.context_generation is not None
            and (context.session_state == 'connected' or context.recovery_eligible)
            and context.session_state not in {'disconnected', 'pending'}
        ):
            self.requested = ContinuedScope(
                snapshot.profile_instance_id,
                snapshot.epoch,
                route.peer,
                context.context_generation,
                context.session_state,
            )

    def confirmed(self, event: ClientRestrictedEvent) -> None:
        """Accepts an initial grant only when Core returned the exact requested generation.

        Args:
            event: Authoritative same-client restriction result.
        Returns:
            None
        """
        requested = self.requested
        if requested is not None and (
            event.continued_live_target == requested.peer
            and event.continued_live_context_generation == requested.context_generation
            and (event.epoch is None or event.epoch == requested.epoch)
        ):
            self.scope = requested
            self.revision += 1

    def revoke(self) -> None:
        """Stops the original media owners and requires actual release before another press.

        Args:
            None
        Returns:
            None
        """
        if self.scope is not None:
            self.scope = None
            self.security.controller.voice.depart()
            self.security.controller.playback.stop()
            self.revision += 1

    def install(self, operation: str, event: IpcEvent | None) -> bool:
        """Revalidates current authority without exposing full profile state while covered.

        Args:
            operation: Same-generation restricted-state query identity.
            event: Core projection or an unknown result.
        Returns:
            bool: Whether this continuation owner consumed the update.
        """
        if operation != 'security:state':
            return False
        self._pending = False
        controller = self.security.controller
        if (
            not controller.state.covered
            or self.security.restoring
            or self.security.restriction is None
        ):
            return True
        if not isinstance(event, RestrictedClientStateEvent) or not event.restricted:
            self.revoke()
            return True
        requested = self.requested
        if requested is not None and (
            event.continued_live_target == requested.peer
            and event.continued_live_context_generation == requested.context_generation
            and (event.epoch is None or event.epoch == requested.epoch)
        ):
            scope = ContinuedScope(
                requested.profile_instance,
                requested.epoch,
                requested.peer,
                requested.context_generation,
                event.session_state,
            )
            if self.scope != scope:
                self.scope = scope
                self.revision += 1
        else:
            self.revoke()
        controller.calls.restricted(event)
        return True

    def poll(self) -> None:
        """Refreshes only this client's permitted state without disturbing native auth focus.

        Args:
            None
        Returns:
            None
        """
        controller = self.security.controller
        now = time.monotonic()
        client = controller.client
        if (
            client is None
            or not controller.state.covered
            or self.security.restriction is None
            or self.security.restoring
            or self._pending
            or now < self._next_refresh
            or 'restricted_live_projection' not in controller.state.capabilities
        ):
            return
        if controller.submit(
            'security:state',
            lambda: client.request(
                GetRestrictedClientStateCommand(), RestrictedClientStateEvent
            ),
            background=True,
        ):
            self._pending = True
            self._next_refresh = now + GuiLimits.RESTRICTED_REFRESH_SECONDS
