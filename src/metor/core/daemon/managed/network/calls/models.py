"""Bounded in-memory call ownership and fresh media-frame state."""

import socket
import time
from collections import deque
from dataclasses import dataclass, field

from metor.core.api import CallAudioFrame, CallInfo
from metor.shared.constants import Constants


@dataclass
class CallSession:
    """One call; no durable payload, recording, or automatic recovery ownership."""

    info: CallInfo
    wire_id: str = ''
    owner: socket.socket | None = None
    connection: socket.socket | None = None
    borrowed: bool = False
    deadline: float = field(
        default_factory=lambda: time.monotonic() + Constants.CALL_RING_TIMEOUT_SEC
    )
    last_peer: float = field(default_factory=time.monotonic)
    last_ping: float = field(default_factory=time.monotonic)
    sent_sequence: int = -1
    received_sequence: int = -1
    pending_writes: int = 0
    local_epoch: float = field(default_factory=time.monotonic)
    peer_clock_offset: float | None = None
    frames: deque[tuple[float, CallAudioFrame]] = field(
        default_factory=lambda: deque(maxlen=Constants.CALL_AUDIO_MAX_FRAMES)
    )

    def __post_init__(self) -> None:
        """Binds outgoing local identity to its wire identity unless explicitly separated."""
        if not self.wire_id:
            self.wire_id = self.info.call_id

    def tick(self) -> int:
        """Projects elapsed call time without wall-clock or uptime disclosure."""
        return int(
            (time.monotonic() - self.local_epoch) * Constants.CALL_TIMESTAMP_SCALE
        )

    def observe_clock(self, tick: int) -> None:
        """Tracks minimum relative delay without requiring synchronized clocks."""
        sample = time.monotonic() - tick / Constants.CALL_TIMESTAMP_SCALE
        self.peer_clock_offset = (
            sample
            if self.peer_clock_offset is None
            else min(self.peer_clock_offset, sample)
        )
