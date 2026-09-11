"""Bounded single-writer dispatch for peer and local IPC sockets."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import socket
import threading
from typing import Callable, Optional


class FrameQueueFull(ConnectionError):
    """Raised when a bounded socket writer cannot admit another frame."""


@dataclass(frozen=True)
class QueuedFrame:
    """One serialized frame with an optional last-moment validity claim."""

    payload: bytes
    claim: Optional[Callable[[], bool]] = None


class BoundedSocketWriter:
    """Owns one tracked worker and finite FIFO for a single socket."""

    def __init__(
        self,
        conn: socket.socket,
        *,
        capacity: int,
        on_failure: Optional[Callable[[socket.socket, Exception], None]] = None,
        on_exit: Optional[Callable[['BoundedSocketWriter'], None]] = None,
        idle_timeout: float = 30.0,
    ) -> None:
        """Starts a single daemon worker for one socket."""
        if capacity <= 0:
            raise ValueError('Socket writer capacity must be positive.')
        self._conn = conn
        self._queue: queue.Queue[QueuedFrame] = queue.Queue(maxsize=capacity)
        self._on_failure = on_failure
        self._on_exit = on_exit
        self._idle_timeout = idle_timeout
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def enqueue(
        self, payload: bytes, claim: Optional[Callable[[], bool]] = None
    ) -> None:
        """Admits one bounded frame without waiting for socket I/O."""
        if self._closed.is_set():
            raise ConnectionError('Socket writer is closed.')
        try:
            self._queue.put_nowait(QueuedFrame(payload=payload, claim=claim))
        except queue.Full as exc:
            raise FrameQueueFull('Socket writer queue is full.') from exc

    def close(self) -> None:
        """Cancels queued work and interrupts a blocked socket write."""
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._conn.shutdown(socket.SHUT_RDWR)
        except (OSError, TypeError):
            pass
        try:
            self._conn.close()
        except (OSError, TypeError):
            pass

    def _run(self) -> None:
        """Serially admits claims and writes complete frames."""
        try:
            while not self._closed.is_set():
                try:
                    item = self._queue.get(timeout=self._idle_timeout)
                except queue.Empty:
                    return
                try:
                    if self._closed.is_set():
                        return
                    if item.claim is not None and not item.claim():
                        continue
                    self._conn.sendall(item.payload)
                except Exception as exc:
                    self._closed.set()
                    if self._on_failure is not None:
                        try:
                            self._on_failure(self._conn, exc)
                        except Exception:
                            pass
                    return
                finally:
                    self._queue.task_done()
        finally:
            if self._on_exit is not None:
                try:
                    self._on_exit(self)
                except Exception:
                    pass
