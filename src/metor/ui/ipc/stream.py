"""Shared UI-side newline-delimited IPC event framing helpers."""

import json
import socket
from typing import Dict, Optional

from metor.core.api import IpcEvent, JsonValue
from metor.utils import Constants


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
            line_bytes (bytes | bytearray): The raw event bytes without the trailing newline.

        Returns:
            IpcEvent: The decoded typed event.
        """
        line: str = line_bytes.decode('utf-8').strip()
        event_dict: Dict[str, JsonValue] = json.loads(line)
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
        if len(self._buffer) > Constants.MAX_IPC_BYTES:
            raise ValueError('Daemon response exceeded the IPC size limit.')

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

    def read_from_socket(self, sock: socket.socket) -> Optional[IpcEvent]:
        """
        Reads one complete IPC event from a connected socket.

        Args:
            sock (socket.socket): The connected IPC socket.

        Returns:
            Optional[IpcEvent]: The decoded event, or None when the stream ends.
        """
        while True:
            buffered_event: Optional[IpcEvent] = self.pop_event()
            if buffered_event is not None:
                return buffered_event

            data: bytes = sock.recv(Constants.TCP_BUFFER_SIZE)
            if not data:
                return None

            self.append_bytes(data)
