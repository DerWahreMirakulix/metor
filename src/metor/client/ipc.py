"""Module managing the outbound IPC socket connection to the local Daemon."""

import socket
import threading
import time
import queue
from collections import deque
from typing import Callable, Optional

from metor.client.stream import BufferedIpcEventReader
from metor.core.api import ensure_request_id, IpcCommand, IpcEvent
from metor.shared.constants import Constants


class IpcClientError(ConnectionError):
    """Base exception for explicit SDK transport failures."""


class IpcDisconnectedError(IpcClientError):
    """Raised when a response wait ends because the IPC stream was lost."""


class IpcSendError(IpcClientError):
    """Raised when a command could not be written to the daemon."""


class IpcTimeoutError(IpcClientError):
    """Raised when a correlated response did not arrive before its deadline."""


class IpcRequestLimitError(IpcClientError):
    """Raised when the bounded concurrent request inventory is saturated."""


class IpcClient:
    """Handles the raw TCP socket connection to the background Daemon."""

    def __init__(
        self,
        port: int,
        timeout: float,
        on_event: Callable[[IpcEvent], None],
        on_disconnect: Callable[[], None],
        host: str = Constants.LOCALHOST,
    ) -> None:
        """
        Initializes the IPC Client.

        Args:
            port (int): The local localhost port the Daemon is listening on.
            timeout (float): Socket timeout used for connect and recv operations.
            on_event (Callable[[IpcEvent], None]): Callback fired when a valid event arrives.
            on_disconnect (Callable[[], None]): Callback fired if the connection drops.
            host (str): Host address to connect to (defaults to 127.0.0.1).

        Returns:
            None
        """
        self._host: str = host
        self._port: int = port
        self._timeout: float = timeout
        self._on_event: Callable[[IpcEvent], None] = on_event
        self._on_disconnect: Callable[[], None] = on_disconnect

        self._socket: Optional[socket.socket] = None
        self._stop_flag: threading.Event = threading.Event()
        self._listener_thread: Optional[threading.Thread] = None
        self._listener_lock = threading.Lock()
        self._event_thread: Optional[threading.Thread] = None
        self._event_queue: queue.Queue[IpcEvent] = queue.Queue(
            maxsize=Constants.MAX_CLIENT_EVENT_QUEUE
        )
        self._disconnect_lock: threading.Lock = threading.Lock()
        self._send_lock: threading.Lock = threading.Lock()
        self._disconnect_notified: bool = False
        self._reader: BufferedIpcEventReader = BufferedIpcEventReader()
        self._response_condition = threading.Condition()
        self._response_waiters: set[str] = set()
        self._responses: dict[str, deque[IpcEvent]] = {}
        self._connection_lost = False

    @property
    def host(self) -> str:
        """
        Returns the target host address.

        Args:
            None

        Returns:
            str: The target host address.
        """
        return self._host

    @property
    def port(self) -> int:
        """
        Returns the target port.

        Args:
            None

        Returns:
            int: The target port.
        """
        return self._port

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
            self._socket.connect((self._host, self._port))
            self._reader.reset()
            with self._response_condition:
                self._response_waiters.clear()
                self._responses.clear()
                self._connection_lost = False
            self._event_queue = queue.Queue(maxsize=Constants.MAX_CLIENT_EVENT_QUEUE)
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
        with self._listener_lock:
            if self._socket is None:
                return
            if self._listener_thread is not None and self._listener_thread.is_alive():
                return
            self._listener_thread = threading.Thread(
                target=self._listener_thread_main,
                daemon=True,
            )
            self._event_thread = threading.Thread(
                target=self._event_thread_main,
                daemon=True,
            )
            self._listener_thread.start()
            self._event_thread.start()

    def stop(self) -> None:
        """
        Safely shuts down the background listener and closes the socket.

        Args:
            None

        Returns:
            None
        """
        self._stop_flag.set()
        with self._response_condition:
            self._connection_lost = True
            self._response_condition.notify_all()
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
        if (
            self._event_thread
            and self._event_thread.is_alive()
            and threading.current_thread() is not self._event_thread
        ):
            self._event_thread.join(timeout=Constants.THREAD_POLL_TIMEOUT)

    def send_command(self, cmd: IpcCommand) -> None:
        """
        Serializes and pushes a strictly typed command to the Daemon.

        Args:
            cmd (IpcCommand): The DTO payload to send.

        Returns:
            None
        """
        if not self._socket:
            raise IpcDisconnectedError('IPC client is not connected.')

        try:
            ensure_request_id(cmd)
            payload: bytes = (cmd.to_json() + '\n').encode('utf-8')
            with self._send_lock:
                self._socket.sendall(payload)
        except (OSError, ValueError) as exc:
            self._notify_disconnect()
            raise IpcSendError('IPC command could not be sent.') from exc

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

        if self._listener_thread is not None and self._listener_thread.is_alive():
            raise RuntimeError('The active listener owns all IPC reads.')

        return self._reader.read_from_socket(self._socket)

    def begin_request(self, request_id: str) -> None:
        """Registers one correlated response stream before sending its command.

        Args:
            request_id (str): Stable request correlation identifier.

        Returns:
            None
        """
        with self._response_condition:
            if len(self._response_waiters) >= Constants.MAX_PENDING_IPC_REQUESTS:
                raise IpcRequestLimitError('Too many concurrent IPC requests.')
            self._response_waiters.add(request_id)
            self._responses.setdefault(request_id, deque())
        self.start_listener()

    def wait_for_response(self, request_id: str) -> Optional[IpcEvent]:
        """Waits for the sole reader thread to demultiplex one response event.

        Args:
            request_id (str): Registered request correlation identifier.

        Returns:
            Optional[IpcEvent]: Next correlated event, or None on timeout/loss.
        """
        deadline = time.monotonic() + self._timeout
        with self._response_condition:
            while not self._stop_flag.is_set():
                queued = self._responses.get(request_id)
                if queued:
                    return queued.popleft()
                if self._connection_lost or self._stop_flag.is_set():
                    raise IpcDisconnectedError(
                        'IPC connection ended before the response arrived.'
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise IpcTimeoutError('IPC request timed out.')
                self._response_condition.wait(remaining)
        raise IpcDisconnectedError('IPC request was stopped before completion.')

    def end_request(self, request_id: str) -> None:
        """Unregisters a request after its complete correlated exchange.

        Args:
            request_id (str): Stable request correlation identifier.

        Returns:
            None
        """
        with self._response_condition:
            self._response_waiters.discard(request_id)
            remaining = tuple(self._responses.pop(request_id, ()))
        for event in remaining:
            try:
                self._on_event(event)
            except Exception:
                pass

    def _dispatch_event(self, event: IpcEvent) -> None:
        """Routes responses to waiters and preserves every asynchronous event.

        Args:
            event (IpcEvent): Decoded daemon event.

        Returns:
            None
        """
        request_id = event.request_id
        if request_id is not None:
            overflow = False
            with self._response_condition:
                if request_id in self._response_waiters:
                    responses = self._responses[request_id]
                    if len(responses) >= Constants.MAX_RESPONSES_PER_REQUEST:
                        self._connection_lost = True
                        self._response_condition.notify_all()
                        overflow = True
                    else:
                        responses.append(event)
                        overflow = False
                    self._response_condition.notify_all()
                    if not overflow:
                        return
            if overflow:
                self._notify_disconnect()
                return
        if self._event_thread is None or not self._event_thread.is_alive():
            try:
                self._on_event(event)
            except Exception:
                pass
            return
        try:
            self._event_queue.put_nowait(event)
        except queue.Full:
            self._notify_disconnect()

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

        with self._response_condition:
            self._connection_lost = True
            self._response_condition.notify_all()

        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        self._on_disconnect()

    def _event_thread_main(self) -> None:
        """Dispatches asynchronous events without blocking the sole reader."""
        while not self._stop_flag.is_set():
            try:
                event = self._event_queue.get(timeout=Constants.THREAD_POLL_TIMEOUT)
            except queue.Empty:
                if self._connection_lost:
                    return
                continue
            try:
                self._on_event(event)
            except Exception:
                pass
            finally:
                self._event_queue.task_done()

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
                    self._dispatch_event(buffered_event)
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
