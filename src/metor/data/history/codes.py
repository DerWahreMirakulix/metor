"""Typed codes shared by the history persistence and projection layers."""

from enum import Enum


class HistoryFamily(str, Enum):
    """Top-level transport family for one history row."""

    LIVE = 'live'
    DROP = 'drop'


class HistoryEvent(str, Enum):
    """Raw persisted transport event codes."""

    QUEUED = 'queued'
    SENT = 'sent'
    RECEIVED = 'received'
    FAILED = 'failed'
    TUNNEL_CONNECTED = 'tunnel_connected'
    TUNNEL_FAILED = 'tunnel_failed'
    TUNNEL_CLOSED = 'tunnel_closed'

    REQUESTED = 'requested'
    CONNECTED = 'connected'
    REJECTED = 'rejected'
    DISCONNECTED = 'disconnected'
    CONNECTION_LOST = 'connection_lost'
    AUTO_RECONNECT_SCHEDULED = 'auto_reconnect_scheduled'
    RETUNNEL_INITIATED = 'retunnel_initiated'
    RETUNNEL_SUCCEEDED = 'retunnel_succeeded'
    STREAM_CORRUPTED = 'stream_corrupted'

    @property
    def family(self) -> HistoryFamily:
        """
        Resolves the transport family for one raw event code.

        Args:
            None

        Returns:
            HistoryFamily: The normalized transport family.
        """
        return _HISTORY_EVENT_FAMILIES[self]


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

    AUTO_FALLBACK_TO_DROP = 'auto_fallback_to_drop'
    MANUAL_FALLBACK_TO_DROP = 'manual_fallback_to_drop'
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
    UNACKED_LIVE_CONVERTED_TO_DROP = 'unacked_live_converted_to_drop'


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


_HISTORY_EVENT_FAMILIES: dict[HistoryEvent, HistoryFamily] = {
    HistoryEvent.QUEUED: HistoryFamily.DROP,
    HistoryEvent.SENT: HistoryFamily.DROP,
    HistoryEvent.RECEIVED: HistoryFamily.DROP,
    HistoryEvent.FAILED: HistoryFamily.DROP,
    HistoryEvent.TUNNEL_CONNECTED: HistoryFamily.DROP,
    HistoryEvent.TUNNEL_FAILED: HistoryFamily.DROP,
    HistoryEvent.TUNNEL_CLOSED: HistoryFamily.DROP,
    HistoryEvent.REQUESTED: HistoryFamily.LIVE,
    HistoryEvent.CONNECTED: HistoryFamily.LIVE,
    HistoryEvent.REJECTED: HistoryFamily.LIVE,
    HistoryEvent.DISCONNECTED: HistoryFamily.LIVE,
    HistoryEvent.CONNECTION_LOST: HistoryFamily.LIVE,
    HistoryEvent.AUTO_RECONNECT_SCHEDULED: HistoryFamily.LIVE,
    HistoryEvent.RETUNNEL_INITIATED: HistoryFamily.LIVE,
    HistoryEvent.RETUNNEL_SUCCEEDED: HistoryFamily.LIVE,
    HistoryEvent.STREAM_CORRUPTED: HistoryFamily.LIVE,
}
