"""Exact-handle invitation selection, explicit navigation and normal unlock continuation."""

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from metor.core.api import (
    AcceptCommand,
    RejectCommand,
    IpcEvent,
    IncomingConnectionEvent,
    PendingConnectionExpiredEvent,
    ConnectedEvent,
    ConnectionRejectedEvent,
    ClientAccessRestrictedEvent,
    Delivery,
    ConnectionOrigin,
    PendingConnectionReasonCode,
)
from metor.ui.gui.constants import GuiLimits
from metor.ui.gui.state import Route
from metor.ui.gui.state.mailbox import Update

if TYPE_CHECKING:
    from ..controller import GuiController

InvitationAction = Literal['accept', 'decline', 'open']


def _safe_label(label: str) -> str:
    """Bounds no-preview labels without retaining oversized event text.

    Args:
        label: Public display label.
    Returns:
        str: Permitted bounded label or a generic event kind.
    """
    return (
        label
        if len(label.encode('utf-8')) <= GuiLimits.DEVICE_STRING
        else 'Live chat invitation'
    )


@dataclass
class InvitationNotice:
    """Permitted metadata for one request; its handle never changes under a press."""

    handle: str
    peer: str | None
    label: str
    phase: str = 'pending'
    denied: bool = False
    status: str = ''


