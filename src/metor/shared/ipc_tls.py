"""Pinned TLS for the full-duplex managed IPC byte stream."""

from __future__ import annotations

import hmac
import select
import socket
import ssl
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar, cast

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer

_T = TypeVar('_T')


class IpcTlsSocket(ssl.SSLSocket):
    """Serializes short OpenSSL operations while allowing concurrent IPC reads and writes."""

    def activate(self) -> None:
        """Completes the bounded handshake before the socket becomes visible."""
        self.do_handshake()
        self._ipc_timeout = super().gettimeout()
        super().setblocking(False)
        self._tls_lock = threading.Lock()

    def settimeout(self, value: float | None) -> None:
        if hasattr(self, '_tls_lock'):
            self._ipc_timeout = value
        else:
            super().settimeout(value)

    def gettimeout(self) -> float | None:
        if hasattr(self, '_tls_lock'):
            return self._ipc_timeout
        return super().gettimeout()

    def _operate(self, operation: Callable[[], _T], deadline: float | None) -> _T:
        while True:
            with self._tls_lock:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError('IPC TLS operation timed out.')
                try:
                    return operation()
                except ssl.SSLWantReadError:
                    reading = True
                except ssl.SSLWantWriteError:
                    reading = False
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise TimeoutError('IPC TLS operation timed out.')
            readable, writable, _ = select.select(
                [self] if reading else [], [] if reading else [self], [], remaining
            )
            if not (readable or writable):
                raise TimeoutError('IPC TLS operation timed out.')

    def _deadline(self) -> float | None:
        timeout = self.gettimeout()
        return None if timeout is None else time.monotonic() + timeout

    def read_before(self, size: int, deadline: float | None) -> bytes:
        reader = super().recv
        return self._operate(
            lambda: reader(size), self._deadline() if deadline is None else deadline
        )

    def recv(self, buflen: int = 1024, flags: int = 0) -> bytes:
        if flags:
            raise ValueError('IPC TLS does not accept recv flags.')
        return self.read_before(buflen, None)

    def sendall(self, data: ReadableBuffer, flags: int = 0) -> None:
        if flags:
            raise ValueError('IPC TLS does not accept send flags.')
        data_view = memoryview(data)
        write = super().send
        deadline = self._deadline()
        while data_view:
            sent = self._operate(lambda: write(data_view), deadline)
            if not sent:
                raise ConnectionError('IPC TLS connection closed.')
            data_view = data_view[sent:]

    def shutdown(self, how: int) -> None:
        # Aborting or half-closing transport must not switch SSLSocket to raw reads.
        socket.socket.shutdown(self, how)


def authenticate_daemon(sock: socket.socket, certificate: str) -> IpcTlsSocket:
    """Authenticates exactly one independently supplied leaf before returning a stream."""
    if not certificate:
        raise ValueError('A trusted IPC daemon certificate is required.')
    expected = ssl.PEM_cert_to_DER_cert(certificate.strip())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cadata=certificate)
    context.sslsocket_class = IpcTlsSocket
    channel = cast(
        IpcTlsSocket, context.wrap_socket(sock, do_handshake_on_connect=False)
    )
    try:
        channel.activate()
        if not hmac.compare_digest(
            channel.getpeercert(binary_form=True) or b'', expected
        ):
            raise ssl.SSLCertVerificationError('IPC daemon certificate mismatch.')
        return channel
    except BaseException:
        channel.close()
        raise
