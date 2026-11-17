"""Module providing buffered newline-delimited IPC event framing for clients."""

import json
import socket
import time
from typing import Dict, Optional

from metor.core.api import IpcEvent, JsonValue
from metor.shared import Constants, recv_before


class BufferedIpcEventReader:
    """Reads strict newline-delimited IPC events with one persistent byte buffer."""

    def __init__(self) -> None:
        """
        Initializes the buffer-backed IPC event reader.

        Args:
            None

        Returns:
            None
        """
        self._buffer: bytearray = bytearray()

    def reset(self) -> None:
        """
        Clears the current buffered IPC bytes.

        Args:
            None

        Returns:
            None
        """
        self._buffer = bytearray()

    @staticmethod
    def _decode_event_line(line_bytes: bytes | bytearray) -> IpcEvent:
        """
        Decodes one newline-delimited event payload into a typed DTO.

        Args:
            line_bytes (bytes | bytearray): The raw event bytes without trailing newline.

        Returns:
            IpcEvent: The decoded typed event.
        """
        line: str = line_bytes.decode('utf-8').strip()
        event_dict: Dict[str, JsonValue] = json.loads(line)
        if not isinstance(event_dict, dict):
            raise TypeError('An IPC event must be an object.')
        return IpcEvent.from_dict(event_dict)

    def append_bytes(self, data: bytes) -> None:
        """
        Appends raw socket bytes and enforces the IPC byte cap.

        Args:
            data (bytes): The raw socket bytes.

        Raises:
            ValueError: If the buffered payload exceeds the IPC size limit.

        Returns:
            None
        """
        self._buffer.extend(data)
        if len(self._buffer) <= Constants.MAX_IPC_BYTES:
            return

        frame_start: int = 0
        while True:
            frame_end: int = self._buffer.find(b'\n', frame_start)
            if frame_end < 0:
                if len(self._buffer) - frame_start > Constants.MAX_IPC_BYTES:
                    raise ValueError('Daemon response exceeded the IPC size limit.')
                return
            if frame_end - frame_start + 1 > Constants.MAX_IPC_BYTES:
                raise ValueError('Daemon response exceeded the IPC size limit.')
            frame_start = frame_end + 1

    def pop_event(self) -> Optional[IpcEvent]:
        """
        Parses one already-buffered event when a full line is available.

        Args:
            None

        Returns:
            Optional[IpcEvent]: The decoded event, or None if the buffer is incomplete.
        """
        while b'\n' in self._buffer:
            line_bytes, _, rest = self._buffer.partition(b'\n')
            self._buffer = bytearray(rest)
            if not line_bytes.strip():
                continue
            return self._decode_event_line(line_bytes)

        return None

    def read_from_socket(
        self, sock: socket.socket, *, deadline: float | None = None
    ) -> Optional[IpcEvent]:
        """
        Reads one complete IPC event from a connected socket.

        Args:
            sock (socket.socket): The connected IPC socket.
            deadline: Optional monotonic deadline for the whole operation, including fragmented frames.

        Returns:
            Optional[IpcEvent]: The decoded event, or None when the stream ends.
        """
        if deadline is not None and time.monotonic() >= deadline:
            raise socket.timeout('IPC operation deadline elapsed.')
        while True:
            try:
                buffered_event = self.pop_event()
            except (ValueError, TypeError, RecursionError):
                # Invalid enum values, fields and JSON can contain private peer data.
                raise ValueError('The daemon sent an invalid IPC event.') from None
            if buffered_event is not None:
                return buffered_event
            data = recv_before(sock, Constants.TCP_BUFFER_SIZE, deadline)
            if not data:
                return None
            self.append_bytes(data)
