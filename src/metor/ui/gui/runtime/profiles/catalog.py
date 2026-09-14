"""Bounded public-host catalog operations with exact targets and unknown-result barriers."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from metor.client import (
    FrontendProfileCatalog,
    FrontendProfileChange,
    FrontendProfileCreateRequest,
    FrontendProfileManagement,
    FrontendProfileOperationResult,
    OneUseSecretProvider,
)
from metor.core.api import IpcEvent
from metor.shared import Constants
from metor.ui.gui.state.mailbox import Update
from metor.ui.gui.state import Route

if TYPE_CHECKING:
    from ..controller import GuiController


class ProfileCatalog:
    """Retains one finite local metadata page and one admitted catalog mutation."""

    def __init__(self, controller: 'GuiController') -> None:
        """Binds catalog state to one activation without touching host files.

        Args:
            controller: Current GUI public-service owner.
        Returns:
            None
        """
        self.controller = controller
        self.page: FrontendProfileCatalog | None = None
        self.revision = 0
        self.serial = 0
        self.outcome = ''
        self.error = ''
        self.pending = False
        self.unknown = False
        self._needed = False
        self._after: str | None = None

    @property
    def host(self) -> FrontendProfileManagement | None:
        """Checks the optional public extension while keeping simulation inert.

        Args:
            None
        Returns:
            FrontendProfileManagement | None: Supported local catalog service.
        """
        host = self.controller.context.host
        return (
            host
            if not self.controller.simulator
            and isinstance(host, FrontendProfileManagement)
            else None
        )

    def reload(self, after: str | None = None) -> None:
        """Schedules one exact read; a failed read leaves the displayed page intact.

        Args:
            after: Exclusive name bookmark or first page.
        Returns:
            None
        """
        self._after, self._needed = after, True

    def poll(self) -> None:
        """Reads only on permitted catalog surfaces through the serialized worker.

        Args:
            None
        Returns:
            None
        """
        controller = self.controller
        if not self._needed or controller.state.route.view not in {'V02', 'V20'}:
            return
        if controller.state.covered and controller.client is not None:
            return
        host = self.host
        if host is None:
            self.error = 'Profile management is unavailable in this deployment.'
            self._needed = False
            self.revision += 1
            return
        generation, after = controller.state.generation, self._after

        def read() -> IpcEvent | None:
            """Transfers bounded catalog metadata without a frontend filesystem scan.

            Args:
                None
            Returns:
                IpcEvent | None: Host results use their separate typed mailbox field.
            """
            page = host.profile_catalog(after, Constants.FRONTEND_PROFILE_PAGE_ITEMS)
            if len(page.entries) > Constants.FRONTEND_PROFILE_PAGE_ITEMS:
                raise ValueError('Profile page exceeds its public bound')
            controller.mailbox.put(
                Update(generation, 'profiles:page', profile_catalog=page)
            )
            return None

        if controller.submit('profiles:read', read):
            self._needed = False

    def change(self, change: FrontendProfileChange) -> bool:
        """Submits an originally captured selected-host context and mutation target.

        Args:
            change: Validated public operation with original target and selection.
        Returns:
            bool: Whether one mutation was admitted.
        """
        host = self.host
        return host is not None and self._mutate(lambda: host.manage_profile(change))

    def select(self, name: str) -> bool:
        """Selects a startup profile off the GUI thread without an active-runtime switch.

        Args:
            name: Exact permitted local catalog entry.
        Returns:
            bool: Whether startup selection was admitted.
        """
        controller = self.controller
        if (
            controller.simulator
            or controller.client is not None
            or controller.state.route.view != 'V02'
        ):
            return False
        generation = controller.state.generation

        def select() -> IpcEvent | None:
            """Publishes the host's actual selected entry without starting its runtime.

            Args:
                None
            Returns:
                IpcEvent | None: Local result uses a dedicated typed field.
            """
            selected = controller.context.host.select_profile(name)
            controller.mailbox.put(
                Update(
                    generation,
                    'profiles:selected',
                    profile_result=FrontendProfileOperationResult(
                        selected.exists, 'selected', selected.profile
                    ),
                )
            )
            return None

        return controller.submit('profiles:select', select)

    def create(self, name: str, password: str) -> bool:
        """Creates an encrypted catalog entry without switching the active host selection.

        Args:
            name: Exact user-selected name.
            password: One-use masked creation credential.
        Returns:
            bool: Whether one creation was admitted.
        """
        host = self.host
        secret = OneUseSecretProvider(password)

        def create() -> FrontendProfileOperationResult:
            """Consumes the secret even if the local host rejects or raises.

            Args:
                None
            Returns:
                FrontendProfileOperationResult: Actual creation result.
            """
            try:
                assert host is not None
                return host.create_profile_entry(
                    FrontendProfileCreateRequest(name), secret
                )
            finally:
                secret.take()

        admitted = host is not None and self._mutate(create)
        if not admitted:
            secret.take()
        return admitted

    def _mutate(self, operation: Callable[[], FrontendProfileOperationResult]) -> bool:
        """Admits at most one host mutation and preserves uncertainty until explicit readback.

        Args:
            operation: Exact public host call, never a mutable selection lookup.
        Returns:
            bool: Whether the serialized operation was accepted.
        """
        controller = self.controller
        if controller.state.covered or self.pending or self.unknown:
            return False
        generation = controller.state.generation

        def mutate() -> IpcEvent | None:
            """Publishes actual host success or refusal without synthesizing an IPC event.

            Args:
                None
            Returns:
                IpcEvent | None: Result is carried in the typed local mailbox field.
            """
            result = operation()
            controller.mailbox.put(
                Update(generation, 'profiles:result', profile_result=result)
            )
            return None

        if not controller.submit('profiles:mutation', mutate):
            return False
        self.pending = True
        self.serial += 1
        self.outcome = 'pending'
        self.error = ''
        self.revision += 1
        return True

    def install(self, update: Update) -> bool:
        """Installs actual bounded catalog state and safely labelled mutation outcomes.

        Args:
            update: Generation-validated local host result.
        Returns:
            bool: Whether this catalog consumed the update.
        """
        if not update.operation.startswith('profiles:'):
            return False
        state = self.controller.state
        if state.covered and state.route.view != 'V02':
            if update.operation in {'profiles:mutation', 'profiles:result'}:
                self.pending = False
                if update.profile_result is not None:
                    self.outcome = (
                        'saved' if update.profile_result.success else 'rejected'
                    )
                elif update.status:
                    self.unknown = True
                    self.outcome = 'unknown'
            self._needed = True
            return True
        if update.profile_catalog is not None:
            self.page = update.profile_catalog
            self.error = ''
            self.unknown = False
        elif update.profile_result is not None:
            result = update.profile_result
            if update.operation == 'profiles:selected':
                if result.success:
                    state.route = Route('V01')
                    state.status = ''
                else:
                    self.error = 'Profile unavailable. Retry or choose another.'
                    state.status = self.error
                self.revision += 1
                return True
            self.pending = False
            self.outcome = 'saved' if result.success else 'rejected'
            self.error = (
                ''
                if result.success
                else {
                    'cannot_remove_active': 'Switch to another profile before removing this one.',
                    'cannot_remove_default': 'Choose another default before removing this profile.',
                    'cannot_remove_running': 'This profile is running. Removal is unavailable.',
                    'cannot_rename_running': 'This profile is running. Rename is unavailable.',
                    'selection_changed': 'The selected profile changed. Reload the catalog.',
                    'invalid_name': 'Use letters, numbers, hyphens or underscores for the profile name.',
                    'renamed_default_unconfirmed': 'The profile was renamed, but its default selection could not be updated. Reload and choose the default explicitly.',
                    'profile_exists': 'A profile with this name already exists.',
                }.get(
                    result.code,
                    'The profile operation was refused. Reload and review its current state.',
                )
            )
            state.status = self.error or 'Profile updated'
            self.reload()
        elif update.status:
            if update.operation == 'profiles:mutation':
                self.pending = False
                self.unknown = True
                self.outcome = 'unknown'
                self.error = 'Profile change is unconfirmed. Reload before making another change.'
            else:
                self.error = 'Could not read the profile catalog. Retry.'
            state.status = self.error
        self.revision += 1
        return True
