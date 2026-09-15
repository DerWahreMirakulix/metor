"""Deferred graphical profile activation through the public host and SDK boundary."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metor.client import FrontendProfileCreateRequest, MetorClient, OneUseSecretProvider
from metor.core.api import (
    GetGuiPreferencesCommand,
    GuiPreferencesEvent,
    IpcEvent,
    InitEvent,
    VoiceOwnerRegisteredEvent,
    ListRetainedMessagesCommand,
    RetainedMessagesEvent,
    RuntimeSnapshotEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

# Local Package Imports
from .voice import VoiceOwnerLease
from .interaction import Interactions

if TYPE_CHECKING:
    from .controller import GuiController


class ProfileActivation:
    """Owns graphical bootstrap and profile creation without frontend storage access."""

    def __init__(self, controller: 'GuiController') -> None:
        """Binds activation to one public-service GUI coordinator.

        Args:
            controller: Current GUI coordinator.
        Returns:
            None
        """
        self.controller = controller

    def open_profile(self) -> bool:
        """Starts graphical bootstrap, subscription, snapshot and inventory.

        Args:
            None
        Returns:
            bool: Whether activation was started.
        """

        controller = self.controller
        if controller.simulator:
            controller.state.snapshot = RuntimeSnapshotEvent(
                profile='Simulator', onion='', epoch='simulator'
            )
            controller.state.covered = False
            controller.state.route = Route('V06')
            return True
        generation = controller.state.generation
        interactions = controller.interactions

        def bootstrap() -> IpcEvent | None:
            """Obtains authoritative state without a terminal prompt.

            Args:
                None
            Returns:
                IpcEvent | None: Fully obtained snapshot or failed bootstrap.
            """
            client = self.connect(generation, interactions)
            installed = False
            try:
                initialized = client.bootstrap()
                if initialized is None:
                    return None
                activation = self.hydrate(client, initialized)
                if not controller.adopt_client(client, generation):
                    return None
                installed = True
                self.publish(activation, generation)
                return activation.snapshot
            finally:
                interactions.startup_secret(None)
                if not installed:
                    client.disconnect()

        controller.state.status = 'Opening profile…'
        return controller.submit('bootstrap', bootstrap)

    def connect(self, generation: int, interactions: Interactions) -> MetorClient:
        """Creates an unactivated SDK candidate using only the selected public host.

        Args:
            generation: Candidate activation identity captured by its callbacks.
            interactions: Candidate-owned one-use credential bridge.
        Returns:
            MetorClient: Inert candidate awaiting canonical SDK bootstrap.
        """
        controller = self.controller
        result = controller.context.host.bootstrap(interactions)
        interactions.startup_secret(result.session_auth)

        def on_event(event: IpcEvent) -> None:
            """Queues a typed candidate event without manipulating GUI state.

            Args:
                event: Public Core event.
            Returns:
                None
            """
            if not controller.purge.observe(generation, event):
                controller.mailbox.put(Update(generation, 'event', event))

        def on_disconnect() -> None:
            """Marks loss only for this captured candidate activation.

            Args:
                None
            Returns:
                None
            """
            if not controller.purge.lost(generation):
                controller.mailbox.put(
                    Update(generation, 'lost', status='Connection lost')
                )

        return MetorClient(
            result.port,
            auth_provider=interactions,
            on_event=on_event,
            on_disconnect=on_disconnect,
        )

    def hydrate(
        self, client: MetorClient, initialized: InitEvent
    ) -> 'ActivatedProfile':
        """Obtains subscribed snapshot, staging ownership and protected preferences.

        Args:
            client: Authenticated candidate; not yet installed in the GUI.
            initialized: Actual negotiated capabilities from SDK bootstrap.
        Returns:
            ActivatedProfile: Complete candidate metadata, or raises before publication.
        """
        if not client.register_live_consumer():
            raise RuntimeError('Consumer registration failed')
        snapshot = client.runtime_snapshot()
        owner = None
        if 'disposable_voice_owner' in initialized.capabilities:
            owner = VoiceOwnerLease.register(client)
            if owner is None or not owner.owner_token:
                raise RuntimeError('Voice ownership unavailable')
        inventory = client.request(
            ListRetainedMessagesCommand(
                limit=GuiLimits.PAGE_ITEMS,
                owner_token=owner.owner_token if owner is not None else None,
            ),
            RetainedMessagesEvent,
        )
        if snapshot is None or inventory is None:
            raise RuntimeError('Profile hydration failed')
        preferences = None
        if 'protected_gui_preferences' in initialized.capabilities:
            preferences = client.request(
                GetGuiPreferencesCommand(), GuiPreferencesEvent
            )
            if (
                preferences is None
                or preferences.profile_instance_id != snapshot.profile_instance_id
            ):
                raise RuntimeError('Protected preferences unavailable')
        return ActivatedProfile(
            client, snapshot, initialized, inventory, owner, preferences
        )

    def publish(self, activation: 'ActivatedProfile', generation: int) -> None:
        """Queues complete candidate metadata before its final bootstrap snapshot.

        Args:
            activation: Hydrated candidate selected for this GUI.
            generation: Current activation identity.
        Returns:
            None
        """
        mailbox = self.controller.mailbox
        mailbox.put(Update(generation, 'capabilities', activation.initialized))
        if activation.owner is not None:
            mailbox.put(Update(generation, 'voice_owner', activation.owner))
        if activation.preferences is not None:
            mailbox.put(Update(generation, 'preferences', activation.preferences))
        mailbox.put(Update(generation, 'inventory', activation.inventory))

    def create_profile(self, name: str, password: str) -> bool:
        """Creates only an encrypted profile via the public host boundary.

        Args:
            name: User-supplied profile name.
            password: Single-use creation credential.
        Returns:
            bool: Whether creation was admitted.
        """

        controller = self.controller
        if controller.simulator:
            controller.state.status = 'Profile creation is unavailable in simulation'
            return False
        secret = OneUseSecretProvider(password)

        def create() -> IpcEvent | None:
            """Creates one profile without accessing its files.

            Args:
                None
            Returns:
                IpcEvent | None: No content result; failure is explicit.
            """
            result = controller.context.host.create_profile(
                FrontendProfileCreateRequest(name), secret
            )
            if not result.success:
                raise RuntimeError('Profile creation failed')
            controller.context.host.select_profile(result.profile)
            return None

        return controller.submit('create', create)


@dataclass(frozen=True)
class ActivatedProfile:
    """One fully hydrated public SDK candidate; never contains reusable credentials."""

    client: MetorClient
    snapshot: RuntimeSnapshotEvent
    initialized: InitEvent
    inventory: RetainedMessagesEvent
    owner: VoiceOwnerRegisteredEvent | None
    preferences: GuiPreferencesEvent | None
