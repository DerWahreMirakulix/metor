"""Bounded single-writer dispatch for peer and local IPC sockets."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import socket
import threading
from typing import Callable, Optional
from metor.utils import Constants


class FrameQueueFull(ConnectionError):
    """Raised when a bounded socket writer cannot admit another frame."""


@dataclass(frozen=True)
class QueuedFrame:
    """One serialized frame with an optional last-moment validity claim."""

    payload: bytes
    claim: Optional[Callable[[], bool]] = None
    final: bool = False


class BoundedSocketWriter:
    """Owns one tracked worker and finite FIFO for a single socket."""

    def __init__(
        self,
        conn: socket.socket,
        *,
        capacity: int,
        byte_capacity: int = 8 * 1024 * 1024,
        max_frame_bytes: int = 5 * 1024 * 1024,
        on_failure: Optional[Callable[[socket.socket, Exception], None]] = None,
        on_exit: Optional[Callable[['BoundedSocketWriter'], None]] = None,
    ) -> None:
        """Starts a single daemon worker for one socket."""
        if capacity <= 0:
            raise ValueError('Socket writer capacity must be positive.')
        if byte_capacity <= 0 or max_frame_bytes <= 0:
            raise ValueError('Socket writer byte limits must be positive.')
        self._conn = conn
        self._queue: queue.Queue[QueuedFrame] = queue.Queue(maxsize=capacity)
        self._byte_capacity = byte_capacity
        self._max_frame_bytes = max_frame_bytes
        self._queued_bytes = 0
        self._on_failure = on_failure
        self._on_exit = on_exit
        self._state_lock = threading.RLock()
        self._finish_timer: threading.Timer | None = None
        self._accepting = True
        self._socket_closed = False
        self._drained = threading.Event()
        self._drained.set()
        self._closed = threading.Event()
        self._started = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue(
        self,
        payload: bytes,
        claim: Optional[Callable[[], bool]] = None,
        *,
        final: bool = False,
    ) -> None:
        """Admits one bounded frame without waiting for socket I/O."""
        payload_size = len(payload)
        if payload_size > self._max_frame_bytes:
            raise FrameQueueFull('Socket writer frame exceeds its size limit.')
        with self._state_lock:
            if not self._accepting:
                raise ConnectionError('Socket writer is closed.')
            if self._queued_bytes + payload_size > self._byte_capacity:
                raise FrameQueueFull('Socket writer byte queue is full.')
            try:
                self._queue.put_nowait(
                    QueuedFrame(payload=payload, claim=claim, final=final)
                )
            except queue.Full as exc:
                raise FrameQueueFull('Socket writer queue is full.') from exc
            self._queued_bytes += payload_size
            self._drained.clear()

    def finish(self, payload: bytes, timeout: float) -> None:
        """Admits the last frame and transfers bounded shutdown to the writer.

        Args:
            payload (bytes): Final control frame, after all previously admitted work.
            timeout (float): Finite maximum drain time before forced cancellation.

        Returns:
            None
        """
        with self._state_lock:
            self.enqueue(payload, final=True)
            self._accepting = False
            self._finish_timer = threading.Timer(max(0.0, timeout), self.close)
            self._finish_timer.daemon = True
            self._finish_timer.start()

    def flush(self, timeout: float) -> bool:
        """Waits a bounded time for accepted frames to finish.

        Args:
            timeout (float): Maximum wait in seconds.

        Returns:
            bool: True when every accepted frame reached a terminal outcome.
        """
        return self._drained.wait(max(0.0, timeout))

    def wait_started(self, timeout: float) -> bool:
        """Waits until the sole delivery owner enters its worker loop.

        Args:
            timeout (float): Maximum wait in seconds.

        Returns:
            bool: True when worker ownership is established.
        """
        return self._started.wait(max(0.0, timeout))

    def close(self) -> None:
        """Cancels queued work and interrupts a blocked socket write."""
        with self._state_lock:
            self._accepting = False
            if self._socket_closed:
                return
            self._socket_closed = True
            self._closed.set()
            if self._finish_timer is not None:
                self._finish_timer.cancel()
        try:
            self._conn.shutdown(socket.SHUT_RDWR)
        except (OSError, TypeError):
            pass
        try:
            self._conn.close()
        except (OSError, TypeError):
            pass
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            with self._state_lock:
                self._queued_bytes -= len(item.payload)
                if self._queued_bytes == 0:
                    self._drained.set()
            self._queue.task_done()

    def _run(self) -> None:
        """Serially admits claims and writes complete frames."""
        self._started.set()
        try:
            while not self._closed.is_set():
                try:
                    item = self._queue.get(
                        timeout=Constants.SOCKET_WRITER_POLL_TIMEOUT_SEC
                    )
                except queue.Empty:
                    continue
                try:
                    if self._closed.is_set():
                        return
                    if item.claim is not None and not item.claim():
                        continue
                    self._conn.sendall(item.payload)
                    if item.final:
                        self._conn.shutdown(socket.SHUT_WR)
                        return
                except Exception as exc:
                    with self._state_lock:
                        self._accepting = False
                    if self._on_failure is not None:
                        try:
                            self._on_failure(self._conn, exc)
                        except Exception:
                            pass
                    return
                finally:
                    with self._state_lock:
                        self._queued_bytes -= len(item.payload)
                        if self._queued_bytes == 0:
                            self._drained.set()
                    self._queue.task_done()
        finally:
            self.close()
            if self._on_exit is not None:
                try:
                    self._on_exit(self)
                except Exception:
                    pass
