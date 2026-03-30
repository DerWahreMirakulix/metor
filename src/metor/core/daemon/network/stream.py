"""
Module providing strict TCP stream framing and fragmentation resilience.
Mitigates Out-Of-Memory (OOM) DoS attacks by enforcing buffer limits on incoming streams,
and prevents Unicode decoding crashes (UTF-8 DoS).
"""

import socket
from typing import Optional


class TcpStreamReader:
    """Reads from a socket safely, enforcing a maximum buffer size."""

    def __init__(
        self, conn: socket.socket, initial_buffer: str = '', max_bytes: int = 1048576
    ) -> None:
        """
        Initializes the stream reader with OPSEC constraints.

        Args:
            conn (socket.socket): The active socket connection.
            initial_buffer (str): Any leftover string buffer from previous reads.
            max_bytes (int): The absolute maximum allowed buffer size in bytes (Default: 1MB).

        Returns:
            None
        """
        self._conn: socket.socket = conn
        self._buffer: str = initial_buffer
        self._max_bytes: int = max_bytes

    def read_line(self) -> Optional[str]:
        """
        Reads from the socket until a newline delimiter is encountered or the connection drops.
        Strictly bounds the buffer size to prevent OOM DoS attacks and ignores decode errors.

        Args:
            None

        Raises:
            MemoryError: If the incoming payload exceeds the maximum buffer size without a delimiter.
            ConnectionError: If the socket drops unexpectedly.
            socket.timeout: If the read operation times out.

        Returns:
            Optional[str]: The parsed line without the newline character, or None if disconnected safely.
        """
        while '\n' not in self._buffer:
            if len(self._buffer.encode('utf-8')) > self._max_bytes:
                raise MemoryError(
                    'Maximum TCP stream buffer size exceeded. Possible DoS attack.'
                )

            try:
                data: bytes = self._conn.recv(4096)
                if not data:
                    return None

                # Critical OPSEC fix: Ignore malformed UTF-8 fragments to prevent daemon crash
                self._buffer += data.decode('utf-8', errors='ignore')
            except socket.timeout:
                raise
            except Exception as e:
                raise ConnectionError(f'Socket error: {str(e)}')

        line, self._buffer = self._buffer.split('\n', 1)
        return line.strip()

    def get_buffer(self) -> str:
        """
        Returns the remaining unparsed buffer for downstream handover.

        Args:
            None

        Returns:
            str: The remaining string buffer.
        """
        return self._buffer
