"""Transport, session, and live-lifecycle IPC event DTOs."""

from dataclasses import dataclass, field
from typing import List, Optional

# Local Package Imports
from metor.core.api.base import IpcEvent
from metor.core.api.codes import (
    ConnectionActor,
    ConnectionOrigin,
    ConnectionReasonCode,
    EventType,
)
from metor.core.api.registry import register_event


@register_event(EventType.INIT)
@dataclass
class InitEvent(IpcEvent):
    """Initializes the UI with the local onion address."""

    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.INIT, init=False)


@register_event(EventType.TOR_KEY_DECRYPT_FAILED)
@dataclass
class TorKeyDecryptFailedEvent(IpcEvent):
    """Signals that the encrypted Tor runtime key could not be decrypted."""

    event_type: EventType = field(
        default=EventType.TOR_KEY_DECRYPT_FAILED,
        init=False,
    )


@register_event(EventType.TOR_KEY_WRITE_FAILED)
@dataclass
class TorKeyWriteFailedEvent(IpcEvent):
    """Signals that the Tor runtime key could not be written to disk."""

    event_type: EventType = field(default=EventType.TOR_KEY_WRITE_FAILED, init=False)


@register_event(EventType.TOR_START_FAILED)
@dataclass
class TorStartFailedEvent(IpcEvent):
    """Signals that the Tor process could not be started."""

    error: Optional[str] = None
    event_type: EventType = field(default=EventType.TOR_START_FAILED, init=False)


@register_event(EventType.TOR_PROCESS_TERMINATED)
@dataclass
class TorProcessTerminatedEvent(IpcEvent):
    """Signals that Tor terminated unexpectedly during startup."""

    error: Optional[str] = None
    event_type: EventType = field(
        default=EventType.TOR_PROCESS_TERMINATED,
        init=False,
    )


@register_event(EventType.REMOTE_MSG)
@dataclass
class RemoteMsgEvent(IpcEvent):
    """Carries a live inbound message."""

    alias: str
    text: str
    onion: Optional[str] = None
    timestamp: Optional[str] = None
    event_type: EventType = field(default=EventType.REMOTE_MSG, init=False)


@register_event(EventType.ACK)
@dataclass
class AckEvent(IpcEvent):
    """Confirms delivery of a live outbound message."""

    msg_id: str
    text: Optional[str] = None
    timestamp: Optional[str] = None
    event_type: EventType = field(default=EventType.ACK, init=False)


@register_event(EventType.DROP_FAILED)
@dataclass
class DropFailedEvent(IpcEvent):
    """Marks an asynchronous drop as failed."""

    msg_id: str
    event_type: EventType = field(default=EventType.DROP_FAILED, init=False)


@register_event(EventType.CONNECTED)
@dataclass
class ConnectedEvent(IpcEvent):
    """Announces a connected peer."""

    alias: str
    onion: str
    origin: ConnectionOrigin = ConnectionOrigin.MANUAL
    actor: ConnectionActor = ConnectionActor.REMOTE
    event_type: EventType = field(default=EventType.CONNECTED, init=False)


@register_event(EventType.DISCONNECTED)
@dataclass
class DisconnectedEvent(IpcEvent):
    """Announces a disconnected peer."""

    alias: str
    onion: Optional[str] = None
    actor: ConnectionActor = ConnectionActor.LOCAL
    origin: ConnectionOrigin = ConnectionOrigin.MANUAL
    reason_code: Optional[ConnectionReasonCode] = None
    event_type: EventType = field(default=EventType.DISCONNECTED, init=False)


@register_event(EventType.CONNECTION_CONNECTING)
@dataclass
class ConnectionConnectingEvent(IpcEvent):
    """Signals that an outbound connection attempt has started."""

    alias: str
    onion: Optional[str] = None
    origin: ConnectionOrigin = ConnectionOrigin.MANUAL
    actor: ConnectionActor = ConnectionActor.LOCAL
    event_type: EventType = field(
        default=EventType.CONNECTION_CONNECTING,
        init=False,
    )


@register_event(EventType.CONNECTIONS_STATE)
@dataclass
class ConnectionsStateEvent(IpcEvent):
    """Broadcasts the current connection-state snapshot."""

    active: List[str]
    pending: List[str]
    contacts: List[str]
    is_header: bool = False
    event_type: EventType = field(default=EventType.CONNECTIONS_STATE, init=False)


