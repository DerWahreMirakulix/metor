"""Machine-readable runtime and retunnel error codes shared across the IPC boundary."""

from enum import Enum


class RuntimeErrorCode(str, Enum):
    """Structured runtime and retunnel subreason codes for UI-side translation."""

    NO_CACHED_DROP_TUNNEL = 'no_cached_drop_tunnel'
    NO_ACTIVE_CONNECTION_TO_RETUNNEL = 'no_active_connection_to_retunnel'
    RETUNNEL_RECONNECT_FAILED = 'retunnel_reconnect_failed'
    PENDING_ACCEPTANCE_EXPIRED = 'pending_acceptance_expired'
    TOR_LAUNCH_FAILED = 'tor_launch_failed'
    TOR_BINARY_LAUNCH_FAILED = 'tor_binary_launch_failed'
    TOR_PROXY_NOT_READY = 'tor_proxy_not_ready'
