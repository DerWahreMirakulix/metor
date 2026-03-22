"""
Module managing the outbound IPC socket connection to the local Daemon.
Isolates all raw TCP byte parsing from the Chat Engine logic.
"""

import socket
import threading
import json
from typing import Callable, Dict, Any, Optional

from metor.core.api import IpcCommand, IpcEvent
from metor.utils.constants import Constants


class IpcClient:
    """Handles the raw TCP socket connection to the background Daemon."""

    def __init__(
        self,
        port: int,
        on_event: Callable[[IpcEvent], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        """
        Initializes the IPC Client.

        Args:
            port (int): The local localhost port the Daemon is listening on.
            on_event (Callable[[IpcEvent], None]): Callback fired when a valid event arrives.
            on_disconnect (Callable[[], None]): Callback fired if the connection drops.
        """
        self._port: int = port
        self._on_event: Callable[[IpcEvent], None] = on_event
        self._on_disconnect: Callable[[], None] = on_disconnect

        self._socket: Optional[socket.socket] = None
        self._stop_flag: threading.Event = threading.Event()

    def connect(self) -> bool:
        """
        Attempts to establish a connection to the Daemon.

        Returns:
            bool: True if connection is successful, False otherwise.
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.connect((Constants.LOCALHOST, self._port))
            threading.Thread(target=self._listener_thread, daemon=True).start()
            return True
        except Exception:
            return False

    def stop(self) -> None:
        """Safely shuts down the background listener and closes the socket."""
        self._stop_flag.set()
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass

    def send_command(self, cmd: IpcCommand) -> None:
        """
        Serializes and pushes a strictly typed command to the Daemon.

        Args:
            cmd (IpcCommand): The DTO payload to send.
        """
        if not self._socket:
            return

        try:
            payload: bytes = (cmd.to_json() + '\n').encode('utf-8')
            self._socket.sendall(payload)
        except Exception:
            pass

    def _listener_thread(self) -> None:
        """Background worker that continuously pulls bytes from the IPC stream."""
        buffer: str = ''
        try:
            while not self._stop_flag.is_set():
                if not self._socket:
                    break

                data: bytes = self._socket.recv(4096)
                if not data:
                    self._on_disconnect()
                    break

                buffer += data.decode('utf-8')

                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event_dict: Dict[str, Any] = json.loads(line)
                        event: IpcEvent = IpcEvent.from_dict(event_dict)
                        self._on_event(event)
                    except Exception:
                        pass
        except Exception:
            self._on_disconnect()