@register_event(EventType.SWITCH_SUCCESS)
@dataclass
class SwitchSuccessEvent(IpcEvent):
    """Confirms a focus switch or focus clear operation."""

    alias: Optional[str] = None
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.SWITCH_SUCCESS, init=False)


@register_event(EventType.CONNECTION_PENDING)
@dataclass
class ConnectionPendingEvent(IpcEvent):
    """Signals a pending outbound live connection."""

    alias: str
    onion: Optional[str] = None
    origin: ConnectionOrigin = ConnectionOrigin.MANUAL
    actor: ConnectionActor = ConnectionActor.REMOTE
    event_type: EventType = field(default=EventType.CONNECTION_PENDING, init=False)


@register_event(EventType.CONNECTION_AUTO_ACCEPTED)
@dataclass
class ConnectionAutoAcceptedEvent(IpcEvent):
    """Signals that a pending connection was auto-accepted."""

    alias: str
    onion: Optional[str] = None
    origin: ConnectionOrigin = ConnectionOrigin.INCOMING
    actor: ConnectionActor = ConnectionActor.SYSTEM
    event_type: EventType = field(
        default=EventType.CONNECTION_AUTO_ACCEPTED,
        init=False,
    )


@register_event(EventType.CONNECTION_RETRY)
@dataclass
class ConnectionRetryEvent(IpcEvent):
    """Signals a retrying connection attempt."""

    alias: str
    attempt: int
    max_retries: int
    onion: Optional[str] = None
    origin: ConnectionOrigin = ConnectionOrigin.MANUAL
    actor: ConnectionActor = ConnectionActor.SYSTEM
    event_type: EventType = field(default=EventType.CONNECTION_RETRY, init=False)


@register_event(EventType.CONNECTION_FAILED)
@dataclass
class ConnectionFailedEvent(IpcEvent):
    """Signals that a connection attempt failed permanently."""

    alias: str
    onion: Optional[str] = None
    error: Optional[str] = None
    origin: ConnectionOrigin = ConnectionOrigin.MANUAL
    actor: ConnectionActor = ConnectionActor.SYSTEM
    reason_code: Optional[ConnectionReasonCode] = None
    event_type: EventType = field(default=EventType.CONNECTION_FAILED, init=False)


@register_event(EventType.INCOMING_CONNECTION)
@dataclass
class IncomingConnectionEvent(IpcEvent):
    """Signals an inbound live connection request."""

    alias: str
    onion: Optional[str] = None
    origin: ConnectionOrigin = ConnectionOrigin.INCOMING
    actor: ConnectionActor = ConnectionActor.REMOTE
    event_type: EventType = field(default=EventType.INCOMING_CONNECTION, init=False)


@register_event(EventType.CONNECTION_REJECTED)
@dataclass
class ConnectionRejectedEvent(IpcEvent):
    """Signals that a live connection was rejected."""

    alias: str
    onion: Optional[str] = None
    origin: ConnectionOrigin = ConnectionOrigin.INCOMING
    actor: ConnectionActor = ConnectionActor.REMOTE
    reason_code: Optional[ConnectionReasonCode] = None
    event_type: EventType = field(default=EventType.CONNECTION_REJECTED, init=False)


@register_event(EventType.AUTO_RECONNECT_SCHEDULED)
@dataclass
class AutoReconnectScheduledEvent(IpcEvent):
    """Signals that an automatic reconnect was scheduled."""

    alias: str
    onion: Optional[str] = None
    origin: ConnectionOrigin = ConnectionOrigin.AUTO_RECONNECT
    actor: ConnectionActor = ConnectionActor.SYSTEM
    event_type: EventType = field(
        default=EventType.AUTO_RECONNECT_SCHEDULED,
        init=False,
    )


@register_event(EventType.CANNOT_CONNECT_SELF)
@dataclass
class CannotConnectSelfEvent(IpcEvent):
    """Signals that the local onion cannot connect to itself."""

    event_type: EventType = field(default=EventType.CANNOT_CONNECT_SELF, init=False)


@register_event(EventType.INVALID_TARGET)
@dataclass
class InvalidTargetEvent(IpcEvent):
    """Signals that a user-supplied target could not be resolved."""

    target: str
    event_type: EventType = field(default=EventType.INVALID_TARGET, init=False)


