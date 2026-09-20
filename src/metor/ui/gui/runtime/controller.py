"""Serial bounded SDK operations and generation-safe UI result installation."""

from collections.abc import Callable
import threading

from metor.client import (
    FrontendLaunchContext,
    MetorClient,
    MetorRequestRejectedError,
)
from metor.core.api import (
    Delivery,
    EventType,
    DaemonLockedEvent,
    SelfDestructInitiatedEvent,
    GuiPreferencesEvent,
    GuiPreferencesRejectedEvent,
    IpcCommand,
    IpcEvent,
    InitEvent,
    MessagesDataEvent,
    VoiceOwnerRegisteredEvent,
    VoiceIncomingStartedEvent,
    VoiceChunkReceivedEvent,
    VoiceFinalizedEvent,
    RuntimeSnapshotEvent,
    RuntimeStateChangedEvent,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import GuiState, Route
from metor.ui.gui.state.mailbox import Mailbox, Update

# Local Package Imports
from .interaction import Interactions
from .activation import ProfileActivation
from .preferences import PreferenceBridge
from .settings import CoreSettings
from .history import ActivityHistory
from .security import SecurityController
from .text import TextController
from .drop import DropActions
from .live import LiveActions
from .voice import VoiceOwnerLease, VoiceController, InputBridge
from .playback import PlaybackController
from .transcript import Transcript
from .handoff import TextHandoff
from .pages import ArchivePages, InventoryPages
from .contacts import ContactFlow
from .notifications import Notifications
from .calls import IncomingCalls
from .profiles import ProfileCatalog, ProfileTransition, ProfileIdentity
from .resend import ResendActions
from .receipts import ReceiptReconciliation
from .purge import PurgeMonitor
from .device import DeviceLifecycle


class GuiController:
    """Coordinates public clients; workers never manipulate toolkit widgets."""

    def __init__(self, context: FrontendLaunchContext, simulator: bool = False) -> None:
        """Creates an inert controller; no host/transport starts before Open.

        Args:
            context: Injected public host and typed launch options.
            simulator: Explicit isolated mode; host/client creation is prohibited.
        Returns:
            None
        """
        self.context = context
        self.simulator = simulator
        self.state = GuiState()
        self.mailbox = Mailbox()
        self.interactions = Interactions(self.state.generation, self.mailbox)
        self.client: MetorClient | None = None
        self.messages: MessagesDataEvent | None = None
        self.preferences = PreferenceBridge(self)
        self.core_settings = CoreSettings(self)
        self.history = ActivityHistory(self)
        self.security = SecurityController(self)
        self._worker: threading.Thread | None = None
        self._worker_background = False
        self._deferred_work: tuple[int, str, Callable[[], IpcEvent | None]] | None = (
            None
        )
        self._guard = threading.Lock()
        self._refresh_needed: bool = False
        self._messages_needed: bool = False
        self.text = TextController(self)
        self.drop = DropActions(self)
        self.live = LiveActions(self)
        self.voice_owner = VoiceOwnerLease()
        self.voice = VoiceController(self)
        self.inputs = InputBridge()
        self.activation = ProfileActivation(self)
        self.playback = PlaybackController(self)
        self.transcript = Transcript(self)
        self.handoff = TextHandoff(self)
        self.archive = ArchivePages(self)
        self.inventory = InventoryPages(self)
        self.contacts = ContactFlow(self)
        self.notifications = Notifications(self)
        self.calls = IncomingCalls(self)
        self._unknown_actions: set[str] = set()
        self.profiles = ProfileCatalog(self)
        self.lifecycle = ProfileTransition(self)
        self.identity = ProfileIdentity(self)
        self.resend = ResendActions(self)
        self.receipts = ReceiptReconciliation(self)
        self.purge = PurgeMonitor(self)
        self.device = DeviceLifecycle(self, context.platform)

    def submit(
        self,
        operation: str,
        work: Callable[[], IpcEvent | None],
        *,
        background: bool = False,
    ) -> bool:
        """Admits one operation; double activation cannot enqueue duplicates.

        Args:
            operation: Stable operation/route identity.
            work: Worker callable using a captured client and target.
            background: Read-only restricted refresh that must not replace auth focus.
        Returns:
            bool: Whether this exact operation was admitted.
        """
        with self._guard:
            if self.purge.active:
                return False
            if (
                not background
                and not self.state.busy
                and operation not in self._unknown_actions
                and self._deferred_work is None
                and self._worker_background
                and self._worker is not None
                and self._worker.is_alive()
            ):
                self._deferred_work = (self.state.generation, operation, work)
                self.state.busy = True
                return True
            if (
                operation in self._unknown_actions
                or self.state.busy
                or (self._worker is not None and self._worker.is_alive())
            ):
                return False
            generation = self.state.generation
            self._worker_background = background
            if not background:
                self.state.busy = True

            def run() -> None:
                """Executes one bounded SDK request off the GUI loop.

                Args:
                    None
                Returns:
                    None
                """
                try:
                    event = work()
                    update = Update(generation, operation, event)
                    if event is None and operation.startswith('A'):
                        update = Update(
                            generation,
                            operation,
                            status='Operation could not be confirmed',
                        )
                except MetorRequestRejectedError as exc:
                    update = Update(
                        generation,
                        operation,
                        exc.event,
                        status='Operation was rejected',
                    )
                except Exception:
                    update = Update(
                        generation, operation, status='Operation could not be confirmed'
                    )
                self.mailbox.put(update)

            self._worker = threading.Thread(
                target=run, name='metor-gui-operation', daemon=True
            )
            self._worker.start()
            return True

    def open_profile(self) -> bool:
        """Starts deferred graphical profile activation.

        Args:
            None
        Returns:
            bool: Whether activation was admitted.
        """
        return False if self.purge.active else self.activation.open_profile()

    def adopt_client(self, client: MetorClient, generation: int) -> bool:
        """Installs a completed bootstrap only into its still-current activation.

        Args:
            client: Fully authenticated and initialized SDK client.
            generation: Generation captured before deferred host interaction.
        Returns:
            bool: Whether the client was installed rather than abandoned.
        """
        with self._guard:
            if generation != self.state.generation:
                return False
            self.client = client
            return True

    def create_profile(self, name: str, password: str) -> bool:
        """Creates an encrypted profile through the public host boundary.

        Args:
            name: User-selected profile name.
            password: One-use creation credential.
        Returns:
            bool: Whether creation was admitted.
        """
        return (
            False
            if self.purge.active
            else self.activation.create_profile(name, password)
        )

    def navigate(self, route: Route) -> None:
        """Opens a projection without a communication-changing command.

        Args:
            route: Foreground route and canonical peer.
        Returns:
            None
        """
        if self.state.covered:
            return
        if route != self.state.route:
            self.voice.depart()
            self.playback.stop()
        self.state.navigate(route)
        if route.view in {'V17', 'V19'}:
            self.core_settings.reload()
        if route.view == 'V18':
            self.history.open(route.history_raw)
        if route.view == 'V20':
            self.profiles.reload()
            self.refresh_state()
        self.archive.reset()
        self.inventory.reset()
        self.handoff.needed = True
        if route.peer is not None and route.delivery == Delivery.DROP:
            self.load_messages()

    def back(self) -> None:
        """Stops the bound press before returning to the previous projection.

        Args:
            None
        Returns:
            None
        """
        if not self.state.covered:
            self.voice.depart()
            self.playback.stop()
            self.state.back()
            if self.state.route.view == 'V18':
                self.history.open(self.state.route.history_raw)
            self.handoff.needed = True
            self.archive.reset()
            self.inventory.reset()
            if self.state.route.delivery is Delivery.DROP:
                self.load_messages()

    def load_messages(self) -> bool:
        """Reads a bounded DROP page without consuming background Voice.

        Args:
            None
        Returns:
            bool: Whether the exact route request was admitted.
        """
        return self.archive.load()

    def refresh_state(self) -> None:
        """Requests a coalesced authoritative refresh after an explicit mutation.

        Args:
            None
        Returns:
            None
        """
        self._refresh_needed = True
        self._messages_needed = True

    def command(
        self, action: str, command: IpcCommand, expected: type[IpcEvent]
    ) -> bool:
        """Executes an explicit UI action against the current authenticated client.

        Args:
            action: Stable action/operation ID.
            command: Exact immutable target captured at activation.
            expected: Typed success result.
        Returns:
            bool: Whether the action was admitted.
        """
        client = self.client
        if self.state.covered or client is None or action in self._unknown_actions:
            return False
        return self.submit(action, lambda: client.request(command, expected))

    def send_text(self, peer: str, delivery: Delivery) -> None:
        """Binds one message ID and retains the draft until confirmed acceptance.

        Args:
            peer: Canonical peer, never a mutable alias.
            delivery: Visible composer semantics.
        Returns:
            None
        """
        self.text.send(peer, delivery)

    def poll(self) -> bool:
        """Installs generation-valid updates without blanket content revision drops.

        Args:
            None
        Returns:
            bool: Whether the presentation changed.
        """
        changed = self.purge.poll()
        changed = self.device.poll() or changed
        if self.purge.active:
            return changed
        initially_covered = self.state.covered
        for _ in range(GuiLimits.PAGE_ITEMS):
            update = self.mailbox.take()
            if update is None:
                break
            if update.generation != self.state.generation:
                continue
            changed = True
            if update.event is not None and self.purge.observe(
                update.generation, update.event
            ):
                self.purge.poll()
                if self.purge.active:
                    return True
                continue
            if self.device.install(update):
                continue
            if self.lifecycle.install(update):
                continue
            if update.event is not None:
                self.notifications.observe(update.event)
                self.calls.observe(update.event)
                if not self.state.covered and update.event.event_type in {
                    EventType.CONNECTED,
                    EventType.DISCONNECTED,
                    EventType.CONNECTION_CONNECTING,
                    EventType.CONNECTION_PENDING,
                    EventType.CONNECTION_AUTO_ACCEPTED,
                    EventType.CONNECTION_FAILED,
                    EventType.CONNECTION_REJECTED,
                    EventType.AUTO_RECONNECT_SCHEDULED,
                    EventType.INCOMING_CONNECTION,
                    EventType.PENDING_CONNECTION_EXPIRED,
                    EventType.RETUNNEL_INITIATED,
                    EventType.RETUNNEL_SUCCESS,
                    EventType.RETUNNEL_FAILED,
                    EventType.LIVE_CONTROL_REJECTED,
                }:
                    self._refresh_needed = True
            if update.operation == 'lost':
                self.close()
                self.state.status = 'Connection lost. Unsent drafts were not restored. Open profile to reconnect.'
                continue
            if not update.operation.startswith('voice-') and update.operation not in (
                'event',
                'status',
                'inventory',
                'capabilities',
                'voice_owner',
                'playback',
                'playback-done',
                'security:state',
            ):
                self.state.busy = False
            covered_status = self.state.status
            if self.profiles.install(update):
                continue
            if self.identity.install(update):
                continue
            if self.resend.install(update):
                continue
            if self.receipts.install(update):
                continue
            if self.calls.install(update):
                continue
            if self.core_settings.install(update):
                continue
            if self.history.install(update):
                continue
            if self.contacts.install(update):
                continue
            if self.drop.install(update):
                continue
            if self.live.install(update):
                continue
            if self.archive.install(update) or self.inventory.install(update):
                continue
            if self.handoff.install(update):
                continue
            if self.playback.install(update):
                continue
            if self.voice.install(update):
                if self.state.covered:
                    self.state.status = covered_status
                continue
            if self.security.install(update.operation, update.event):
                continue
            if isinstance(
                update.event, (DaemonLockedEvent, SelfDestructInitiatedEvent)
            ):
                self.close(purging=isinstance(update.event, SelfDestructInitiatedEvent))
                continue
            if isinstance(update.event, GuiPreferencesRejectedEvent):
                self.preferences.rejected(update.event)
                continue
            if update.status:
                self.state.status = update.status
                if (
                    update.status == 'Operation could not be confirmed'
                    and update.operation.startswith('A')
                ):
                    self._unknown_actions.add(update.operation)
                    if update.operation == 'A-settings':
                        self.preferences.uncertain()
            if self.text.install(update):
                continue
            if update.status:
                continue
            if self.state.covered and self.state.route.view == 'V05':
                scope = self.security.continuation.scope
                if (
                    scope is not None
                    and isinstance(
                        update.event,
                        (
                            VoiceIncomingStartedEvent,
                            VoiceChunkReceivedEvent,
                            VoiceFinalizedEvent,
                        ),
                    )
                    and update.event.onion == scope.peer
                ):
                    self.transcript.install(update.event)
                continue
            if update.event is not None and self.transcript.install(update.event):
                continue
            if (
                isinstance(update.event, InitEvent)
                and update.operation == 'capabilities'
            ):
                self.state.capabilities = frozenset(update.event.capabilities)
            elif update.operation == 'bootstrap':
                if isinstance(update.event, RuntimeSnapshotEvent):
                    self.state.snapshot = update.event
                    self.state.covered = False
                    self.security.activity()
                    preferences = self.state.preferences
                    self.state.route = Route(
                        'V04'
                        if preferences is not None
                        and not preferences.preferences.setup_complete
                        else 'V06'
                    )
                    self.state.status = ''
                else:
                    self.state.status = (
                        'Could not open profile. Retry or choose a profile.'
                    )
            elif update.operation == 'create':
                self.state.route = Route('V01')
                self.state.status = 'Profile created. Open profile to continue.'
            elif isinstance(update.event, GuiPreferencesEvent):
                if (
                    self.preferences.install(
                        update.event, confirmed_save=update.operation == 'A-settings'
                    )
                    and update.operation == 'preferences'
                ):
                    self._unknown_actions.discard('A-settings')
            elif isinstance(update.event, VoiceOwnerRegisteredEvent):
                self.voice_owner.token = update.event.owner_token
            elif isinstance(update.event, MessagesDataEvent):
                if (
                    self.state.route.delivery is Delivery.DROP
                    and update.operation == 'messages:' + (self.state.route.peer or '')
                ):
                    self.messages = update.event
            elif isinstance(update.event, RuntimeSnapshotEvent):
                current = self.state.snapshot
                if current is not None and current.epoch != update.event.epoch:
                    self.close()
                    self.state.status = 'Unlock required'
                elif current is None or (update.event.revision or 0) >= (
                    current.revision or 0
                ):
                    self.state.snapshot = update.event
            elif isinstance(update.event, RuntimeStateChangedEvent):
                if update.event.scope == 'inbox':
                    self.handoff.needed = True
                if update.event.scope == 'ui.gui':
                    self.preferences.refresh_needed = True
                else:
                    self._refresh_needed = True
                    if self.state.preferences is not None:
                        self.preferences.refresh_needed = True
        if self.mailbox.overloaded:
            self.close()
            self.state.status = 'Updating state failed. Open profile to reconnect.'
            changed = True
        if self._deferred_work is not None and (
            self._worker is None or not self._worker.is_alive()
        ):
            generation, operation, work = self._deferred_work
            self._deferred_work = None
            if generation == self.state.generation:
                self.state.busy = False
                self.submit(operation, work)
        if (
            self._refresh_needed
            and not self.state.covered
            and not self.state.busy
            and self.client is not None
        ):
            client = self.client
            if self.submit('snapshot', client.runtime_snapshot):
                self._refresh_needed = False
        self.security.poll()
        self.preferences.poll()
        self.core_settings.poll()
        self.history.poll()
        self.profiles.poll()
        self.resend.poll()
        self.receipts.poll()
        self.text.poll()
        self.voice.review_actions.poll()
        self.playback.poll()
        self.playback.auto.poll()
        self.handoff.poll()
        self.archive.poll()
        self.inventory.poll()
        self.contacts.poll()
        self.drop.poll()
        self.live.poll()
        changed = self.notifications.poll() or changed
        changed = self.calls.poll() or changed
        if self._messages_needed and not self.state.busy:
            if (
                self.state.route.peer is None
                or self.state.route.delivery is not Delivery.DROP
            ):
                self._messages_needed = False
            elif self.load_messages():
                self._messages_needed = False
        return changed or initially_covered != self.state.covered

    def close(
        self,
        purging: bool = False,
        *,
        preserve_interactions: Interactions | None = None,
        preserve_purge: bool = False,
    ) -> None:
        """Detaches this GUI without global hard lock, profile exit or host power.

        Args:
            purging: Accepted purge preempts normal producer finalization.
            preserve_interactions: Fully authenticated replacement's independent bridge.
            preserve_purge: Keeps only an accepted destruction's separate read-only observer.
        Returns:
            None
        """
        if preserve_purge and not (purging and self.purge.active):
            raise ValueError('Only accepted destruction can retain its observer')
        if not preserve_purge:
            self.purge.dispose()
            self.purge = PurgeMonitor(self)
        with self._guard:
            self.lifecycle.cancel()
            self.resend.clear()
            self.contacts.book.stop()
            self.voice.abandon(purge=purging)
            self.playback.abandon()
            if self.interactions is not preserve_interactions:
                self.interactions.cancel()
            client, self.client = self.client, None
            owner, self.voice_owner.token = self.voice_owner.token, None
            self.state.abandon()
            self._deferred_work = None
        self.messages = None
        self.preferences = PreferenceBridge(self)
        self.core_settings = CoreSettings(self)
        self.history = ActivityHistory(self)
        self._messages_needed = False
        self._refresh_needed = False
        self.security = SecurityController(self)
        self.text.clear()
        self.transcript.clear()
        self.handoff.clear()
        self.archive = ArchivePages(self)
        self.inventory = InventoryPages(self)
        self.contacts = ContactFlow(self)
        self.drop = DropActions(self)
        self.live = LiveActions(self)
        self.receipts = ReceiptReconciliation(self)
        self.notifications = Notifications(self)
        self.calls = IncomingCalls(self)
        self.profiles = ProfileCatalog(self)
        self.voice = VoiceController(self)
        self._unknown_actions.clear()
        self.playback = PlaybackController(self)
        self.mailbox.clear()
        self.identity = ProfileIdentity(self)
        self.interactions = preserve_interactions or Interactions(
            self.state.generation, self.mailbox
        )
        if client is not None:
            threading.Thread(
                target=VoiceOwnerLease.detach,
                args=(client, owner, purging),
                name='metor-gui-detach',
                daemon=True,
            ).start()
