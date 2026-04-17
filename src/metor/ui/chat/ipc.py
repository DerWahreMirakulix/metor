"""Module managing the outbound IPC socket connection to the local Daemon."""

import socket
import threading
from typing import Callable, Optional

from metor.core.api import ensure_request_id, IpcCommand, IpcEvent
from metor.ui.ipc import BufferedIpcEventReader

# Local Package Imports
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
        self._reader: BufferedIpcEventReader = BufferedIpcEventReader()

    def connect(self, *, start_listener: bool = True) -> bool:
        """
        Attempts to establish a connection to the Daemon.

        Args:
            start_listener (bool): Whether to start the background listener immediately.

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
            self._reader.reset()
            if start_listener:
                self.start_listener()
            return True
        except Exception:
            self.stop()
            return False

    def start_listener(self) -> None:
        """
        Starts the background listener after any synchronous bootstrap finished.

        Args:
            None

        Returns:
            None
        """
        if self._socket is None:
            return

        if self._listener_thread is not None and self._listener_thread.is_alive():
            return

        self._listener_thread = threading.Thread(
            target=self._listener_thread_main,
            daemon=True,
        )
        self._listener_thread.start()

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
            ensure_request_id(cmd)
            payload: bytes = (cmd.to_json() + '\n').encode('utf-8')
            self._socket.sendall(payload)
        except Exception:
            pass

    def read_event(self) -> Optional[IpcEvent]:
        """
        Reads one IPC event synchronously from the connected socket.

        Args:
            None

        Returns:
            Optional[IpcEvent]: The decoded event, or None when the stream ends.
        """
        if self._socket is None:
            return None

        return self._reader.read_from_socket(self._socket)

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
        try:
            while not self._stop_flag.is_set():
                if not self._socket:
                    break

                try:
                    buffered_event: Optional[IpcEvent] = self._reader.pop_event()
                except Exception:
                    continue

                if buffered_event is not None:
                    self._on_event(buffered_event)
                    continue

                try:
                    data: bytes = self._socket.recv(Constants.TCP_BUFFER_SIZE)
                except socket.timeout:
                    continue

                if not data:
                    self._notify_disconnect()
                    break

                try:
                    self._reader.append_bytes(data)
                except ValueError:
                    self._notify_disconnect()
                    break
        except Exception:
            self._notify_disconnect()