@register_event(EventType.CANNOT_SWITCH_SELF)
@dataclass
class CannotSwitchSelfEvent(IpcEvent):
    """Signals that the UI cannot focus the local onion."""

    event_type: EventType = field(default=EventType.CANNOT_SWITCH_SELF, init=False)


@register_event(EventType.NO_CONNECTION_TO_REJECT)
@dataclass
class NoConnectionToRejectEvent(IpcEvent):
    """Signals that there is no connection to reject."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(
        default=EventType.NO_CONNECTION_TO_REJECT,
        init=False,
    )


@register_event(EventType.NO_CONNECTION_TO_DISCONNECT)
@dataclass
class NoConnectionToDisconnectEvent(IpcEvent):
    """Signals that there is no connection to disconnect."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(
        default=EventType.NO_CONNECTION_TO_DISCONNECT,
        init=False,
    )


@register_event(EventType.NO_PENDING_CONNECTION)
@dataclass
class NoPendingConnectionEvent(IpcEvent):
    """Signals that there is no pending connection to accept."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.NO_PENDING_CONNECTION, init=False)


@register_event(EventType.PENDING_CONNECTION_EXPIRED)
@dataclass
class PendingConnectionExpiredEvent(IpcEvent):
    """Signals that a pending connection existed but its acceptance window expired."""

    alias: str
    onion: Optional[str] = None
    origin: ConnectionOrigin = ConnectionOrigin.INCOMING
    actor: ConnectionActor = ConnectionActor.SYSTEM
    reason_code: ConnectionReasonCode = ConnectionReasonCode.PENDING_ACCEPTANCE_EXPIRED
    event_type: EventType = field(
        default=EventType.PENDING_CONNECTION_EXPIRED,
        init=False,
    )


@register_event(EventType.MAX_CONNECTIONS_REACHED)
@dataclass
class MaxConnectionsReachedEvent(IpcEvent):
    """Signals that the maximum live connection count was reached."""

    target: str
    max_conn: int
    event_type: EventType = field(
        default=EventType.MAX_CONNECTIONS_REACHED,
        init=False,
    )


@register_event(EventType.DROPS_DISABLED)
@dataclass
class DropsDisabledEvent(IpcEvent):
    """Signals that offline drops are disabled."""

    event_type: EventType = field(default=EventType.DROPS_DISABLED, init=False)


@register_event(EventType.CANNOT_DROP_SELF)
@dataclass
class CannotDropSelfEvent(IpcEvent):
    """Signals that the local onion cannot send drops to itself."""

    event_type: EventType = field(default=EventType.CANNOT_DROP_SELF, init=False)


@register_event(EventType.DROP_QUEUED)
@dataclass
class DropQueuedEvent(IpcEvent):
    """Signals that a drop was queued successfully."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.DROP_QUEUED, init=False)


@register_event(EventType.NO_PENDING_LIVE_MSGS)
@dataclass
class NoPendingLiveMessagesEvent(IpcEvent):
    """Signals that no pending live messages existed for fallback."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.NO_PENDING_LIVE_MSGS, init=False)


@register_event(EventType.FALLBACK_SUCCESS)
@dataclass
class FallbackSuccessEvent(IpcEvent):
    """Signals that pending live messages were converted to drops."""

    alias: str
    count: int
    msg_ids: List[str]
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.FALLBACK_SUCCESS, init=False)


@register_event(EventType.RETUNNEL_INITIATED)
@dataclass
class RetunnelInitiatedEvent(IpcEvent):
    """Signals that retunneling has started for a peer."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.RETUNNEL_INITIATED, init=False)


@register_event(EventType.RETUNNEL_SUCCESS)
@dataclass
class RetunnelSuccessEvent(IpcEvent):
    """Signals that retunneling succeeded for a peer."""

    alias: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.RETUNNEL_SUCCESS, init=False)


@register_event(EventType.RETUNNEL_FAILED)
@dataclass
class RetunnelFailedEvent(IpcEvent):
    """Signals that retunneling failed for a peer."""

    alias: str
    onion: Optional[str] = None
    error: Optional[str] = None
    event_type: EventType = field(default=EventType.RETUNNEL_FAILED, init=False)
