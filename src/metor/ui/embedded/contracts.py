"""Small-screen read models for a future embedded frontend."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from metor.core.api import ConnectionActor, JsonValue, MessageContent


class DaemonLockState(str, Enum):
    """UI-safe daemon lock states."""

    LOCKED = 'locked'
    AUTH_REQUIRED = 'auth_required'
    READY = 'ready'


class DaemonHealth(str, Enum):
    """Compact daemon and Tor health states."""

    STARTING = 'starting'
    ONLINE = 'online'
    DEGRADED = 'degraded'
    OFFLINE = 'offline'


class LiveSessionPhase(str, Enum):
    """User-visible LIVE session phases."""

    PENDING = 'pending'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    RECONNECTING = 'reconnecting'
    RETUNNELING = 'retunneling'
    ENDING = 'ending'


class LiveAction(str, Enum):
    """Actions permitted by one projected LIVE state."""

    ACCEPT = 'accept'
    REJECT = 'reject'
    END = 'end'
    RETUNNEL = 'retunnel'
    FALLBACK = 'fallback'


@dataclass(frozen=True)
class CapabilityInfo:
    """Negotiated daemon capability and protocol summary."""

    negotiated_ipc_generation: int
    daemon_application_version: str
    capabilities: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EmbeddedStartupSnapshot:
    """Coherent initial state for a compact embedded home screen."""

    revision: int
    lock_state: DaemonLockState
    health: DaemonHealth
    profile_id: Optional[str]
    unread_drop_total: int
    active_live_count: int
    pending_live_count: int
    incoming_request_count: int
    capability_info: CapabilityInfo


@dataclass(frozen=True)
class DropConversationSummary:
    """DROP-only conversation-list projection."""

    peer_id: str
    alias: str
    last_drop_preview: Optional[str]
    unread_count: int
    last_activity: Optional[datetime]
    has_pending_outbox: bool
    has_active_live_session: bool = False


@dataclass(frozen=True)
class LiveSessionSummary:
    """LIVE-only session projection kept separate from DROP history."""

    peer_id: str
    alias: str
    phase: LiveSessionPhase
    actor: ConnectionActor
    reason_code: Optional[str]
    started_at: Optional[datetime]
    pending_outbound_count: int
    allowed_actions: Tuple[LiveAction, ...] = ()


@dataclass(frozen=True)
class DropMessagePageItem:
    """One stable message item in a paginated DROP result."""

    msg_id: str
    peer_id: str
    content: MessageContent
    timestamp: datetime
    revision: int


@dataclass(frozen=True)
class DropMessagePage:
    """Cursor-based DROP page that never includes LIVE content."""

    items: Tuple[DropMessagePageItem, ...]
    next_cursor: Optional[str] = None


@dataclass(frozen=True)
class LiveContentItem:
    """One transient LIVE content item, separate from DROP history."""

    msg_id: str
    peer_id: str
    content: MessageContent
    timestamp: datetime
    revision: int


@dataclass(frozen=True)
class SettingDescriptor:
    """Typed effective setting metadata suitable for any frontend."""

    key: str
    effective_value: JsonValue
    source: str
    scope: str
    value_type: str
    constraints: Optional[str]
    security_note: Optional[str]
    restart_required: bool
    editable: bool


@dataclass
class RevisionGate:
    """Applies incremental state only after a fresh ordered snapshot."""

    revision: Optional[int] = None
    seen_event_ids: set[str] = field(default_factory=set)

    def install_snapshot(self, revision: int) -> None:
        """Starts a new incremental event epoch.

        Args:
            revision (int): Authoritative snapshot revision.

        Returns:
            None
        """
        self.revision = revision
        self.seen_event_ids.clear()

    def accept(self, event_id: str, revision: int) -> bool:
        """Rejects duplicate, stale, or pre-snapshot incremental events.

        Args:
            event_id (str): Stable event identity.
            revision (int): Event revision.

        Returns:
            bool: Whether the event may be applied.
        """
        if self.revision is None or revision <= self.revision:
            return False
        if event_id in self.seen_event_ids:
            return False
        self.revision = revision
        self.seen_event_ids.add(event_id)
        return True
