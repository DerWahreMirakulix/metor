"""Exact-owner bounded real-time PCM admission; no conversation recording."""

import base64
import binascii
import socket
import time
from typing import TYPE_CHECKING

from metor.core.api import (
    CallAudioEvent,
    CallAudioFrame,
    CallAudioSentEvent,
    CallReason,
    CallRejectedEvent,
    CallState,
)
from metor.core.daemon.managed.models import TorCommand
from metor.shared.constants import Constants

# Local Package Imports
from .models import CallSession

if TYPE_CHECKING:
    from .controller import CallController


def decode_frame(data: str) -> bytes | None:
    """Validates one codec frame before allocation or peer forwarding."""
    if len(data) > ((Constants.CALL_FRAME_BYTES + 2) // 3) * 4:
        return None
    try:
        decoded = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error):
        return None
    return decoded if len(decoded) == Constants.CALL_FRAME_BYTES else None


def send_audio(
    controller: 'CallController',
    call_id: str,
    client: socket.socket,
    sequence: int,
    data: str,
) -> CallAudioSentEvent | CallRejectedEvent:
    """Admits fresh media only after explicit acceptance, with bounded writer ownership."""
    if (
        decode_frame(data) is None
        or not 0 <= sequence <= Constants.CALL_FRAME_SEQUENCE_MAX
    ):
        return CallRejectedEvent(call_id=call_id, reason=CallReason.MALFORMED)
    with controller.lock:
        if not controller.is_owned_active(call_id, client):
            return CallRejectedEvent(call_id=call_id, reason=CallReason.NOT_OWNER)
        session = controller.sessions[call_id]
        if sequence <= session.sent_sequence:
            return CallRejectedEvent(call_id=call_id, reason=CallReason.INVALID_STATE)
        session.sent_sequence = sequence
        if (
            session.info.muted
            or session.pending_writes >= Constants.CALL_AUDIO_MAX_FRAMES
        ):
            return CallAudioSentEvent(call_id=call_id, next_sequence=sequence + 1)
        session.pending_writes += 1
        deadline = time.monotonic() + Constants.CALL_AUDIO_EXPIRY_SEC

    def claim() -> bool:
        """Drops expired queued audio and revokes stale/muted call frames before writing."""
        with controller.lock:
            session.pending_writes = max(0, session.pending_writes - 1)
            return (
                session.info.state is CallState.ACTIVE
                and not session.info.muted
                and time.monotonic() < deadline
            )

    if not controller.send(
        session,
        f'{TorCommand.CALL_AUDIO.value} {session.wire_id} {sequence} {session.tick()} {data}\n',
        claim,
    ):
        return CallRejectedEvent(call_id=call_id, reason=CallReason.TRANSPORT_LOST)
    return CallAudioSentEvent(call_id=call_id, next_sequence=sequence + 1)


def receive_audio(session: CallSession, sequence: int, tick: int, data: str) -> bool:
    """Stores only fresh bounded accepted PCM, without persistence or replay ACKs."""
    if (
        session.info.state is not CallState.ACTIVE
        or decode_frame(data) is None
        or not session.received_sequence < sequence <= Constants.CALL_FRAME_SEQUENCE_MAX
    ):
        return False
    session.received_sequence = sequence
    now = time.monotonic()
    if session.peer_clock_offset is None:
        return False
    age = now - session.peer_clock_offset - tick / Constants.CALL_TIMESTAMP_SCALE
    if age > Constants.CALL_AUDIO_EXPIRY_SEC:
        return True
    session.frames.append((now, CallAudioFrame(sequence=sequence, data=data)))
    return True


def read_audio(
    controller: 'CallController', call_id: str, client: socket.socket, max_frames: int
) -> CallAudioEvent | CallRejectedEvent:
    """Consumes fresh audio once and bounds one IPC result independently of caller input."""
    if not 1 <= max_frames <= Constants.CALL_AUDIO_MAX_FRAMES:
        return CallRejectedEvent(call_id=call_id, reason=CallReason.MALFORMED)
    with controller.lock:
        if not controller.is_owned_active(call_id, client):
            return CallRejectedEvent(call_id=call_id, reason=CallReason.NOT_OWNER)
        session = controller.sessions[call_id]
        now = time.monotonic()
        while (
            session.frames
            and now - session.frames[0][0] >= Constants.CALL_AUDIO_EXPIRY_SEC
        ):
            session.frames.popleft()
        frames = [
            session.frames.popleft()[1]
            for _ in range(min(max_frames, len(session.frames)))
        ]
        return CallAudioEvent(call_id=call_id, frames=frames)
