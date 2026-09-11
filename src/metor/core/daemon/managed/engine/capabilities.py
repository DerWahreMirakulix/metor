"""Exact runtime identities for restricted anonymous pending-call actions."""

from dataclasses import dataclass
import socket


@dataclass(frozen=True)
class PendingCallGrant:
    """One requesting session's opaque authority over one pending socket."""

    onion: str
    restriction: int
    runtime: int
    pending: socket.socket
    expires_at: float
