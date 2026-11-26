"""Bounded receiver-owned acknowledgements for Voice Drops on Live sockets."""

import socket
import threading
import time
from typing import Callable

from metor.utils import Constants


class DropTransferAcknowledgements:
    """Owns one response slot for an exact authenticated socket and message.

    The receiver publishes frames without reading competing with the sender.
    Timeout, shutdown, socket replacement and response overflow cancel this
    attempt while its durable outbox row remains eligible for a later retry.
    """

    def __init__(
        self,
        onion: str,
        msg_id: str,
        timeout: float,
        stop_flag: threading.Event,
        is_current: Callable[[], bool],
    ) -> None:
        """Initializes bounded response ownership and cancellation checks."""
        self.onion = onion
        self.msg_id = msg_id
        self._timeout = timeout
        self._stop_flag = stop_flag
        self._is_current = is_current
        self._condition = threading.Condition()
        self._response: str | None = None
        self._closed = False

    def publish(self, line: str) -> None:
        """Publishes one response, cancelling an attempt on response overflow."""
        with self._condition:
            if self._closed:
                return
            if self._response is not None:
                self._closed = True
                self._response = None
            else:
                self._response = line
            self._condition.notify_all()

    def close(self) -> None:
        """Revokes this attempt and wakes its sender without touching a retry."""
        with self._condition:
            self._closed = True
            self._response = None
            self._condition.notify_all()

    def is_open(self) -> bool:
        """Checks response ownership before admitting another queued frame."""
        with self._condition:
            return not self._closed and not self._stop_flag.is_set()

    def read_line(self) -> str | None:
        """Waits for a receiver-owned response within the configured idle timeout."""
        deadline = time.monotonic() + self._timeout
        while not self._stop_flag.is_set() and self._is_current():
            with self._condition:
                if self._closed:
                    return None
                if self._response is not None:
                    response, self._response = self._response, None
                    return response
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._closed = True
                    return None
                self._condition.wait(
                    min(remaining, Constants.SOCKET_WRITER_POLL_TIMEOUT_SEC)
                )
        self.close()
        return None


class StateTrackerDropTransferMixin:
    """Correlates one bounded Voice Drop transfer per current Live socket."""

    _lock: threading.RLock
    _connections: dict[str, socket.socket]
    _drop_transfers: dict[socket.socket, DropTransferAcknowledgements]

    def begin_drop_transfer(
        self,
        onion: str,
        conn: socket.socket,
        msg_id: str,
        timeout: float,
        stop_flag: threading.Event,
        eligible: Callable[[], bool] | None = None,
    ) -> DropTransferAcknowledgements:
        """Admits one response owner only on the exact current socket.

        Raises:
            ConnectionError: The socket is stale or transfer capacity is occupied.
        """
        with self._lock:
            if (
                self._connections.get(onion) is not conn
                or conn in self._drop_transfers
                or len(self._drop_transfers) >= Constants.DROP_SESSION_MAX_TRANSFERS
            ):
                raise ConnectionError('Live Drop transfer is unavailable.')
            transfer = DropTransferAcknowledgements(
                onion,
                msg_id,
                timeout,
                stop_flag,
                lambda: (
                    self.is_drop_transfer_current(conn, transfer)
                    and (eligible is None or eligible())
                ),
            )
            self._drop_transfers[conn] = transfer
            return transfer

    def is_drop_transfer_current(
        self, conn: socket.socket, transfer: DropTransferAcknowledgements
    ) -> bool:
        """Checks the exact transfer lease at response and writer boundaries."""
        with self._lock:
            return (
                self._drop_transfers.get(conn) is transfer
                and self._connections.get(transfer.onion) is conn
                and transfer.is_open()
            )

    def finish_drop_transfer(
        self, conn: socket.socket, transfer: DropTransferAcknowledgements
    ) -> None:
        """Removes only the finishing lease, preserving any replacement owner."""
        with self._lock:
            if self._drop_transfers.get(conn) is transfer:
                self._drop_transfers.pop(conn)
        transfer.close()

    def acknowledge_drop_transfer(
        self, onion: str, conn: socket.socket, msg_id: str, line: str
    ) -> bool:
        """Routes a response by authenticated peer, exact socket and message ID."""
        with self._lock:
            transfer = self._drop_transfers.get(conn)
            if transfer is None or transfer.onion != onion or transfer.msg_id != msg_id:
                return False
            current = self._connections.get(onion) is conn
        if current:
            transfer.publish(line)
        else:
            transfer.close()
        return True

    def reject_drop_transfer(self, onion: str, conn: socket.socket, line: str) -> bool:
        """Routes the existing uncorrelated DROP-policy rejection to its sole owner."""
        with self._lock:
            transfer = self._drop_transfers.get(conn)
            msg_id = transfer.msg_id if transfer is not None else None
        return msg_id is not None and self.acknowledge_drop_transfer(
            onion, conn, msg_id, line
        )