class LiveInvitations:
    """Owns bounded invitation presentation; Core decides every action and privacy grant."""

    def __init__(self, controller: 'GuiController') -> None:
        """Creates an empty per-activation invitation presentation.

        Args:
            controller: Owning public-service GUI controller.
        Returns:
            None
        """
        self.controller = controller
        self.entries: OrderedDict[str, InvitationNotice] = OrderedDict()
        self.selected: str | None = None
        self.visible = False
        self.revision = 0
        self._snapshot: object = None
        self._operation: tuple[str, str, InvitationAction, Route] | None = None
        self._opening: tuple[str, Route] | None = None
        self._serial = 0

    def clear(self) -> None:
        """Drops all prior authorized presentation before a new privacy cycle.

        Args:
            None
        Returns:
            None
        """
        self.entries.clear()
        self.selected = None
        self.visible = False
        self._snapshot = None
        self._opening = None
        self._operation = None
        self.revision += 1

    def _add(
        self, handle: str, peer: str | None, label: str, *, notify: bool = True
    ) -> None:
        """Admits one content-free request while keeping the selected target stable.

        Args:
            handle: Exact public per-session authority.
            peer: Permitted public identity, absent when anonymized.
            label: Permitted no-preview display label.
            notify: Whether a fresh request warrants unsolicited presentation.
        Returns:
            None
        """
        if len(handle.encode('utf-8')) > GuiLimits.DEVICE_STRING:
            return
        label = _safe_label(label)
        if handle in self.entries:
            return
        if len(self.entries) >= GuiLimits.NOTIFICATIONS:
            victim = next((key for key in self.entries if key != self.selected), None)
            if victim is None:
                return
            self.entries.pop(victim)
        self.entries[handle] = InvitationNotice(handle, peer, label)
        if self.selected is None or self.entries[self.selected].phase == 'ended':
            self.selected = handle
        if notify:
            self.visible = True
        self.revision += 1

    def observe(self, event: IpcEvent) -> None:
        """Installs only permitted metadata; unsolicited invitations never navigate or focus.

        Args:
            event: Current activation's public Core event.
        Returns:
            None
        """
        state = self.controller.state
        if state.covered:
            return
        if isinstance(event, IncomingConnectionEvent) and event.action_handle:
            self._add(
                event.action_handle,
                event.onion,
                event.alias,
                notify=event.origin
                not in {
                    ConnectionOrigin.AUTO_RECONNECT,
                    ConnectionOrigin.GRACE_RECONNECT,
                    ConnectionOrigin.RETUNNEL,
                },
            )
        elif isinstance(event, PendingConnectionExpiredEvent) and event.action_handle:
            entry = self.entries.get(event.action_handle)
            if entry is not None:
                entry.phase, entry.status = 'ended', 'Request ended'
                self.revision += 1

    def show(self, handle: str | None = None) -> None:
        """Explicitly opens a selected current invitation surface without accepting it.

        Args:
            handle: Optional exact entry chosen from another authorized view.
        Returns:
            None
        """
        if handle in self.entries:
            self.selected = handle
        elif handle is None and (
            self.selected is None
            or self.selected not in self.entries
            or self.entries[self.selected].phase == 'ended'
        ):
            self.selected = next(
                (key for key, entry in self.entries.items() if entry.phase != 'ended'),
                self.selected,
            )
        self.visible = (
            self.selected is not None
            and self.selected in self.entries
            and self.entries[self.selected].phase != 'ended'
        )
        self.revision += 1

    def dismiss(self) -> None:
        """Closes presentation while preserving discoverable current invitation facts.

        Args:
            None
        Returns:
            None
        """
        self.visible = False
        self.revision += 1

    def step(self, delta: int) -> None:
        """Selects another request only through an explicit Previous/Next action.

        Args:
            delta: Signed selection displacement.
        Returns:
            None
        """
        handles = [key for key, entry in self.entries.items() if entry.phase != 'ended']
        if self.selected in handles:
            self.selected = handles[
                (handles.index(self.selected) + delta) % len(handles)
            ]
            self.revision += 1

    def perform(self, handle: str, action: InvitationAction) -> bool:
        """Admits an exact invitation action or its configured normal unlock continuation.

        Args:
            handle: Handle captured when the action control was built.
            action: Explicit Accept, Decline or Open intent.
        Returns:
            bool: Whether the intent was admitted.
        """
        controller, state = self.controller, self.controller.state
        entry = self.entries.get(handle)
        if entry is None or entry.phase == 'ended' or self._operation is not None:
            return False
        if state.covered:
            return False
        if action == 'open' and entry.phase == 'accepted':
            self._opening = (handle, state.route)
            controller.refresh_state()
            return True
        if entry.phase != 'pending' or controller.client is None:
            return False
        self._serial += 1
        operation = f'live-invitation:{self._serial}'
        client = controller.client
        command = (
            RejectCommand(entry.peer or handle, handle)
            if action == 'decline'
            else AcceptCommand(entry.peer or handle, handle)
        )
        if controller.submit(operation, lambda: client.request(command, IpcEvent)):
            self._operation = (operation, handle, action, state.route)
            entry.status = 'Declining…' if action == 'decline' else 'Accepting…'
            self.revision += 1
            return True
        return False

    def install(self, update: Update) -> bool:
        """Installs one correlated result without accepting a replacement request.

        Args:
            update: Current activation's public request outcome.
        Returns:
            bool: Whether this flow consumed the operation result.
        """
        if not update.operation.startswith('live-invitation:'):
            return False
        operation, self._operation = self._operation, None
        if operation is None or operation[0] != update.operation:
            return True
        _, handle, action, origin = operation
        entry = self.entries.get(handle)
        if entry is None:
            return True
        event = update.event
        if isinstance(event, ClientAccessRestrictedEvent):
            entry.denied, entry.status = True, 'Unlock to accept'
        elif isinstance(event, ConnectedEvent):
            entry.phase, entry.status = 'accepted', 'Live accepted'
            if action == 'open':
                self._opening = (handle, origin)
        elif isinstance(event, ConnectionRejectedEvent):
            entry.phase, entry.status = 'ended', 'Request ended'
        else:
            entry.status = 'Checking request…' if event is None else 'Request ended'
            entry.phase = 'checking' if event is None else 'ended'
            if action == 'open' and event is None:
                self._opening = (handle, origin)
        if not self.controller.state.covered:
            self.controller.refresh_state()
        self.revision += 1
        return True

    def _facts(self) -> tuple[tuple[object, ...], ...]:
        """Captures bounded visible facts to preserve controls on unchanged refreshes.

        Args:
            None
        Returns:
            tuple[tuple[object, ...], ...]: Current no-preview entry facts.
        """
        return tuple(
            (
                entry.handle,
                entry.peer,
                entry.label,
                entry.phase,
                entry.denied,
                entry.status,
            )
            for entry in self.entries.values()
        )

    def poll(self) -> bool:
        """Revalidates exact requests after unlock or an unknown outcome before navigation.

        Args:
            None
        Returns:
            bool: Whether the invitation surface changed.
        """
        controller, state = self.controller, self.controller.state
        snapshot = state.snapshot
        before = self.revision
        prior_facts = self._facts()
        if state.covered or snapshot is None or snapshot is self._snapshot:
            return False
        self._snapshot = snapshot
        pending = {
            entry.action_handle: entry
            for entry in snapshot.pending
            if entry.action_handle
        }
        accepted = {
            entry.invitation_handle: entry
            for entry in snapshot.live_contexts
            if entry.invitation_handle
        }
        for handle, source in pending.items():
            assert handle is not None
            self._add(
                handle,
                source.onion,
                source.alias,
                notify=source.reason is PendingConnectionReasonCode.USER_ACCEPT
                and source.origin
                not in {
                    ConnectionOrigin.AUTO_RECONNECT,
                    ConnectionOrigin.GRACE_RECONNECT,
                    ConnectionOrigin.RETUNNEL,
                },
            )
        for handle, entry in self.entries.items():
            if handle in pending:
                source = pending[handle]
                entry.peer, entry.label = source.onion, _safe_label(source.alias)
                entry.phase = 'pending'
            elif handle in accepted:
                live = accepted[handle]
                entry.peer, entry.label, entry.phase = (
                    live.onion,
                    _safe_label(live.alias),
                    'accepted',
                )
            else:
                entry.phase, entry.status = 'ended', 'Request ended'
        if self._opening is not None:
            handle, origin = self._opening
            opened = accepted.get(handle)
            if opened is not None:
                self._opening = None
                if state.route == origin:
                    controller.navigate(Route('V09', opened.onion, Delivery.LIVE))
                    self.dismiss()
            elif handle not in pending:
                self._opening = None
                state.status = 'Request ended'
        if self._facts() != prior_facts:
            self.revision += 1
        if (
            self.selected is not None
            and self.selected in self.entries
            and self.entries[self.selected].phase == 'ended'
        ):
            current = next(
                (key for key, entry in self.entries.items() if entry.phase != 'ended'),
                None,
            )
            self.selected = current
            if current is None:
                self.visible = False
        return before != self.revision
