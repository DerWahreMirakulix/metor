"""Active-profile password and address mutations with explicit Core outcome handling."""

from typing import TYPE_CHECKING

from metor.core.api import (
    AddressGeneratedEvent,
    ChangePasswordCommand,
    GenerateAddressCommand,
    IpcEvent,
    PasswordChangedEvent,
)
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from ..controller import GuiController


class ProfileIdentity:
    """Keeps operation metadata while credentials belong only to one admitted request."""

    def __init__(self, controller: 'GuiController') -> None:
        """Binds one identity owner to the current authenticated profile.

        Args:
            controller: Public SDK owner.
        Returns:
            None
        """
        self.controller = controller
        self.serial = 0
        self.outcome = ''
        self.error = ''
        self.unknown = False

    def change_password(self, current: str, new: str) -> bool:
        """Supplies Core with the actual full current password and confirmed replacement.

        Args:
            current: One-use profile password; never a substituted PIN.
            new: Explicit replacement password.
        Returns:
            bool: Whether the operation was admitted once.
        """
        controller, client = self.controller, self.controller.client
        if client is None or controller.state.covered or self.unknown:
            return False
        command = ChangePasswordCommand(current, new)

        def request() -> IpcEvent | None:
            """Drops command secret references after its only SDK request.

            Args:
                None
            Returns:
                IpcEvent | None: Actual Core password result.
            """
            try:
                return client.request(command, PasswordChangedEvent)
            finally:
                command.current_password = command.new_password = ''

        admitted = controller.submit('identity:password', request)
        if not admitted:
            command.current_password = command.new_password = ''
        else:
            self.serial += 1
            self.outcome, self.error = 'pending', ''
        return admitted

    def generate_address(self) -> bool:
        """Submits only an explicitly confirmed identity rotation for Core eligibility checks.

        Args:
            None
        Returns:
            bool: Whether the operation was admitted.
        """
        controller, client = self.controller, self.controller.client
        if client is None or controller.state.covered or self.unknown:
            return False
        admitted = controller.submit(
            'identity:address',
            lambda: client.request(GenerateAddressCommand(), AddressGeneratedEvent),
        )
        if admitted:
            self.serial += 1
            self.outcome, self.error = 'pending', ''
        return admitted

    def install(self, update: Update) -> bool:
        """Retains actual identity and blocks repeats when a mutation's result is unknown.

        Args:
            update: Generation-qualified result.
        Returns:
            bool: Whether this owner consumed the result.
        """
        if not update.operation.startswith('identity:'):
            return False
        event = update.event
        if isinstance(event, (PasswordChangedEvent, AddressGeneratedEvent)):
            self.outcome, self.error = 'saved', ''
            self.controller.state.status = (
                'Password changed'
                if isinstance(event, PasswordChangedEvent)
                else 'Address generated'
            )
            self.controller.refresh_state()
        elif event is not None:
            self.outcome = 'rejected'
            self.error = {
                'invalid_password': 'The current profile password was not accepted.',
                'invalid_new_password': 'The new password was not accepted.',
                'password_change_unsupported': 'Password change requires encrypted profile storage.',
                'address_cant_generate_running': 'Address generation requires a stopped profile runtime. Closing this window does not stop the shared runtime.',
            }.get(
                event.event_type.value,
                'Metor refused this profile change. Its current restrictions still apply.',
            )
        else:
            self.outcome, self.unknown = 'unknown', True
            self.error = 'The change is unconfirmed. Re-enter the profile explicitly to check its current identity or password; do not repeat this operation.'
        if self.error:
            self.controller.state.status = self.error
        return True
