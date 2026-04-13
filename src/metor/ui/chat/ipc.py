"""
Module managing the outbound IPC socket connection to the local Daemon.
Isolates all raw TCP byte parsing from the Chat Engine logic and thwarts UTF-8 DoS attacks.
"""

import socket
import threading
import json
from typing import Callable, Dict, Optional

from metor.core.api import IpcCommand, IpcEvent, JsonValue
from metor.utils import Constants


class IpcClient:
    """Handles the raw TCP socket connection to the background Daemon."""

    def __init__(
        self,
        port: int,
        timeout: float,
        on_event: Callable[[IpcEvent], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        """
        Initializes the IPC Client.

        Args:
            port (int): The local localhost port the Daemon is listening on.
            timeout (float): Socket timeout used for connect and recv operations.
            on_event (Callable[[IpcEvent], None]): Callback fired when a valid event arrives.
            on_disconnect (Callable[[], None]): Callback fired if the connection drops.

        Returns:
            None
        """
        self._port: int = port
        self._timeout: float = timeout
        self._on_event: Callable[[IpcEvent], None] = on_event
        self._on_disconnect: Callable[[], None] = on_disconnect

        self._socket: Optional[socket.socket] = None
        self._stop_flag: threading.Event = threading.Event()
        self._listener_thread: Optional[threading.Thread] = None
        self._disconnect_lock: threading.Lock = threading.Lock()
        self._disconnect_notified: bool = False

    def connect(self) -> bool:
        """
        Attempts to establish a connection to the Daemon.

        Args:
            None

        Returns:
            bool: True if connection is successful, False otherwise.
        """
        try:
            self._stop_flag.clear()
            with self._disconnect_lock:
                self._disconnect_notified = False

            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self._timeout)
            self._socket.connect((Constants.LOCALHOST, self._port))
            self._listener_thread = threading.Thread(
                target=self._listener_thread_main, daemon=True
            )
            self._listener_thread.start()
            return True
        except Exception:
            self.stop()
            return False

    def stop(self) -> None:
        """
        Safely shuts down the background listener and closes the socket.

        Args:
            None

        Returns:
            None
        """
        self._stop_flag.set()
        sock: Optional[socket.socket] = self._socket
        self._socket = None

        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

        if (
            self._listener_thread
            and self._listener_thread.is_alive()
            and threading.current_thread() is not self._listener_thread
        ):
            self._listener_thread.join(timeout=Constants.THREAD_POLL_TIMEOUT)

    def send_command(self, cmd: IpcCommand) -> None:
        """
        Serializes and pushes a strictly typed command to the Daemon.

        Args:
            cmd (IpcCommand): The DTO payload to send.

        Returns:
            None
        """
        if not self._socket:
            return

        try:
            payload: bytes = (cmd.to_json() + '\n').encode('utf-8')
            self._socket.sendall(payload)
        except Exception:
            pass

    def _notify_disconnect(self) -> None:
        """
        Fires the disconnect callback once for unexpected IPC loss.

        Args:
            None

        Returns:
            None
        """
        if self._stop_flag.is_set():
            return

        with self._disconnect_lock:
            if self._disconnect_notified:
                return
            self._disconnect_notified = True

        self._on_disconnect()

    def _listener_thread_main(self) -> None:
        """
        Background worker that continuously pulls bytes from the IPC stream.
        Utilizes byte buffering to prevent UTF-8 fragmentation corruption.

        Args:
            None

        Returns:
            None
        """
        buffer: bytearray = bytearray()
        try:
            while not self._stop_flag.is_set():
                if not self._socket:
                    break

                try:
                    data: bytes = self._socket.recv(Constants.TCP_BUFFER_SIZE)
                except socket.timeout:
                    continue

                if not data:
                    self._notify_disconnect()
                    break

                buffer.extend(data)

                if len(buffer) > Constants.MAX_IPC_BYTES:
                    self._notify_disconnect()
                    break

                while b'\n' in buffer:
                    line_bytes, _, rest = buffer.partition(b'\n')
                    buffer = bytearray(rest)

                    try:
                        line: str = line_bytes.decode('utf-8').strip()
                    except UnicodeDecodeError:
                        self._notify_disconnect()
                        return

                    if not line:
                        continue

                    try:
                        event_dict: Dict[str, JsonValue] = json.loads(line)
                        event: IpcEvent = IpcEvent.from_dict(event_dict)
                        self._on_event(event)
                    except Exception:
                        pass
        except Exception:
            self._notify_disconnect()
