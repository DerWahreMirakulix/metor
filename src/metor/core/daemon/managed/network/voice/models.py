"""In-memory logical Voice transfer state."""

from dataclasses import dataclass
from typing import Optional

from metor.core.api import Delivery


@dataclass
class VoiceTurn:
    """Tracks one peer-bound logical Voice turn and its resume position."""

    alias: str
    onion: str
    msg_id: str
    delivery: Delivery
    codec: str
    blob_id: str
    chunk_ids: list[str]
    data: bytearray
    timestamp: str
    acknowledged_offset: int = 0
    duration_ms: Optional[int] = None
    finalized: bool = False
    pressure_emitted: bool = False
