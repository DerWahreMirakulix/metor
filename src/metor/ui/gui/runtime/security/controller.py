"""Per-client restriction, one-use reauthorization and graphical PIN management."""

from dataclasses import replace
import time
from typing import TYPE_CHECKING

from metor.client import (
    build_pin_unlock_proof,
    build_session_auth_proof,
    create_pin_verifier,
)
from metor.core.api import (
    ClientReauthorizedEvent,
    ClientRestrictedEvent,
    ClientUnlockMethod,
    ConfigureQuickUnlockCommand,
    GetGuiPreferencesCommand,
    GuiPreferences,
    GuiPreferencesEvent,
    IpcEvent,
    LocalAuthRateLimitedEvent,
    QuickUnlockAction,
    QuickUnlockConfiguredEvent,
    QuickUnlockFailedEvent,
    ReauthorizeClientCommand,
    RestrictClientCommand,
    SetGuiPreferencesCommand,
    RuntimeSnapshotEvent,
    NotificationPrivacy,
)
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

from .continuation import ContinuedLive

if TYPE_CHECKING:
    from ..controller import GuiController


class SecurityController:
    """Mirrors Core authorization; an opaque local cover never grants permission."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates inactive authorization state for one GUI client.

        Args:
            controller: Owning GUI public-service controller.
        Returns:
            None
        """
        self.controller = controller
        self.continuation = ContinuedLive(self)
        self.restriction: ClientRestrictedEvent | None = None
        self.pending = False
        self.restoring = False
        self.retry_at = 0.0
        self.profile_label = ''
        self._profile_instance: str | None = None
        self._policy = GuiPreferences()
        self._return_route = Route('V06')
        self._last_input = time.monotonic()

    @property
    def notification_privacy(self) -> NotificationPrivacy:
        """Returns the requested frozen privacy policy for this covered cycle.

        Args:
            None
        Returns:
            NotificationPrivacy: Privacy used only after Core confirms restriction.
        """
        return self._policy.notifications_locked

    @property
    def return_route(self) -> Route:
        """Returns the explicitly covered route for normal unlock continuation.

        Args:
            None
        Returns:
            Route: Original permitted foreground route.
        """
        return self._return_route

    def activity(self) -> None:
        """Records deliberate user input independently of incoming messages.

        Args:
            None
        Returns:
            None
        """
        self._last_input = time.monotonic()

    def lock(self) -> bool:
        """Covers private views immediately and schedules same-client restriction.

        Args:
            None
        Returns:
            bool: Whether a new lock cycle started.
        """
        controller, state = self.controller, self.controller.state
        if state.covered or controller.client is None:
            return False
        controller.calls.clear()
        controller.resend.cancel()
        controller.contacts.book.stop()
        controller.notifications.begin_lock()
        controller.voice.depart()
        controller.playback.stop()
        preferences = (
            state.preferences.preferences if state.preferences else GuiPreferences()
        )
        self.continuation.prepare(state.snapshot, state.route, preferences)
        self._policy = replace(preferences, pins=[])
        self._profile_instance = (
            state.snapshot.profile_instance_id if state.snapshot else None
        )
        self._return_route = state.route
        self.profile_label = (
            state.snapshot.profile
            if state.snapshot and preferences.show_profile_locked
            else ''
        )
        state.covered = True
        state.route = Route('V05')
        state.status = 'Locking…'
        state.snapshot = None
        state.preferences = None
        controller.core_settings.cover()
        controller.history.cover()
        controller.state.secondary_scroll.clear()
        controller.messages = None
        self.restriction = None
        self.pending = True
        self.restoring = False
        return True

    def unlock(self, secret: str = '', *, password: bool = False) -> bool:
        """Submits one proof to the current Core-issued challenge.

        Args:
            secret: One-use PIN or profile password from a masked widget.
            password: Request a fresh password challenge without a false PIN attempt.
        Returns:
            bool: Whether the request was admitted.
        """
        client = self.controller.client
        restriction = self.restriction
        if client is None or restriction is None or time.monotonic() < self.retry_at:
            return False
        method = (
            ClientUnlockMethod.PROFILE_PASSWORD
            if password
            else restriction.unlock_method
        )
        challenge, salt = restriction.challenge, restriction.salt

        def request() -> IpcEvent | None:
            """Derives credentials off the native loop and sends no plaintext PIN.

            Args:
                None
            Returns:
                IpcEvent | None: Typed Core outcome, never local validation success.
            """
            proof = None
            if not password and method is not ClientUnlockMethod.NONE:
                if challenge is None or salt is None:
                    return None
                proof = (
                    build_pin_unlock_proof(secret, salt, challenge)
                    if method is ClientUnlockMethod.PIN
                    else build_session_auth_proof(secret, challenge, salt)
                )
            return client.request(ReauthorizeClientCommand(method, proof), IpcEvent)

        return self.controller.submit('security:unlock', request)

    def configure(
        self,
        method: ClientUnlockMethod,
        pin: str | None = None,
        *,
        remove_pin: bool = False,
    ) -> bool:
        """Changes protected lock policy only after required Core authorization.

        Args:
            method: Explicitly selected application unlock method.
            pin: One-use new PIN; root-password challenge remains Core-owned.
            remove_pin: Whether to remove the protected verifier before policy update.
        Returns:
            bool: Whether configuration was admitted.
        """
        state, client = self.controller.state, self.controller.client
        current = state.preferences
        if state.covered or client is None or current is None:
            return False
        preferences = replace(
            current.preferences, unlock_method=method, setup_complete=True
        )

        def configure() -> IpcEvent | None:
            """Runs sensitive verifier management before persisting method selection.

            Args:
                None
            Returns:
                IpcEvent | None: Final authoritative settings or explicit failure.
            """
            if pin is not None or remove_pin:
                salt, verifier = (
                    create_pin_verifier(pin) if pin is not None else (None, None)
                )
                result = client.request(
                    ConfigureQuickUnlockCommand(
                        QuickUnlockAction.REMOVE
                        if remove_pin
                        else QuickUnlockAction.SET,
                        salt,
                        verifier,
                    ),
                    QuickUnlockConfiguredEvent,
                )
                salt = verifier = None
                if result is None or result.enabled == remove_pin:
                    return None
            return client.request(
                SetGuiPreferencesCommand(current.preferences_revision, preferences),
                GuiPreferencesEvent,
            )

        return self.controller.submit('A-security-settings', configure)

    def install(self, operation: str, event: IpcEvent | None) -> bool:
        """Consumes only security-owned outcomes while the private cover remains up.

        Args:
            operation: Current generation's operation identity.
            event: Typed outcome or unknown result.
        Returns:
            bool: Whether this security controller consumed the update.
        """
        if self.continuation.install(operation, event):
            return True
        if not operation.startswith('security:'):
            return False
        state = self.controller.state
        if isinstance(event, RuntimeSnapshotEvent) and operation == 'security:snapshot':
            if event.profile_instance_id != self._profile_instance:
                self.controller.close()
                state.status = 'Profile changed. Open profile again.'
            else:
                state.snapshot = event
        elif isinstance(event, ClientRestrictedEvent):
            self.restriction = event
            self.continuation.confirmed(event)
            state.status = ''
        elif isinstance(event, QuickUnlockFailedEvent):
            method = (
                ClientUnlockMethod.PROFILE_PASSWORD
                if event.password_required
                else self.restriction.unlock_method
                if self.restriction
                else ClientUnlockMethod.PROFILE_PASSWORD
            )
            self.restriction = ClientRestrictedEvent(
                method, event.challenge, event.salt
            )
            state.status = (
                'Enter profile password'
                if event.password_required
                else 'Could not unlock. Try again.'
            )
        elif isinstance(event, LocalAuthRateLimitedEvent):
            self.retry_at = time.monotonic() + event.retry_after
            state.status = f'Try again in {event.retry_after} seconds'
        elif isinstance(event, ClientReauthorizedEvent):
            self.continuation.revoke()
            self.restriction = None
            self.restoring = True
            state.status = 'Opening Metor…'
        elif isinstance(event, GuiPreferencesEvent) and operation == 'security:restore':
            if (
                state.snapshot is None
                or event.profile_instance_id != self._profile_instance
            ):
                self.controller.close()
                return True
            state.preferences = event
            state.route = self._return_route
            state.covered = False
            state.status = ''
            self.restoring = False
            self.profile_label = ''
            self.activity()
        else:
            self.controller.close()
            state.status = 'Unlock could not be confirmed. Open profile to reconnect.'
        return True

    def poll(self) -> None:
        """Admits pending restriction/refresh and measures real input inactivity.

        Args:
            None
        Returns:
            None
        """
        controller, state = self.controller, self.controller.state
        client = controller.client
        if client is None:
            return
        if not state.covered:
            timeout = (
                state.preferences.preferences.idle_seconds
                if state.preferences
                else self._policy.idle_seconds
            )
            if timeout and time.monotonic() - self._last_input >= timeout:
                self.lock()
        if self.pending:
            if controller.voice.running or controller.playback.running:
                return
            requested = self.continuation.requested
            command = RestrictClientCommand(
                unlock_method=self._policy.unlock_method,
                continued_live_target=requested.peer if requested else None,
                continued_live_context_generation=requested.context_generation
                if requested
                else None,
                live_while_locked=requested is not None,
                accept_while_locked=self._policy.accept_live_locked,
                notification_privacy=self._policy.notifications_locked,
            )
            if controller.submit(
                'security:restrict',
                lambda: client.request(command, ClientRestrictedEvent),
            ):
                self.pending = False
        elif self.restoring:
            generation = state.generation

            def restore() -> IpcEvent | None:
                """Obtains fresh authoritative state before removing the cover.

                Args:
                    None
                Returns:
                    IpcEvent | None: Validated profile metadata after the snapshot.
                """
                snapshot = client.runtime_snapshot()
                preferences = client.request(
                    GetGuiPreferencesCommand(), GuiPreferencesEvent
                )
                if (
                    snapshot is None
                    or preferences is None
                    or snapshot.profile_instance_id != preferences.profile_instance_id
                ):
                    return None
                controller.mailbox.put(
                    Update(generation, 'security:snapshot', snapshot)
                )
                return preferences

            if controller.submit('security:restore', restore):
                self.restoring = False
        self.continuation.poll()
