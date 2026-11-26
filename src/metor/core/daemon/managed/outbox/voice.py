"""Resumable Voice Drop frames shared by direct, cached and Live transports."""

import base64
import json
import socket
from typing import Callable, Protocol

from metor.core.api import JsonValue
from metor.core.daemon.managed.models import TorCommand
from metor.data.blob import BlobLifecycle, BlobStore

# Local Package Imports
from ..network import StateTracker


class DropResponseReader(Protocol):
    """Reads responses from either an owned tunnel or a receiver-fed mailbox."""

    def read_line(self) -> str | None:
        """Returns one response frame or None when the attempt ends."""
        ...


class DropDeliveryCancelled(ConnectionError):
    """Signals revoked durable eligibility without reporting transport failure."""


def is_expected_voice_commit_line(msg_id: str, ack_line: str | None) -> bool:
    """Validates durable Voice completion against the exact message identity."""
    if ack_line is None:
        return False
    parts = ack_line.strip().split()
    return (
        len(parts) == 2
        and parts[0] == TorCommand.VOICE_COMMIT_ACK.value
        and parts[1] == msg_id
    )


class VoiceDropSender:
    """Sends bounded retained chunks without taking ownership of Live reads."""

    def __init__(self, state: StateTracker, blobs: BlobStore | None) -> None:
        """Binds daemon emission and retained encrypted payload ownership."""
        self._state = state
        self._blobs = blobs

    def send(
        self,
        conn: socket.socket,
        stream: DropResponseReader,
        payload: str,
        msg_id: str,
        timestamp: str,
        claim: Callable[[], bool] | None = None,
    ) -> str | None:
        """Sends a resumable Voice Drop, leaving the terminal response unread.

        A committed replay returns its early terminal ACK. Otherwise each chunk
        waits for its correlated exact-offset ACK before another chunk is queued.
        Raises on invalid metadata, lost response ownership or invalid offsets.
        """
        if self._blobs is None:
            raise ValueError('Voice DROP storage is unavailable.')
        metadata = json.loads(payload)
        if not isinstance(metadata, dict):
            raise ValueError('Invalid Voice DROP metadata.')
        codec = str(metadata['codec'])
        chunk_ids = metadata.get('chunk_ids')
        size_bytes = metadata.get('size_bytes')
        if (
            not isinstance(chunk_ids, list)
            or any(not isinstance(chunk_id, str) for chunk_id in chunk_ids)
            or type(size_bytes) is not int
            or size_bytes < 0
        ):
            raise ValueError('Invalid segmented Voice DROP metadata.')
        self._send_frame(
            conn,
            TorCommand.DROP_VOICE_BEGIN,
            {'id': msg_id, 'codec': codec, 'timestamp': timestamp},
            claim,
        )
        resume_line = stream.read_line()
        if is_expected_voice_commit_line(msg_id, resume_line) or (
            resume_line is not None
            and resume_line.strip().startswith(TorCommand.REJECT.value)
        ):
            return resume_line
        offset = self._parse_offset(msg_id, resume_line, size_bytes)
        stored_offset = 0
        for chunk_id in chunk_ids:
            chunk = self._blobs.read(chunk_id, BlobLifecycle.PERSISTENT)
            chunk_end = stored_offset + len(chunk)
            if offset >= chunk_end:
                stored_offset = chunk_end
                continue
            if offset < stored_offset:
                raise ConnectionError('Voice DROP resume offset is not contiguous.')
            chunk = chunk[offset - stored_offset :]
            self._send_frame(
                conn,
                TorCommand.DROP_VOICE_CHUNK,
                {
                    'id': msg_id,
                    'offset': offset,
                    'data': base64.b64encode(chunk).decode('ascii'),
                },
                claim,
            )
            response = stream.read_line()
            if response is not None and response.strip().startswith(
                TorCommand.REJECT.value
            ):
                return response
            offset = self._parse_offset(msg_id, response, chunk_end)
            if offset != chunk_end:
                raise ConnectionError('Voice DROP acknowledgement offset is not exact.')
            stored_offset = chunk_end
        if offset != size_bytes:
            raise ConnectionError('Voice DROP retained size does not match metadata.')
        self._send_frame(
            conn,
            TorCommand.DROP_VOICE_END,
            {
                'id': msg_id,
                'size': size_bytes,
                'duration_ms': metadata.get('duration_ms'),
            },
            claim,
        )
        return None

    def _send_frame(
        self,
        conn: socket.socket,
        command: TorCommand,
        payload: dict[str, JsonValue],
        claim: Callable[[], bool] | None,
    ) -> None:
        """Queues one complete frame under its exact transport lease."""
        if claim is not None and not claim():
            raise DropDeliveryCancelled('Voice Drop delivery was cancelled.')
        encoded = base64.b64encode(
            json.dumps(payload, separators=(',', ':')).encode('utf-8')
        ).decode('ascii')
        self._state.send_frame(
            conn, f'{command.value} {encoded}\n'.encode('ascii'), claim
        )

    @staticmethod
    def _parse_offset(msg_id: str, line: str | None, maximum: int) -> int:
        """Validates one exact identity and bounded contiguous resume offset."""
        if line is None:
            raise ConnectionError('Voice DROP acknowledgement missing.')
        parts = line.split()
        if (
            len(parts) != 3
            or parts[0] != TorCommand.VOICE_ACK.value
            or parts[1] != msg_id
        ):
            raise ConnectionError('Voice DROP acknowledgement invalid.')
        offset = int(parts[2])
        if offset < 0 or offset > maximum:
            raise ConnectionError('Voice DROP acknowledgement offset invalid.')
        return offset
