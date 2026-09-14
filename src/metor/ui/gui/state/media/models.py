"""Exact media identities and bounded local playback progress records."""

from dataclasses import dataclass

from metor.core.api import Delivery, MessageDirectionCode


@dataclass(frozen=True)
class PlaybackTarget:
    """Exact activation-qualified media identity independent of mutable view labels."""

    generation: int
    profile_instance: str
    epoch: str
    peer: str
    delivery: Delivery
    direction: MessageDirectionCode
    msg_id: str
    owner_token: str | None = None


@dataclass(frozen=True)
class PlaybackProgress:
    """Local output facts, never a fabricated Core delivery or read event."""

    target: PlaybackTarget
    serial: int
    position: int = 0
    available: int = 0
    finalized: bool = False
    state: str = 'buffering'
