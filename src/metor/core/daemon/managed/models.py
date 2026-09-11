"""
Module defining daemon-local protocol and transport enumerations.
Uses strict Enums to prevent string typos during handshakes and per-peer
transport state derivation.
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
    DROP_ACK = '/drop_ack'
    DROP = '/drop'
    READ = '/read'
    VOICE_BEGIN = '/voice_begin'
    VOICE_CHUNK = '/voice_chunk'
    VOICE_END = '/voice_end'
    VOICE_ACK = '/voice_ack'
    VOICE_COMMIT_ACK = '/voice_commit_ack'
    DROP_VOICE_BEGIN = '/drop_voice_begin'
    DROP_VOICE_CHUNK = '/drop_voice_chunk'
    DROP_VOICE_END = '/drop_voice_end'


class DisconnectIntent(str, Enum):
    """Enumeration of semantic live-disconnect intents."""

    MANUAL = 'manual'
    RECOVER = 'recover'


class RejectIntent(str, Enum):
    """Enumeration of semantic live-reject intents."""

    MANUAL = 'manual'


class PrimaryTransport(str, Enum):
    """Enumeration of the daemon-level primary transport per peer."""

    NONE = 'none'
    SESSION = 'session'
    TUNNEL = 'tunnel'


class SessionState(str, Enum):
    """Enumeration of the live transport lifecycle for one peer."""

    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    PENDING = 'pending'
    CONNECTED = 'connected'
    RETUNNELING = 'retunneling'
    RECONNECT_GRACE = 'reconnect_grace'
    RECONNECT_SCHEDULED = 'reconnect_scheduled'


@dataclass(frozen=True)
class TunnelState:
    """Snapshot describing one cached drop tunnel."""

    opened_at: float
    last_used_at: float


@dataclass(frozen=True)
class PeerTransportState:
    """Snapshot describing the derived transport state for one peer."""

    onion: str
    live_state: SessionState
    primary_transport: PrimaryTransport
    has_drop_tunnel: bool
    focus_count: int
    standby_drop_allowed: bool
    is_retunneling: bool
