"""Descriptor-driven Core settings with exact activation ownership and readback."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metor.core.api import (
    ConfigListDataEvent,
    ConfigUpdatedEvent,
    GetConfigListCommand,
    IpcEvent,
    SetConfigCommand,
    SettingSnapshotEntry,
    SettingTypeErrorEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from .controller import GuiController


@dataclass(frozen=True)
class SettingMutation:
    """One explicitly saved profile override and its original displayed expectation."""

    operation: str
    key: str
    value: str | int | float | bool
    expected: str


class CoreSettings:
    """Keeps only finite public descriptors and current presentation outcomes."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an inert current-activation settings reader.

        Args:
            controller: Authorized SDK operation owner.
        Returns:
            None
        """
        self.controller = controller
        self.entries: tuple[SettingSnapshotEntry, ...] = ()
        self.pending: SettingMutation | None = None
        self.refresh_needed = True
        self.loaded = False
        self.last_read_success = False
        self.error = ''
        self.revision = 0
        self.completed_operation = ''
        self.completed_success = False
        self._serial = 0
        self._unknown = False

    def save(
        self, entry: SettingSnapshotEntry, value: str | int | float | bool
    ) -> str | None:
        """Saves a permitted profile override against its displayed effective value.

        Args:
            entry: Original safe descriptor captured when the editor opened.
            value: Explicit typed user input, validated again by Core.
        Returns:
            str | None: Admitted operation identity, or no admitted mutation.
        """
        controller, client = self.controller, self.controller.client
        if (
            client is None
            or controller.state.covered
            or self.pending is not None
            or not entry.editable
            or entry.scope != 'profile'
            or 'safe_setting_descriptors' not in controller.state.capabilities
        ):
            return None
        self._serial += 1
        mutation = SettingMutation(
            'core-setting:' + str(self._serial), entry.key, value, entry.value
        )
        if not controller.submit(
            mutation.operation,
            lambda: client.request(
                SetConfigCommand(
                    mutation.key,
                    mutation.value,
                    safe_only=True,
                    expected_value=mutation.expected,
                ),
                IpcEvent,
            ),
        ):
            return None
        self.pending = mutation
        self.error = ''
        self._unknown = False
        self.revision += 1
        return mutation.operation

    def install(self, update: Update) -> bool:
        """Retains actual values and performs only readback after an uncertain save.

        Args:
            update: Generation-validated public result.
        Returns:
            bool: Whether this settings owner handled the update.
        """
        mutation = self.pending
        if mutation is not None and update.operation == mutation.operation:
            event = update.event
            success = (
                isinstance(event, ConfigUpdatedEvent) and event.key == mutation.key
            )
            self.completed_operation = mutation.operation
            self.completed_success = success
            self.error = (
                ''
                if success
                else event.reason or 'This value was rejected by the service.'
                if isinstance(event, SettingTypeErrorEvent)
                else 'Save is unconfirmed. Recheck the current value before saving again.'
            )
            self._unknown = event is None
            if not self._unknown:
                self.pending = None
            self.refresh_needed = True
            self.revision += 1
            return True
        if update.operation != 'core-settings:read':
            return False
        if self.controller.state.covered:
            self.cover()
            return True
        event = update.event
        if (
            isinstance(event, ConfigListDataEvent)
            and len(event.entries) <= GuiLimits.PAGE_ITEMS
            and len(event.to_json().encode('utf-8')) <= GuiLimits.SETTINGS_BYTES
        ):
            self.entries = tuple(event.entries)
            self.loaded = True
            self.last_read_success = True
            if self._unknown:
                self.pending = None
                self._unknown = False
            self.revision += 1
        else:
            self.last_read_success = False
            self.error = (
                'Current service settings could not be read. Retry when available.'
            )
            self.revision += 1
        return True

    def reload(self) -> None:
        """Requests one deliberate read-only refresh while preserving uncertain intent.

        Args:
            None
        Returns:
            None
        """
        self.refresh_needed = True

    def cover(self) -> None:
        """Drops displayed private values and requires fresh readback after unlock.

        Args:
            None
        Returns:
            None
        """
        self.entries = ()
        self.loaded = False
        self.last_read_success = False
        self.refresh_needed = True
        self.revision += 1

    def poll(self) -> None:
        """Reads finite descriptors only from an authorized settings surface.

        Args:
            None
        Returns:
            None
        """
        controller, client = self.controller, self.controller.client
        if (
            not self.refresh_needed
            or client is None
            or controller.state.covered
            or controller.state.route.view not in {'V17', 'V19'}
            or 'safe_setting_descriptors' not in controller.state.capabilities
        ):
            return
        if controller.submit(
            'core-settings:read',
            lambda: client.request(
                GetConfigListCommand(safe_descriptors=True), ConfigListDataEvent
            ),
        ):
            self.refresh_needed = False
