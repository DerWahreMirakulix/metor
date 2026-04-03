"""
Module defining daemon-local protocol, lifecycle, and transport enumerations.
Uses strict Enums to prevent string typos during handshakes, startup status flows,
and per-peer transport state derivation.
"""

from dataclasses import dataclass
from enum import Enum


class TorCommand(str, Enum):
    """Enumeration of all valid Tor protocol commands."""

    CHALLENGE = '/challenge'
    AUTH = '/auth'
    PENDING = '/pending'
    ACCEPTED = '/accepted'
    REJECT = '/reject'
    DISCONNECT = '/disconnect'
    MSG = '/msg'
    ACK = '/ack'
    DROP = '/drop'


class DaemonStatus(str, Enum):
    """Enumeration of local daemon startup states used outside the IPC boundary."""

    LOCKED_MODE = 'locked_mode'
    ACTIVE = 'active'


class PrimaryTransport(str, Enum):
    """Enumeration of the daemon-level primary transport per peer."""

    NONE = 'none'
    LIVE = 'live'
    DROP = 'drop'


class LiveTransportState(str, Enum):
    """Enumeration of the live transport lifecycle for one peer."""

    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    PENDING = 'pending'
    CONNECTED = 'connected'
    RETUNNELING = 'retunneling'


@dataclass(frozen=True)
class DropTunnelState:
    """Snapshot describing one cached drop tunnel."""

    opened_at: float
    last_used_at: float


@dataclass(frozen=True)
class PeerTransportState:
    """Snapshot describing the derived transport state for one peer."""

    onion: str
    live_state: LiveTransportState
    primary_transport: PrimaryTransport
    has_drop_tunnel: bool
    focus_count: int
    standby_drop_allowed: bool
    is_retunneling: bool
