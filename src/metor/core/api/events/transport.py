"""Transport, session, and live-lifecycle IPC event DTOs."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from metor.core.api.content import Delivery, MessageContent

# Local Package Imports
from metor.core.api.base import IpcEvent, JsonValue
from metor.core.api.codes import (
    ConnectionActor,
    ConnectionOrigin,
    ConnectionReasonCode,
    EventType,
    RuntimeErrorCode,
    MessageOperationReason,
)
from metor.core.api.registry import register_event


@register_event(EventType.INIT)
@dataclass
class InitEvent(IpcEvent):
    """Initializes the UI after successful IPC generation negotiation."""

    negotiated_version: int
    daemon_current_version: int
    daemon_min_supported: int
    onion: Optional[str] = None
    profile: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
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
    error_code: Optional[RuntimeErrorCode] = None
    error_detail: Optional[str] = None
    event_type: EventType = field(default=EventType.TOR_START_FAILED, init=False)


@register_event(EventType.TOR_PROCESS_TERMINATED)
@dataclass
class TorProcessTerminatedEvent(IpcEvent):
    """Signals that Tor terminated unexpectedly during startup."""

    error: Optional[str] = None
    error_code: Optional[RuntimeErrorCode] = None
    error_detail: Optional[str] = None
    event_type: EventType = field(
        default=EventType.TOR_PROCESS_TERMINATED,
        init=False,
    )


@register_event(EventType.MESSAGE_RECEIVED)
@dataclass
class MessageReceivedEvent(IpcEvent):
    """Carries inbound typed content and independent delivery semantics."""

    alias: str
    delivery: Delivery
    content: MessageContent
    onion: Optional[str] = None
    timestamp: Optional[str] = None
    msg_id: Optional[str] = None
    event_type: EventType = field(default=EventType.MESSAGE_RECEIVED, init=False)


@register_event(EventType.ACK)
@dataclass
class AckEvent(IpcEvent):
    """Confirms delivery of a live outbound message."""

    msg_id: str
    timestamp: Optional[str] = None
    event_type: EventType = field(default=EventType.ACK, init=False)


@register_event(EventType.DROP_FAILED)
@dataclass
class DropFailedEvent(IpcEvent):
    """Marks an asynchronous drop as failed."""

    msg_id: str
    reason: Optional[str] = None
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


@register_event(EventType.AUTO_FALLBACK_QUEUED)
@dataclass
class AutoFallbackQueuedEvent(IpcEvent):
    """Signals that one live-send request was queued directly as a drop."""

    alias: str
    msg_id: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.AUTO_FALLBACK_QUEUED, init=False)


@register_event(EventType.LIVE_MESSAGE_UNAVAILABLE)
@dataclass
class LiveMessageUnavailableEvent(IpcEvent):
    """Rejects a LIVE send when no active or recoverable session exists."""

    alias: str
    msg_id: str
    onion: Optional[str] = None
    reason: MessageOperationReason = MessageOperationReason.NO_RECOVERY
    event_type: EventType = field(
        default=EventType.LIVE_MESSAGE_UNAVAILABLE,
        init=False,
    )


@register_event(EventType.LIVE_MESSAGE_RESOURCE_PRESSURE)
@dataclass
class LiveMessageResourcePressureEvent(IpcEvent):
    """Rejects a LIVE send that would exceed the retained pending budget."""

    alias: str
    msg_id: str
    reason: MessageOperationReason
    onion: Optional[str] = None
    pending_count: int = 0
    pending_bytes: int = 0
    event_type: EventType = field(
        default=EventType.LIVE_MESSAGE_RESOURCE_PRESSURE,
        init=False,
    )


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


@register_event(EventType.FALLBACK_REJECTED)
@dataclass
class FallbackRejectedEvent(IpcEvent):
    """Rejects an atomic selective fallback whose selection is ineligible."""

    alias: str
    reason: MessageOperationReason
    msg_ids: List[str]
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.FALLBACK_REJECTED, init=False)


@register_event(EventType.MESSAGE_DELETED)
@dataclass
class MessageDeletedEvent(IpcEvent):
    """Confirms local payload deletion for one DROP message."""

    alias: str
    msg_id: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.MESSAGE_DELETED, init=False)


@register_event(EventType.MESSAGE_DELETE_REJECTED)
@dataclass
class MessageDeleteRejectedEvent(IpcEvent):
    """Rejects local deletion without changing delivery semantics."""

    target: str
    msg_id: str
    reason: MessageOperationReason
    onion: Optional[str] = None
    event_type: EventType = field(
        default=EventType.MESSAGE_DELETE_REJECTED,
        init=False,
    )


@register_event(EventType.LIVE_CONTEXT_DISMISSED)
@dataclass
class LiveContextDismissedEvent(IpcEvent):
    """Confirms destruction of resolved inbound disconnected LIVE state."""

    alias: str
    onion: Optional[str] = None
    removed_count: int = 0
    event_type: EventType = field(
        default=EventType.LIVE_CONTEXT_DISMISSED,
        init=False,
    )


@register_event(EventType.LIVE_CONTEXT_DISMISS_REJECTED)
@dataclass
class LiveContextDismissRejectedEvent(IpcEvent):
    """Rejects LIVE-context dismissal while canonical state is unresolved."""

    alias: str
    reason: MessageOperationReason
    onion: Optional[str] = None
    event_type: EventType = field(
        default=EventType.LIVE_CONTEXT_DISMISS_REJECTED,
        init=False,
    )


@register_event(EventType.VOICE_STARTED)
@dataclass
class VoiceStartedEvent(IpcEvent):
    """Confirms allocation of one logical Voice turn."""

    alias: str
    msg_id: str
    delivery: Delivery
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.VOICE_STARTED, init=False)


@register_event(EventType.VOICE_CHUNK_ACCEPTED)
@dataclass
class VoiceChunkAcceptedEvent(IpcEvent):
    """Confirms durable acceptance through the returned next offset."""

    msg_id: str
    next_offset: int
    event_type: EventType = field(
        default=EventType.VOICE_CHUNK_ACCEPTED,
        init=False,
    )


@register_event(EventType.VOICE_CHUNK_RECEIVED)
@dataclass
class VoiceChunkReceivedEvent(IpcEvent):
    """Streams one bounded inbound Voice chunk to an attached consumer."""

    alias: str
    msg_id: str
    offset: int
    data: str
    onion: Optional[str] = None
    event_type: EventType = field(
        default=EventType.VOICE_CHUNK_RECEIVED,
        init=False,
    )


@register_event(EventType.VOICE_FINALIZED)
@dataclass
class VoiceFinalizedEvent(IpcEvent):
    """Confirms clean finalization of one logical Voice turn."""

    msg_id: str
    size_bytes: int
    event_type: EventType = field(default=EventType.VOICE_FINALIZED, init=False)


@register_event(EventType.VOICE_RESOURCE_PRESSURE)
@dataclass
class VoiceResourcePressureEvent(IpcEvent):
    """Reports Voice retention reaching the warning threshold."""

    used_bytes: int
    limit_bytes: int
    msg_id: Optional[str] = None
    event_type: EventType = field(
        default=EventType.VOICE_RESOURCE_PRESSURE,
        init=False,
    )


@register_event(EventType.VOICE_RESOURCE_LIMIT)
@dataclass
class VoiceResourceLimitEvent(IpcEvent):
    """Reports Voice retention refusal or resource-limit finalization."""

    used_bytes: int
    limit_bytes: int
    msg_id: Optional[str] = None
    event_type: EventType = field(
        default=EventType.VOICE_RESOURCE_LIMIT,
        init=False,
    )


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
    error_code: Optional[RuntimeErrorCode] = None
    error_detail: Optional[str] = None
    event_type: EventType = field(default=EventType.RETUNNEL_FAILED, init=False)


@register_event(EventType.TRANSPORT_STATE)
@dataclass
class TransportStateEvent(IpcEvent):
    """Broadcasts the current transport state for one peer or the whole daemon."""

    peer: str
    session_state: str
    onion: Optional[str] = None
    drop_tunnel: Optional[Dict[str, JsonValue]] = None
    focus_count: int = 0
    pending_live_count: int = 0
    auto_accept: bool = False
    event_type: EventType = field(default=EventType.TRANSPORT_STATE, init=False)


@register_event(EventType.READ_RECEIPT)
@dataclass
class ReadReceiptEvent(IpcEvent):
    """Signals that the peer consumed one message and acknowledges it as read."""

    alias: str
    msg_id: str
    onion: Optional[str] = None
    event_type: EventType = field(default=EventType.READ_RECEIPT, init=False)
