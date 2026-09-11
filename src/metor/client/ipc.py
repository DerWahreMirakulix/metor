"""Module managing the outbound IPC socket connection to the local Daemon."""

import socket
import threading
import time
import queue
from collections import deque
from dataclasses import dataclass
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


@dataclass(frozen=True)
class RequestLease:
    """Identity of one exchange, never transferable to a replacement connection."""

    generation: int
    request_id: str
    socket: socket.socket | None


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
        self._generation = 0
        self._listener_thread: Optional[threading.Thread] = None
        self._listener_generation = -1
        self._listener_lock = threading.Lock()
        self._event_thread: Optional[threading.Thread] = None
        self._event_generation = -1
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
        self._request_owners: dict[str, RequestLease] = {}
        self._callback_workers: list[threading.Thread] = []
        self._connect_lock = threading.Lock()
        self._caller = threading.local()
        self._lost_signal = threading.Event()
        self._callback_wakeup = threading.Event()

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
        """Serializes replacement; at most two callback generations may remain alive."""
        if not self._connect_lock.acquire(blocking=False):
            return False
        try:
            self._callback_workers = [t for t in self._callback_workers if t.is_alive()]
            if len(self._callback_workers) >= Constants.MAX_CLIENT_CALLBACK_GENERATIONS:
                return False
            return self._connect(start_listener=start_listener)
        finally:
            self._connect_lock.release()

    def _connect(self, *, start_listener: bool) -> bool:
        """
        Attempts to establish a connection to the Daemon.

        Args:
            start_listener (bool): Whether to start the background listener immediately.

        Returns:
            bool: True if connection is successful, False otherwise.
        """
        try:
            self.stop()
            candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            candidate.settimeout(self._timeout)
            try:
                candidate.connect((self._host, self._port))
            except Exception:
                candidate.close()
                raise
            with self._response_condition:
                self._publish_connection(candidate)
            if start_listener:
                self.start_listener()
            return True
        except Exception:
            self.stop()
            return False

    def _publish_connection(self, candidate: socket.socket) -> None:
        """Publishes replacement state under the exchange/loss transition lock."""
        self._generation += 1
        self._caller.generation = self._generation
        if hasattr(self._caller, 'callback_generation'):
            self._caller.callback_generation = self._generation
        self._stop_flag = threading.Event()
        self._lost_signal = threading.Event()
        self._callback_wakeup = threading.Event()
        self._disconnect_notified = False
        self._socket = candidate
        self._reader = BufferedIpcEventReader()
        self._response_waiters.clear()
        self._responses.clear()
        self._request_owners.clear()
        self._connection_lost = False
        self._event_queue = queue.Queue(maxsize=Constants.MAX_CLIENT_EVENT_QUEUE)
        self._response_condition.notify_all()

    def start_listener(self) -> None:
        """
        Starts the background listener after any synchronous bootstrap finished.

        Args:
            None

        Returns:
            None
        """
        with self._listener_lock:
            generation = self._generation
            stop_flag = self._stop_flag
            event_queue = self._event_queue
            if (
                self._event_thread is None
                or not self._event_thread.is_alive()
                or self._event_generation != generation
            ):
                self._event_thread = threading.Thread(
                    target=self._event_thread_main,
                    args=(
                        generation,
                        stop_flag,
                        event_queue,
                        self._lost_signal,
                        self._callback_wakeup,
                    ),
                    daemon=True,
                )
                self._event_generation = generation
                self._callback_workers.append(self._event_thread)
                self._event_thread.start()
            if self._socket is None:
                return
            if (
                self._listener_thread is None
                or not self._listener_thread.is_alive()
                or self._listener_generation != generation
            ):
                self._listener_thread = threading.Thread(
                    target=self._listener_thread_main,
                    args=(
                        generation,
                        stop_flag,
                        self._socket,
                        self._reader,
                        event_queue,
                    ),
                    daemon=True,
                )
                self._listener_generation = generation
                self._listener_thread.start()

    def stop(self) -> None:
        """
        Safely shuts down the background listener and closes the socket.

        Args:
            None

        Returns:
            None
        """
        with self._response_condition:
            self._stop_flag.set()
            self._callback_wakeup.set()
            self._connection_lost = True
            self._response_condition.notify_all()
            sock = self._socket
            self._socket = None
            listener, callback = self._listener_thread, self._event_thread

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
            listener
            and listener.is_alive()
            and threading.current_thread() is not listener
        ):
            listener.join(timeout=Constants.THREAD_POLL_TIMEOUT)
        if (
            callback
            and callback.is_alive()
            and threading.current_thread() is not callback
        ):
            callback.join(timeout=Constants.THREAD_POLL_TIMEOUT)

    def send_command(self, cmd: IpcCommand, lease: RequestLease | None = None) -> None:
        """
        Serializes and pushes a strictly typed command to the Daemon.

        Args:
            cmd (IpcCommand): The DTO payload to send.

        Returns:
            None
        """
        generation = self._generation if lease is None else lease.generation
        sock = self._socket if lease is None else lease.socket
        caller_generation = getattr(self._caller, 'callback_generation', generation)
        if caller_generation != generation:
            raise IpcDisconnectedError('The caller belongs to an ended IPC generation.')
        if sock is None:
            raise IpcDisconnectedError('IPC client is not connected.')

        try:
            ensure_request_id(cmd)
            payload: bytes = (cmd.to_json() + '\n').encode('utf-8')
            with self._send_lock:
                with self._response_condition:
                    if (
                        lease is not None
                        and self._request_owners.get(lease.request_id) is not lease
                    ):
                        raise IpcDisconnectedError(
                            'Request exchange ownership ended before send.'
                        )
                if (
                    generation != self._generation
                    or sock is not self._socket
                    or self._stop_flag.is_set()
                ):
                    raise IpcDisconnectedError(
                        'IPC generation ended before send admission.'
                    )
                sock.sendall(payload)
        except IpcClientError:
            raise
        except (OSError, ValueError) as exc:
            self._notify_disconnect(generation, sock=sock)
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

    def begin_request(self, request_id: str) -> RequestLease:
        """Registers one correlated response stream before sending its command.

        Args:
            request_id (str): Stable request correlation identifier.

        Returns:
            None
        """
        with self._response_condition:
            caller_generation = getattr(
                self._caller, 'callback_generation', self._generation
            )
            if caller_generation != self._generation:
                raise IpcDisconnectedError(
                    'The callback belongs to an ended IPC generation.'
                )
            if request_id in self._response_waiters:
                raise IpcRequestLimitError('Request ID is already registered.')
            if len(self._response_waiters) >= Constants.MAX_PENDING_IPC_REQUESTS:
                raise IpcRequestLimitError('Too many concurrent IPC requests.')
            self._response_waiters.add(request_id)
            self._responses.setdefault(request_id, deque())
            lease = RequestLease(self._generation, request_id, self._socket)
            self._request_owners[request_id] = lease
            self._caller.generation = self._generation
        self.start_listener()
        return lease

    def wait_for_response(
        self, request_id: str, lease: RequestLease | None = None
    ) -> Optional[IpcEvent]:
        """Waits for the sole reader thread to demultiplex one response event.

        Args:
            request_id (str): Registered request correlation identifier.

        Returns:
            Optional[IpcEvent]: Next correlated event, or None on timeout/loss.
        """
        deadline = time.monotonic() + self._timeout
        with self._response_condition:
            generation = (
                lease.generation
                if lease is not None
                else getattr(self._caller, 'generation', self._generation)
            )
            while not self._stop_flag.is_set():
                if generation != self._generation:
                    raise IpcDisconnectedError('Request connection generation ended.')
                if (
                    lease is not None
                    and self._request_owners.get(request_id) is not lease
                ):
                    raise IpcDisconnectedError('Request exchange ownership ended.')
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

    def end_request(self, request_id: str, lease: RequestLease | None = None) -> None:
        """Unregisters a request after its complete correlated exchange.

        Args:
            request_id (str): Stable request correlation identifier.

        Returns:
            None
        """
        with self._response_condition:
            generation = (
                lease.generation
                if lease is not None
                else getattr(self._caller, 'generation', self._generation)
            )
            owner = self._request_owners.get(request_id)
            if (
                generation != self._generation
                or owner is None
                or owner.generation != generation
                or (lease is not None and owner is not lease)
            ):
                return
            self._response_waiters.discard(request_id)
            self._request_owners.pop(request_id, None)
            remaining = tuple(self._responses.pop(request_id, ()))
        for event in remaining:
            self._queue_async_event(event, generation=generation)

    def dispatch_async_event(
        self, event: IpcEvent, lease: RequestLease | None = None
    ) -> None:
        """Publishes a mismatched outcome through callback ownership.

        Args:
            event (IpcEvent): Typed event not consumed by the request caller.

        Returns:
            None
        """
        self._queue_async_event(
            event,
            generation=lease.generation
            if lease
            else getattr(self._caller, 'generation', self._generation),
        )

    def _dispatch_event(
        self,
        event: IpcEvent,
        generation: Optional[int] = None,
        event_queue: Optional[queue.Queue[IpcEvent]] = None,
    ) -> None:
        """Routes responses to waiters and preserves every asynchronous event.

        Args:
            event (IpcEvent): Decoded daemon event.

        Returns:
            None
        """
        if generation is not None and generation != self._generation:
            return
        request_id = event.request_id
        if request_id is not None:
            overflow = False
            with self._response_condition:
                if generation is not None and generation != self._generation:
                    return
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
                self._notify_disconnect(generation, event_queue=event_queue)
                return
        self._queue_async_event(event, event_queue, generation)

    def _queue_async_event(
        self,
        event: IpcEvent,
        event_queue: Optional[queue.Queue[IpcEvent]] = None,
        generation: Optional[int] = None,
    ) -> None:
        """Queues user callbacks outside protocol and caller threads.

        Args:
            event (IpcEvent): Event to deliver asynchronously.
            event_queue (Optional[queue.Queue[_AsyncItem]]): Generation queue.

        Returns:
            None
        """
        with self._response_condition:
            effective_generation = (
                self._generation if generation is None else generation
            )
            if effective_generation != self._generation:
                return
            target_queue = event_queue or self._event_queue
            try:
                target_queue.put_nowait(event)
                self._callback_wakeup.set()
            except queue.Full:
                self._notify_disconnect(effective_generation, event_queue=target_queue)

    def _notify_disconnect(
        self,
        generation: Optional[int] = None,
        *,
        event_queue: Optional[queue.Queue[IpcEvent]] = None,
        sock: Optional[socket.socket] = None,
    ) -> None:
        """
        Fires the disconnect callback once for unexpected IPC loss.

        Args:
            None

        Returns:
            None
        """
        with self._response_condition:
            self._disconnect_transition(generation, sock)

    def _disconnect_transition(
        self, generation: int | None, sock: socket.socket | None
    ) -> None:
        """Retires only the matching transport under the replacement-state lock."""
        effective_generation = self._generation if generation is None else generation
        if effective_generation != self._generation or self._stop_flag.is_set():
            return

        with self._disconnect_lock:
            if self._disconnect_notified:
                return
            self._disconnect_notified = True

        with self._response_condition:
            self._connection_lost = True
            self._response_condition.notify_all()

        failed_socket = sock or self._socket
        if failed_socket is self._socket:
            self._socket = None
        if failed_socket is not None:
            try:
                failed_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                failed_socket.close()
            except OSError:
                pass

        self._lost_signal.set()
        self._callback_wakeup.set()

    def _event_thread_main(
        self,
        generation: Optional[int] = None,
        stop_flag: Optional[threading.Event] = None,
        event_queue: Optional[queue.Queue[IpcEvent]] = None,
        lost_signal: Optional[threading.Event] = None,
        wakeup: Optional[threading.Event] = None,
    ) -> None:
        """Dispatches asynchronous events without blocking the sole reader."""
        effective_generation = self._generation if generation is None else generation
        effective_stop = stop_flag or self._stop_flag
        effective_queue = event_queue or self._event_queue
        effective_lost = lost_signal or self._lost_signal
        effective_wakeup = wakeup or self._callback_wakeup
        self._caller.callback_generation = effective_generation
        self._caller.generation = effective_generation
        while not effective_stop.is_set():
            effective_wakeup.clear()
            if effective_lost.is_set() and effective_queue.empty():
                try:
                    self._on_disconnect()
                except Exception:
                    pass
                return
            try:
                item = effective_queue.get_nowait()
            except queue.Empty:
                if effective_generation != self._generation:
                    return
                effective_wakeup.wait(Constants.THREAD_POLL_TIMEOUT)
                continue
            try:
                if effective_generation == self._generation:
                    self._on_event(item)
            except Exception:
                pass
            finally:
                effective_queue.task_done()

    def _listener_thread_main(
        self,
        generation: Optional[int] = None,
        stop_flag: Optional[threading.Event] = None,
        sock: Optional[socket.socket] = None,
        reader: Optional[BufferedIpcEventReader] = None,
        event_queue: Optional[queue.Queue[IpcEvent]] = None,
    ) -> None:
        """
        Background worker that continuously pulls bytes from the IPC stream.
        Utilizes byte buffering to prevent UTF-8 fragmentation corruption.

        Args:
            None

        Returns:
            None
        """
        effective_generation = self._generation if generation is None else generation
        effective_stop = stop_flag or self._stop_flag
        effective_socket = sock or self._socket
        effective_reader = reader or self._reader
        try:
            while not effective_stop.is_set():
                if effective_socket is None or effective_generation != self._generation:
                    break

                try:
                    buffered_event: Optional[IpcEvent] = effective_reader.pop_event()
                except Exception:
                    continue

                if buffered_event is not None:
                    self._dispatch_event(
                        buffered_event, effective_generation, event_queue
                    )
                    continue

                try:
                    data: bytes = effective_socket.recv(Constants.TCP_BUFFER_SIZE)
                except socket.timeout:
                    continue

                if not data:
                    self._notify_disconnect(
                        effective_generation,
                        event_queue=event_queue,
                        sock=effective_socket,
                    )
                    break

                try:
                    effective_reader.append_bytes(data)
                except ValueError:
                    self._notify_disconnect(
                        effective_generation,
                        event_queue=event_queue,
                        sock=effective_socket,
                    )
                    break
        except Exception:
            self._notify_disconnect(
                effective_generation,
                event_queue=event_queue,
                sock=effective_socket,
            )
