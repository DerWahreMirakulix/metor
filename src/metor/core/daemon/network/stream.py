"""
Module providing strict TCP stream framing and fragmentation resilience.
Mitigates Out-Of-Memory (OOM) DoS attacks by enforcing buffer limits on incoming streams,
and prevents Unicode decoding crashes (UTF-8 DoS) by parsing binary data before decoding.
"""

import socket
from typing import Optional

from metor.utils import Constants


class TcpStreamReader:
    """Reads from a socket safely, enforcing a maximum buffer size."""

    def __init__(
        self,
        conn: socket.socket,
        initial_buffer: str = '',
        max_bytes: int = Constants.MAX_STREAM_BYTES,
    ) -> None:
        """
        Initializes the stream reader with OPSEC constraints.

        Args:
            conn (socket.socket): The active socket connection.
            initial_buffer (str): Any leftover string buffer from previous reads.
            max_bytes (int): The absolute maximum allowed buffer size in bytes.

        Returns:
            None
        """
        self._conn: socket.socket = conn
        self._buffer: bytearray = bytearray(initial_buffer.encode('utf-8'))
        self._max_bytes: int = max_bytes

    def read_line(self) -> Optional[str]:
        """
        Reads from the socket until a newline delimiter is encountered or the connection drops.
        Strictly bounds the buffer size to prevent OOM DoS attacks and buffers bytes to prevent UTF-8 fragmentation.

        Args:
            None

        Raises:
            MemoryError: If the incoming payload exceeds the maximum buffer size without a delimiter.
            ConnectionError: If the socket drops unexpectedly.
            socket.timeout: If the read operation times out.

        Returns:
            Optional[str]: The parsed line without the newline character, or None if disconnected safely.
        """
        while b'\n' not in self._buffer:
            if len(self._buffer) > self._max_bytes:
                raise MemoryError(
                    'Maximum TCP stream buffer size exceeded. Possible DoS attack.'
                )

            try:
                data: bytes = self._conn.recv(Constants.TCP_BUFFER_SIZE)
                if not data:
                    return None

                self._buffer.extend(data)
            except socket.timeout:
                raise
            except Exception as e:
                raise ConnectionError(f'Socket error: {str(e)}')

        line_bytes, _, rest = self._buffer.partition(b'\n')
        self._buffer = bytearray(rest)

        return line_bytes.decode('utf-8', errors='ignore').strip()

    def get_buffer(self) -> str:
        """
        Returns the remaining unparsed buffer for downstream handover.

        Args:
            None

        Returns:
            str: The remaining string buffer.
        """
        return self._buffer.decode('utf-8', errors='ignore')
