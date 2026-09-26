"""Protected preference commands and authoritative GUI-state reconciliation."""

from dataclasses import replace
from typing import TYPE_CHECKING

from metor.core.api import (
    GetGuiPreferencesCommand,
    GuiPreferences,
    GuiPreferencesEvent,
    GuiPreferencesRejectedEvent,
    GuiPreferenceFailure,
    SetGuiPreferencesCommand,
)

from metor.ui.gui.state import Route

if TYPE_CHECKING:
    from .controller import GuiController


class PreferenceBridge:
    """Keeps presentation options in Core's protected profile namespace."""

    def __init__(self, controller: 'GuiController') -> None:
        """Binds public command submission and generation-qualified state.

        Args:
            controller: Current GUI runtime controller.
        Returns:
            None
        """
        self.controller = controller
        self.refresh_needed = False
        self.last_error = ''
        self.save_serial = 0
        self.save_state = ''

    def save(
        self, preferences: GuiPreferences, expected_revision: int | None = None
    ) -> bool:
        """Requests a revision-qualified update without optimistic local mutation.

        Args:
            preferences: Strict public preference document.
            expected_revision: Revision displayed when an editor was opened, if captured.
        Returns:
            bool: Whether a request was admitted.
        """
        current = self.controller.state.preferences
        if current is None:
            self.controller.state.status = 'Protected settings are unavailable'
            return False
        admitted = self.controller.command(
            'A-settings',
            SetGuiPreferencesCommand(
                current.preferences_revision
                if expected_revision is None
                else expected_revision,
                preferences,
            ),
            GuiPreferencesEvent,
        )
        if admitted:
            self.last_error = ''
            self.save_serial += 1
            self.save_state = 'pending'
        return admitted

    def pin(self, peer: str) -> bool:
        """Toggles a canonical peer identity without saving its mutable alias.

        Args:
            peer: Canonical published peer identity.
        Returns:
            bool: Whether the protected change was admitted.
        """
        current = self.controller.state.preferences
        if current is None:
            return False
        pins = list(current.preferences.pins)
        if peer in pins:
            pins.remove(peer)
        else:
            pins.append(peer)
        try:
            preferences = replace(current.preferences, pins=pins)
        except ValueError:
            self.controller.state.status = 'Pin limit reached'
            return False
        return self.save(preferences)

    def poll(self) -> None:
        """Refreshes invalidated metadata when the serialized worker is available.

        Args:
            None
        Returns:
            None
        """
        controller = self.controller
        client = controller.client
        if self.refresh_needed and client is not None and not controller.state.covered:
            if controller.submit(
                'preferences',
                lambda: client.request(GetGuiPreferencesCommand(), GuiPreferencesEvent),
                background=True,
            ):
                self.refresh_needed = False

    def rejected(self, event: GuiPreferencesRejectedEvent) -> None:
        """Explains typed rejection and refreshes stale protected values.

        Args:
            event: Authoritative non-mutating rejection.
        Returns:
            None
        """
        self.last_error = {
            GuiPreferenceFailure.FULL_AUTH_REQUIRED: 'Unlock with the profile password to change security settings.',
            GuiPreferenceFailure.CONFLICT: 'Settings changed elsewhere. Review the current values.',
            GuiPreferenceFailure.PIN_UNAVAILABLE: 'Set a PIN before selecting PIN unlock.',
            GuiPreferenceFailure.PROTECTED_STORAGE_UNAVAILABLE: 'Protected settings are unavailable for this profile.',
        }.get(event.reason, 'Could not save these settings.')
        self.controller.state.status = self.last_error
        if self.save_state == 'pending':
            self.save_state = 'rejected'
        if event.reason is GuiPreferenceFailure.CONFLICT:
            self.refresh_needed = True

    def uncertain(self) -> None:
        """Schedules readback while retaining the unconfirmed protected-save barrier.

        Args:
            None
        Returns:
            None
        """
        self.last_error = (
            'Save is unconfirmed. Recheck current preferences before saving again.'
        )
        self.controller.state.status = self.last_error
        self.refresh_needed = True
        self.save_state = 'unknown'

    def install(
        self, event: GuiPreferencesEvent, *, confirmed_save: bool = False
    ) -> bool:
        """Rejects cross-profile and stale preference projections.

        Args:
            event: Authoritative Core result for this GUI generation.
            confirmed_save: Whether this is the correlated positive save response.
        Returns:
            bool: Whether this exact profile/revision result was installed.
        """
        state = self.controller.state
        snapshot = state.snapshot
        if (
            snapshot is not None
            and snapshot.profile_instance_id != event.profile_instance_id
        ):
            return False
        current = state.preferences
        if (
            current is not None
            and current.profile_instance_id != event.profile_instance_id
        ):
            return False
        if confirmed_save:
            self.save_state = 'saved'
        if (
            current is not None
            and current.preferences_revision > event.preferences_revision
        ):
            return False
        state.preferences = event
        if state.route.view == 'V04' and event.preferences.setup_complete:
            state.route = Route('V06')
        state.status = self.last_error
        return True
