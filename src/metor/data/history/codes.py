"""Typed codes shared by the history persistence and projection layers."""

from enum import Enum


class HistoryFamily(str, Enum):
    """Top-level transport family for one history row."""

    LIVE = 'live'
    DROP = 'drop'


class HistoryEvent(str, Enum):
    """Raw persisted transport event codes."""

    DROP_QUEUED = 'drop_queued'
    DROP_SENT = 'drop_sent'
    DROP_RECEIVED = 'drop_received'
    DROP_FAILED = 'drop_failed'
    DROP_TUNNEL_CONNECTED = 'drop_tunnel_connected'
    DROP_TUNNEL_FAILED = 'drop_tunnel_failed'
    DROP_TUNNEL_CLOSED = 'drop_tunnel_closed'

    LIVE_REQUESTED = 'live_requested'
    LIVE_CONNECTED = 'live_connected'
    LIVE_REJECTED = 'live_rejected'
    LIVE_DISCONNECTED = 'live_disconnected'
    LIVE_CONNECTION_LOST = 'live_connection_lost'
    LIVE_AUTO_RECONNECT_SCHEDULED = 'live_auto_reconnect_scheduled'
    LIVE_RETUNNEL_INITIATED = 'live_retunnel_initiated'
    LIVE_RETUNNEL_SUCCESS = 'live_retunnel_success'
    LIVE_STREAM_CORRUPTED = 'live_stream_corrupted'

    @property
    def family(self) -> HistoryFamily:
        """
        Resolves the transport family for one raw event code.

        Args:
            None

        Returns:
            HistoryFamily: The normalized transport family.
        """
        if self.value.startswith('drop_'):
            return HistoryFamily.DROP
        return HistoryFamily.LIVE


class HistoryActor(str, Enum):
    """Describes who directly caused one history transition."""

    LOCAL = 'local'
    REMOTE = 'remote'
    SYSTEM = 'system'


class HistoryTrigger(str, Enum):
    """Machine-readable trigger categories persisted with transport history rows."""

    AUTO_ACCEPT_CONTACT = 'auto_accept_contact'
    AUTO_RECONNECT = 'auto_reconnect'
    GRACE_RECONNECT = 'grace_reconnect'
    INCOMING = 'incoming'
    MANUAL = 'manual'
    MUTUAL_CONNECT = 'mutual_connect'
    RETUNNEL = 'retunnel'


class HistoryReasonCode(str, Enum):
    """Machine-readable detail codes for raw history rows."""

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


class HistorySummaryCode(str, Enum):
    """Projected user-facing history summary codes."""

    CONNECTION_REQUESTED = 'connection_requested'
    CONNECTED = 'connected'
    CONNECTION_REJECTED = 'connection_rejected'
    CONNECTION_FAILED = 'connection_failed'
    CONNECTION_LOST = 'connection_lost'
    DISCONNECTED = 'disconnected'
    PENDING_EXPIRED = 'pending_expired'
    RETUNNEL_INITIATED = 'retunnel_initiated'
    RETUNNEL_SUCCEEDED = 'retunnel_succeeded'
    DROP_QUEUED = 'drop_queued'
    DROP_SENT = 'drop_sent'
    DROP_RECEIVED = 'drop_received'
    DROP_FAILED = 'drop_failed'
