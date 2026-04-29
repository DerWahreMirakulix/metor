"""Transport and live-lifecycle enums shared across the IPC boundary."""

from enum import Enum


class ConnectionOrigin(str, Enum):
    """Enumeration describing why one live connection lifecycle step occurred."""

    MANUAL = 'manual'
    AUTO_RECONNECT = 'auto_reconnect'
    RETUNNEL = 'retunnel'
    INCOMING = 'incoming'
    GRACE_RECONNECT = 'grace_reconnect'
    MUTUAL_CONNECT = 'mutual_connect'
    AUTO_ACCEPT_CONTACT = 'auto_accept_contact'


class ConnectionActor(str, Enum):
    """Enumeration describing who directly caused one live lifecycle event."""

    LOCAL = 'local'
    REMOTE = 'remote'
    SYSTEM = 'system'


class ConnectionReasonCode(str, Enum):
    """Enumeration of machine-readable live lifecycle subreasons shared across the IPC boundary."""

    PEER_ENDED_SESSION = 'peer_ended_session'
    RETRY_EXHAUSTED = 'retry_exhausted'
    MAX_CONNECTIONS_REACHED = 'max_connections_reached'
    RETUNNEL_PENDING_CONNECTION_MISSING = 'retunnel_pending_connection_missing'
    LATE_ACCEPTANCE_TIMEOUT = 'late_acceptance_timeout'
    OUTBOUND_ATTEMPT_REJECTED = 'outbound_attempt_rejected'
    OUTBOUND_ATTEMPT_CLOSED_BEFORE_ACCEPTANCE = (
        'outbound_attempt_closed_before_acceptance'
    )
    PENDING_ACCEPTANCE_EXPIRED = 'pending_acceptance_expired'
    MUTUAL_TIEBREAKER_LOSER = 'mutual_tiebreaker_loser'
    DUPLICATE_INCOMING_CONNECTED = 'duplicate_incoming_connected'
    DUPLICATE_INCOMING_PENDING = 'duplicate_incoming_pending'
