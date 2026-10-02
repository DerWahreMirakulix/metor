"""Call identities and metadata independent of message delivery semantics."""

from dataclasses import dataclass
from enum import Enum


class CallState(str, Enum):
    """States of one explicitly authorized telephone conversation."""

    CONNECTING = 'connecting'
    OUTGOING = 'outgoing'
    INCOMING = 'incoming'
    ACTIVE = 'active'
    ENDED = 'ended'


class CallReason(str, Enum):
    """Bounded call admission and termination outcomes."""

    REJECTED = 'rejected'
    CANCELLED = 'cancelled'
    HUNG_UP = 'hung_up'
    TIMEOUT = 'timeout'
    TRANSPORT_LOST = 'transport_lost'
    BUSY = 'busy'
    UNSUPPORTED = 'unsupported'
    CLIENT_LOST = 'client_lost'
    PROFILE_LOCKED = 'profile_locked'
    INVALID_STATE = 'invalid_state'
    NOT_OWNER = 'not_owner'
    MALFORMED = 'malformed'


@dataclass
class CallInfo:
    """Content-free state projection; owned is specific to the observing client."""

    call_id: str = ''
    peer: str = ''
    alias: str = ''
    state: CallState = CallState.ENDED
    muted: bool = False
    started_at: float | None = None
    reason: CallReason | None = None
    owned: bool = False


@dataclass
class CallAudioFrame:
    """One ephemeral ordered PCM frame; data is base64 encoded."""

    sequence: int = 0
    data: str = ''
