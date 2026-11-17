"""Exact complete-source eligibility for explicit delivered-own-LIVE resend."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from metor.core.api import Delivery, MessageDirectionCode, MessageStatusCode
from metor.ui.gui.platform.audio import PcmVoice
from metor.ui.gui.state.media import PlaybackTarget

if TYPE_CHECKING:
    from ..controller import GuiController


@dataclass(frozen=True, repr=False)
class ResendSource:
    """One current-runtime complete source; no remote fetch or persistent shadow copy."""

    target: PlaybackTarget
    text: str | None = None
    size: int = 0


def available_source(
    controller: 'GuiController', peer: str, msg_id: str
) -> ResendSource | None:
    """Requires own delivered LIVE metadata plus all source text or encoded bytes.

    Args:
        controller: Current authorized presentation and bounded cache owner.
        peer: Original canonical source peer.
        msg_id: Original LIVE identity, never reused for the new DROP.
    Returns:
        ResendSource | None: Complete permitted source or unavailable eligibility.
    """
    if controller.state.covered:
        return None
    target = controller.playback.target(
        peer, Delivery.LIVE, MessageDirectionCode.OUT, msg_id
    )
    if target is None:
        return None
    item = controller.transcript.items.get(
        (peer, Delivery.LIVE, MessageDirectionCode.OUT, msg_id)
    )
    delivered = {MessageStatusCode.DELIVERED, MessageStatusCode.READ}
    if item is not None and item.status in delivered and item.finalized:
        if item.text is not None:
            return ResendSource(target, text=item.text)
        if item.codec != PcmVoice.CODEC:
            return None
        size = item.size_bytes
    else:
        turn = controller.voice.live_turns.get(msg_id)
        if (
            turn is None
            or turn.binding.peer != peer
            or turn.binding.generation != controller.state.generation
            or turn.actual_delivery is not Delivery.LIVE
            or turn.status not in delivered
            or not turn.finalized
        ):
            return None
        size = turn.size_bytes
    if (
        size > 0
        and size % PcmVoice.SAMPLE_BYTES == 0
        and controller.playback.cache.complete_size(target) == size
    ):
        return ResendSource(target, size=size)
    return None
