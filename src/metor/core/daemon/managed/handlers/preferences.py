"""Managed-runtime authorization and policy for protected profile GUI metadata."""

from collections.abc import Callable
from dataclasses import asdict
import json
import socket

from metor.core.api import (
    ClientUnlockMethod,
    GetGuiPreferencesCommand,
    GuiPreferenceFailure,
    GuiPreferences,
    GuiPreferencesEvent,
    GuiPreferencesRejectedEvent,
    IpcCommand,
    IpcEvent,
    RuntimeStateChangedEvent,
    SetGuiPreferencesCommand,
)
from metor.data.sql import ProfileMetadataRepository


class ProfileMetadataCommandHandler:
    """Keeps protected persistence and authorization outside any frontend."""

    def __init__(
        self,
        repository: Callable[[], ProfileMetadataRepository],
        full_auth: Callable[[socket.socket], bool],
        notify: Callable[[IpcEvent], None],
        pin_available: Callable[[], bool],
    ) -> None:
        """Binds one unlocked runtime and its existing session authorization owner.

        Args:
            repository: Lazy access to this runtime's protected SQL metadata.
            full_auth: Whether the session has full-password strength now.
            notify: Content-free invalidation publisher.
            pin_available: Core verifier availability, with no credential disclosure.
        Returns:
            None
        """
        self._repository = repository
        self._full_auth = full_auth
        self._notify = notify
        self._pin_available = pin_available

    def instance_id(self) -> str:
        """Supplies the public snapshot's stable profile-instance identity.

        Args:
            None
        Returns:
            str: Opaque persisted profile identity.
        """
        return self._repository().instance_id

    @staticmethod
    def _decode_preferences(payload: str | None) -> tuple[GuiPreferences, bool]:
        """Validates protected values while retiring only known obsolete permissions."""
        if payload is None:
            return GuiPreferences(), False
        stored = json.loads(payload)
        if not isinstance(stored, dict):
            raise ValueError('Invalid protected preference document')
        retired = {'auto_play', 'keep_live_locked', 'accept_live_locked'}
        migrated = bool(retired.intersection(stored))
        for name in retired:
            stored.pop(name, None)
        decoded = IpcEvent.from_dict(
            {'event_type': 'gui_preferences', 'preferences': stored}
        )
        if not isinstance(decoded, GuiPreferencesEvent):
            raise ValueError('Invalid protected preference document')
        return decoded.preferences, migrated

    def call_lock_acceptance_enabled(self) -> bool:
        """Reads the protected Core policy; caller-supplied lock flags cannot enable it."""
        try:
            _revision, payload = self._repository().read_gui()
            preferences, _migrated = self._decode_preferences(payload)
            return preferences.accept_calls_locked
        except (PermissionError, ValueError, TypeError):
            return False

    def handle(self, command: IpcCommand, connection: socket.socket) -> IpcEvent:
        """Reads or compare-and-swaps one authorized protected preference document.

        Args:
            command: Typed preference operation from the managed dispatcher.
            connection: Authenticated unrestricted requesting client.
        Returns:
            IpcEvent: Authoritative values or an explicit non-mutating rejection.
        """
        if not isinstance(
            command, (GetGuiPreferencesCommand, SetGuiPreferencesCommand)
        ):
            return GuiPreferencesRejectedEvent(GuiPreferenceFailure.UNSUPPORTED)
        repository = self._repository()
        try:
            revision, payload = repository.read_gui()
            preferences, migrated = self._decode_preferences(payload)
            if migrated:
                sanitized = json.dumps(asdict(preferences), separators=(',', ':'))
                accepted_revision = repository.write_gui(revision, sanitized)
                if accepted_revision is None:
                    return GuiPreferencesRejectedEvent(GuiPreferenceFailure.CONFLICT)
                revision = accepted_revision
                self._notify(RuntimeStateChangedEvent('ui.gui'))
            if isinstance(command, SetGuiPreferencesCommand):
                command.preferences.__post_init__()
                if (
                    command.preferences.unlock_method != preferences.unlock_method
                    or command.preferences.setup_complete != preferences.setup_complete
                    or command.preferences.accept_calls_locked
                    != preferences.accept_calls_locked
                ) and not self._full_auth(connection):
                    return GuiPreferencesRejectedEvent(
                        GuiPreferenceFailure.FULL_AUTH_REQUIRED
                    )
                if (
                    command.preferences.unlock_method is ClientUnlockMethod.PIN
                    and not self._pin_available()
                ):
                    return GuiPreferencesRejectedEvent(
                        GuiPreferenceFailure.PIN_UNAVAILABLE
                    )
                payload = json.dumps(asdict(command.preferences), separators=(',', ':'))
                accepted = repository.write_gui(command.expected_revision, payload)
                if accepted is None:
                    return GuiPreferencesRejectedEvent(GuiPreferenceFailure.CONFLICT)
                revision = accepted
                preferences = command.preferences
                self._notify(RuntimeStateChangedEvent('ui.gui'))
            return GuiPreferencesEvent(repository.instance_id, revision, preferences)
        except PermissionError:
            return GuiPreferencesRejectedEvent(
                GuiPreferenceFailure.PROTECTED_STORAGE_UNAVAILABLE
            )
        except (ValueError, TypeError):
            return GuiPreferencesRejectedEvent(GuiPreferenceFailure.INVALID_PREFERENCES)
