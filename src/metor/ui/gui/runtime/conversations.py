"""Root conversation membership from public Core facts and bounded local LIVE presentation."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metor.core.api import Delivery

if TYPE_CHECKING:
    from .controller import GuiController


@dataclass(frozen=True)
class ConversationRow:
    """One content-free root row with an immutable canonical navigation target."""

    peer: str
    label: str
    delivery: Delivery
    status: str
    unseen: int = 0
    pending: int = 0
    pinned: bool = False
    local_only: bool = False


def conversation_rows(
    controller: 'GuiController', delivery: Delivery
) -> list[ConversationRow]:
    """Preserves Core membership and ordering while applying only GUI-owned pin/local retention.

    Args:
        controller: Current authorized public state and bounded presentation owners.
        delivery: Explicit root projection, independent of any foreground peer.
    Returns:
        list[ConversationRow]: Stable canonical targets with no message preview or guessed presence.
    """
    state = controller.state
    snapshot = state.snapshot
    if state.covered or snapshot is None:
        return []
    if delivery is Delivery.DROP:
        pins = state.preferences.preferences.pins if state.preferences else []
        pinned = {peer: index for index, peer in enumerate(pins)}
        indexed = list(enumerate(snapshot.conversations))
        indexed.sort(
            key=lambda pair: (
                (0, pinned[pair[1].onion]) if pair[1].onion in pinned else (1, pair[0])
            )
        )
        return [
            ConversationRow(
                entry.onion,
                entry.alias,
                Delivery.DROP,
                'Drop conversation',
                unseen=entry.unread_count,
                pending=entry.pending_count,
                pinned=entry.onion in pinned,
            )
            for _index, entry in indexed
        ]
    rows: list[ConversationRow] = []
    canonical = {item.onion for item in snapshot.live_contexts}
    ordered = list(enumerate(snapshot.live_contexts))
    ordered.sort(
        key=lambda pair: (
            0
            if pair[1].session_state == 'connected' or pair[1].recovery_eligible
            else 1,
            0 if pair[1].pending_outbound_count or pair[1].unseen_count else 1,
            pair[0],
        )
    )
    for _index, entry in ordered:
        status = (
            'Connected'
            if entry.session_state == 'connected'
            else 'Reconnecting…'
            if entry.recovery_eligible
            else 'Calling…'
            if entry.session_state == 'connecting'
            else 'Incoming Live'
            if entry.session_state == 'pending'
            else 'Disconnected'
        )
        rows.append(
            ConversationRow(
                entry.onion,
                entry.alias,
                Delivery.LIVE,
                status,
                entry.unseen_count,
                entry.pending_outbound_count,
            )
        )
    local: dict[str, int] = {}
    for item in controller.transcript.items.values():
        if item.delivery is Delivery.LIVE and item.peer not in canonical:
            local[item.peer] = max(local.get(item.peer, 0), item.order)
    for turn in controller.voice.live_turns.values():
        if turn.actual_delivery is Delivery.LIVE and turn.binding.peer not in canonical:
            local[turn.binding.peer] = max(local.get(turn.binding.peer, 0), turn.order)
    rows.extend(
        ConversationRow(
            peer,
            controller.contacts.alias(peer),
            Delivery.LIVE,
            'Local conversation · Disconnected',
            local_only=True,
        )
        for peer in sorted(local, key=lambda peer: (-local[peer], peer))
    )
    return rows
