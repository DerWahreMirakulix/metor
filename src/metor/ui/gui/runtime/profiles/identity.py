"""Active-profile password and address mutations with explicit Core outcome handling."""

from typing import TYPE_CHECKING

from metor.client import (
    FrontendAddressManagement,
    FrontendProfileAddressRequest,
    FrontendProfileOperationResult,
    OneUseSecretProvider,
)

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
        self.address_request: FrontendProfileAddressRequest | None = None
        self.address_result: FrontendProfileOperationResult | None = None

    def offline_address(
        self, profile: str, selected: str, password: str, *, generate: bool = True
    ) -> bool:
        """Uses an optional public host for one explicitly selected stopped profile's address.

        Args:
            profile: Exact original catalog target.
            selected: Host selection shown when the form opened.
            password: One-use full target-profile password.
            generate: False performs only readback after an uncertain generation.
        Returns:
            bool: Whether the bounded operation was admitted without changing GUI activation.
        """
        controller, host = self.controller, self.controller.context.host
        request = FrontendProfileAddressRequest(profile, selected, generate)
        if (
            controller.simulator
            or controller.state.covered
            or not isinstance(host, FrontendAddressManagement)
            or self.unknown
            and (
                generate
                or self.address_request is None
                or self.address_request.profile != profile
                or self.address_request.selected_profile != selected
            )
        ):
            return False
        secret = OneUseSecretProvider(password)
        generation = controller.state.generation

        def run() -> IpcEvent | None:
            """Installs only an exact host result and consumes the credential on every path.

            Args:
                None
            Returns:
                IpcEvent | None: Local host outcome uses the typed mailbox field.
            """
            try:
                result = host.profile_address(request, secret)
                controller.mailbox.put(
                    Update(generation, 'identity:offline-result', profile_result=result)
                )
            finally:
                secret.take()
            return None

        admitted = controller.submit('identity:offline-complete', run)
        if admitted:
            self.serial += 1
            self.address_request = request
            self.address_result = None
            self.outcome, self.error = 'pending', ''
        else:
            secret.take()
        return admitted

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
        """Submits explicitly confirmed address generation under Core's actual identity policy.

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
        if update.operation == 'identity:offline-complete' and not update.status:
            return True
        if update.operation == 'identity:offline-result':
            result = update.profile_result
            if (
                result is not None
                and self.address_request is not None
                and result.profile == self.address_request.profile
            ):
                self.address_result = result
                self.outcome = 'saved' if result.success else 'rejected'
                self.unknown = False
                self.error = (
                    ''
                    if result.success
                    else {
                        'invalid_password': 'The full profile password was not accepted.',
                        'address_cant_generate_running': 'This profile is running. Address generation is unavailable.',
                        'address_not_generated': 'No contact address is available yet.',
                        'selection_changed': 'The selected profile changed. Reopen the profile form.',
                        'local_profile_required': 'Choose an existing local profile.',
                    }.get(result.code, 'Metor could not provide this profile address.')
                )
                if not self.controller.state.covered:
                    self.controller.state.status = (
                        self.error or 'Address available for ' + result.profile
                    )
                return True
        event = update.event
        if isinstance(event, (PasswordChangedEvent, AddressGeneratedEvent)):
            self.outcome, self.error = 'saved', ''
            if not self.controller.state.covered:
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
        if self.error and not self.controller.state.covered:
            self.controller.state.status = self.error
        return True
