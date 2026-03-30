"""
Module defining the Data Transfer Objects (DTOs) for outbound Daemon events.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

# Local Package Imports
from metor.core.api.base import IpcEvent
from metor.core.api.codes import EventType, Action, TransCode


@dataclass
class InitEvent(IpcEvent):
    onion: Optional[str] = None
    type: EventType = field(default=EventType.INIT, init=False)


@dataclass
class RemoteMsgEvent(IpcEvent):
    alias: str
    text: str
    timestamp: Optional[str] = None
    type: EventType = field(default=EventType.REMOTE_MSG, init=False)


@dataclass
class AckEvent(IpcEvent):
    msg_id: str
    text: Optional[str] = None
    type: EventType = field(default=EventType.ACK, init=False)


@dataclass
class ConnectedEvent(IpcEvent):
    alias: str
    onion: Optional[str] = None
    type: EventType = field(default=EventType.CONNECTED, init=False)


@dataclass
class DisconnectedEvent(IpcEvent):
    alias: str
    type: EventType = field(default=EventType.DISCONNECTED, init=False)


@dataclass
class RenameSuccessEvent(IpcEvent):
    old_alias: str
    new_alias: str
    is_demotion: bool = False
    was_saved: bool = True
    type: EventType = field(default=EventType.RENAME_SUCCESS, init=False)


@dataclass
class ContactRemovedEvent(IpcEvent):
    alias: str
    type: EventType = field(default=EventType.CONTACT_REMOVED, init=False)


@dataclass
class ConnectionsStateEvent(IpcEvent):
    active: List[str]
    pending: List[str]
    contacts: List[str]
    is_header: bool = False
    type: EventType = field(default=EventType.CONNECTIONS_STATE, init=False)


@dataclass
class SwitchSuccessEvent(IpcEvent):
    alias: Optional[str] = None
    type: EventType = field(default=EventType.SWITCH_SUCCESS, init=False)


@dataclass
class ConnectionPendingEvent(IpcEvent):
    alias: Optional[str] = None
    type: EventType = field(default=EventType.CONNECTION_PENDING, init=False)


@dataclass
class ConnectionAutoAcceptedEvent(IpcEvent):
    alias: Optional[str] = None
    type: EventType = field(default=EventType.CONNECTION_AUTO_ACCEPTED, init=False)


@dataclass
class ConnectionRetryEvent(IpcEvent):
    alias: Optional[str] = None
    attempt: int = 1
    max_retries: int = 3
    type: EventType = field(default=EventType.CONNECTION_RETRY, init=False)


@dataclass
class ConnectionFailedEvent(IpcEvent):
    alias: Optional[str] = None
    reason: str = ''
    type: EventType = field(default=EventType.CONNECTION_FAILED, init=False)


@dataclass
class IncomingConnectionEvent(IpcEvent):
    alias: Optional[str] = None
    type: EventType = field(default=EventType.INCOMING_CONNECTION, init=False)


@dataclass
class ConnectionRejectedEvent(IpcEvent):
    alias: Optional[str] = None
    by_remote: bool = False
    type: EventType = field(default=EventType.CONNECTION_REJECTED, init=False)


@dataclass
class TiebreakerRejectedEvent(IpcEvent):
    alias: Optional[str] = None
    type: EventType = field(default=EventType.TIEBREAKER_REJECTED, init=False)


@dataclass
class InboxNotificationEvent(IpcEvent):
    alias: Optional[str] = None
    count: int = 1
    type: EventType = field(default=EventType.INBOX_NOTIFICATION, init=False)


@dataclass
class InboxDataEvent(IpcEvent):
    alias: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    inbox_counts: Dict[str, int] = field(default_factory=dict)
    is_live_flush: bool = False
    type: EventType = field(default=EventType.INBOX_DATA, init=False)


@dataclass
class MsgFallbackToDropEvent(IpcEvent):
    msg_ids: List[str]
    type: EventType = field(default=EventType.MSG_FALLBACK_TO_DROP, init=False)


@dataclass
class NotificationEvent(IpcEvent):
    """Replaces old generic SystemEvent/InfoEvent. Used for asynchronous alerts."""

    code: TransCode
    params: Dict[str, Any] = field(default_factory=dict)
    type: EventType = field(default=EventType.NOTIFICATION, init=False)


@dataclass
class CommandResponseEvent(IpcEvent):
    """Standardized response to CLI/UI synchronous commands."""

    action: Action
    success: bool = True
    code: TransCode = TransCode.COMMAND_SUCCESS
    data: Dict[str, Any] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    type: EventType = field(default=EventType.COMMAND_RESPONSE, init=False)
