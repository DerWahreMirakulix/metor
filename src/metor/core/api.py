"""
Module defining the IPC API contract between the CLI/UI and the background Daemon.
Uses strictly-typed, polymorphic Data Transfer Objects (DTOs) for framework consistency.
"""

import json
import dataclasses
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Optional, List, Dict, Any, Type, Union


class Action(str, Enum):
    """Enumeration of commands sent from the UI/CLI to the Daemon."""

    INIT = 'init'
    GET_CONNECTIONS = 'get_connections'
    GET_CONTACTS_LIST = 'get_contacts_list'
    CONNECT = 'connect'
    DISCONNECT = 'disconnect'
    ACCEPT = 'accept'
    REJECT = 'reject'
    MSG = 'msg'
    ADD_CONTACT = 'add_contact'
    REMOVE_CONTACT = 'remove_contact'
    RENAME_CONTACT = 'rename_contact'
    CLEAR_CONTACTS = 'clear_contacts'
    SWITCH = 'switch'

    SEND_DROP = 'send_drop'
    GET_INBOX = 'get_inbox'
    MARK_READ = 'mark_read'
    FALLBACK = 'fallback'

    GET_HISTORY = 'get_history'
    CLEAR_HISTORY = 'clear_history'
    GET_MESSAGES = 'get_messages'
    CLEAR_MESSAGES = 'clear_messages'
    GET_ADDRESS = 'get_address'
    GENERATE_ADDRESS = 'generate_address'
    CLEAR_PROFILE_DB = 'clear_profile_db'

    SET_SETTING = 'set_setting'
    SELF_DESTRUCT = 'self_destruct'
    UNLOCK = 'unlock'


class EventType(str, Enum):
    """Enumeration of events broadcasted by the Daemon to the connected UIs."""

    INIT = 'init'
    INFO = 'info'
    SYSTEM = 'system'
    REMOTE_MSG = 'remote_msg'
    ACK = 'ack'
    CONNECTED = 'connected'
    DISCONNECTED = 'disconnected'
    RENAME_SUCCESS = 'rename_success'
    CONNECTIONS_STATE = 'connections_state'
    SWITCH_SUCCESS = 'switch_success'
    CONTACT_LIST = 'contact_list'
    CONTACT_REMOVED = 'contact_removed'

    INBOX_NOTIFICATION = 'inbox_notification'
    INBOX_DATA = 'inbox_data'
    MSG_FALLBACK_TO_DROP = 'msg_fallback_to_drop'

    CLI_RESPONSE = 'cli_response'


@dataclass
class IpcMessage:
    """Base class providing JSON serialization for all IPC messages."""

    def to_json(self) -> str:
        """
        Serializes the current DTO into a JSON string, excluding None values.

        Args:
            None

        Returns:
            str: The serialized JSON string.
        """
        data: Dict[str, Any] = {k: v for k, v in asdict(self).items() if v is not None}
        return json.dumps(data)


# --- BASE CLASSES ---


@dataclass
class IpcCommand(IpcMessage):
    """Base class for all commands sent to the Daemon."""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IpcCommand':
        """Factory method to instantiate the correct strict subclass."""
        action: Action = Action(data['action'])
        target_cls: Type['IpcCommand'] = _CMD_MAP[action]
        valid_keys: set[str] = {f.name for f in dataclasses.fields(target_cls)}
        kwargs: Dict[str, Any] = {
            k: v for k, v in data.items() if k in valid_keys and k != 'action'
        }
        return target_cls(**kwargs)


@dataclass
class IpcEvent(IpcMessage):
    """Base class for all events emitted by the Daemon."""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IpcEvent':
        """Factory method to instantiate the correct strict subclass."""
        event_type: EventType = EventType(data['type'])
        target_cls: Type['IpcEvent'] = _EVENT_MAP[event_type]
        valid_keys: set[str] = {f.name for f in dataclasses.fields(target_cls)}
        kwargs: Dict[str, Any] = {
            k: v for k, v in data.items() if k in valid_keys and k != 'type'
        }
        return target_cls(**kwargs)


# --- SPECIFIC COMMAND DTOS ---


@dataclass
class InitCommand(IpcCommand):
    action: Action = field(default=Action.INIT, init=False)


@dataclass
class GetConnectionsCommand(IpcCommand):
    is_header: bool = False
    action: Action = field(default=Action.GET_CONNECTIONS, init=False)


@dataclass
class GetContactsListCommand(IpcCommand):
    chat_mode: bool = False
    action: Action = field(default=Action.GET_CONTACTS_LIST, init=False)


@dataclass
class ConnectCommand(IpcCommand):
    target: str
    action: Action = field(default=Action.CONNECT, init=False)


@dataclass
class DisconnectCommand(IpcCommand):
    target: str
    action: Action = field(default=Action.DISCONNECT, init=False)


@dataclass
class AcceptCommand(IpcCommand):
    target: str
    action: Action = field(default=Action.ACCEPT, init=False)


@dataclass
class RejectCommand(IpcCommand):
    target: str
    action: Action = field(default=Action.REJECT, init=False)


@dataclass
class MsgCommand(IpcCommand):
    target: str
    text: str
    msg_id: str
    action: Action = field(default=Action.MSG, init=False)


@dataclass
class AddContactCommand(IpcCommand):
    alias: str
    onion: Optional[str] = None
    action: Action = field(default=Action.ADD_CONTACT, init=False)


@dataclass
class RemoveContactCommand(IpcCommand):
    alias: str
    action: Action = field(default=Action.REMOVE_CONTACT, init=False)


@dataclass
class RenameContactCommand(IpcCommand):
    old_alias: str
    new_alias: str
    action: Action = field(default=Action.RENAME_CONTACT, init=False)


@dataclass
class ClearContactsCommand(IpcCommand):
    action: Action = field(default=Action.CLEAR_CONTACTS, init=False)


@dataclass
class SwitchCommand(IpcCommand):
    target: Optional[str] = None
    action: Action = field(default=Action.SWITCH, init=False)


@dataclass
class SendDropCommand(IpcCommand):
    target: str
    text: str
    action: Action = field(default=Action.SEND_DROP, init=False)


@dataclass
class GetInboxCommand(IpcCommand):
    cli_mode: bool = False
    action: Action = field(default=Action.GET_INBOX, init=False)


@dataclass
class MarkReadCommand(IpcCommand):
    target: str
    cli_mode: bool = False
    action: Action = field(default=Action.MARK_READ, init=False)


@dataclass
class FallbackCommand(IpcCommand):
    target: str
    action: Action = field(default=Action.FALLBACK, init=False)


@dataclass
class GetHistoryCommand(IpcCommand):
    target: Optional[str] = None
    limit: Optional[int] = None
    action: Action = field(default=Action.GET_HISTORY, init=False)


@dataclass
class ClearHistoryCommand(IpcCommand):
    target: Optional[str] = None
    action: Action = field(default=Action.CLEAR_HISTORY, init=False)


@dataclass
class GetMessagesCommand(IpcCommand):
    target: Optional[str] = None
    limit: Optional[int] = None
    action: Action = field(default=Action.GET_MESSAGES, init=False)


@dataclass
class ClearMessagesCommand(IpcCommand):
    target: Optional[str] = None
    non_contacts_only: bool = False
    action: Action = field(default=Action.CLEAR_MESSAGES, init=False)


@dataclass
class GetAddressCommand(IpcCommand):
    action: Action = field(default=Action.GET_ADDRESS, init=False)


@dataclass
class GenerateAddressCommand(IpcCommand):
    action: Action = field(default=Action.GENERATE_ADDRESS, init=False)


@dataclass
class ClearProfileDbCommand(IpcCommand):
    action: Action = field(default=Action.CLEAR_PROFILE_DB, init=False)


@dataclass
class SetSettingCommand(IpcCommand):
    setting_key: str
    setting_value: Union[str, int, float, bool]
    action: Action = field(default=Action.SET_SETTING, init=False)


@dataclass
class SelfDestructCommand(IpcCommand):
    action: Action = field(default=Action.SELF_DESTRUCT, init=False)


@dataclass
class UnlockCommand(IpcCommand):
    password: str
    action: Action = field(default=Action.UNLOCK, init=False)


# --- SPECIFIC EVENT DTOS ---


@dataclass
class InitEvent(IpcEvent):
    onion: Optional[str] = None
    type: EventType = field(default=EventType.INIT, init=False)


@dataclass
class InfoEvent(IpcEvent):
    text: str
    alias: Optional[str] = None
    type: EventType = field(default=EventType.INFO, init=False)


@dataclass
class SystemEvent(IpcEvent):
    text: str
    type: EventType = field(default=EventType.SYSTEM, init=False)


@dataclass
class RemoteMsgEvent(IpcEvent):
    alias: str
    text: str
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
    text: str
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
class ContactListEvent(IpcEvent):
    text: str
    type: EventType = field(default=EventType.CONTACT_LIST, init=False)


@dataclass
class InboxNotificationEvent(IpcEvent):
    text: str
    alias: Optional[str] = None
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
class CliResponseEvent(IpcEvent):
    text: str
    success: bool = True
    type: EventType = field(default=EventType.CLI_RESPONSE, init=False)


# --- DYNAMIC MAPPERS ---

_CMD_MAP: Dict[Action, Type[IpcCommand]] = {
    Action.INIT: InitCommand,
    Action.GET_CONNECTIONS: GetConnectionsCommand,
    Action.GET_CONTACTS_LIST: GetContactsListCommand,
    Action.CONNECT: ConnectCommand,
    Action.DISCONNECT: DisconnectCommand,
    Action.ACCEPT: AcceptCommand,
    Action.REJECT: RejectCommand,
    Action.MSG: MsgCommand,
    Action.ADD_CONTACT: AddContactCommand,
    Action.REMOVE_CONTACT: RemoveContactCommand,
    Action.RENAME_CONTACT: RenameContactCommand,
    Action.CLEAR_CONTACTS: ClearContactsCommand,
    Action.SWITCH: SwitchCommand,
    Action.SEND_DROP: SendDropCommand,
    Action.GET_INBOX: GetInboxCommand,
    Action.MARK_READ: MarkReadCommand,
    Action.FALLBACK: FallbackCommand,
    Action.GET_HISTORY: GetHistoryCommand,
    Action.CLEAR_HISTORY: ClearHistoryCommand,
    Action.GET_MESSAGES: GetMessagesCommand,
    Action.CLEAR_MESSAGES: ClearMessagesCommand,
    Action.GET_ADDRESS: GetAddressCommand,
    Action.GENERATE_ADDRESS: GenerateAddressCommand,
    Action.CLEAR_PROFILE_DB: ClearProfileDbCommand,
    Action.SET_SETTING: SetSettingCommand,
    Action.SELF_DESTRUCT: SelfDestructCommand,
    Action.UNLOCK: UnlockCommand,
}

_EVENT_MAP: Dict[EventType, Type[IpcEvent]] = {
    EventType.INIT: InitEvent,
    EventType.INFO: InfoEvent,
    EventType.SYSTEM: SystemEvent,
    EventType.REMOTE_MSG: RemoteMsgEvent,
    EventType.ACK: AckEvent,
    EventType.CONNECTED: ConnectedEvent,
    EventType.DISCONNECTED: DisconnectedEvent,
    EventType.RENAME_SUCCESS: RenameSuccessEvent,
    EventType.CONTACT_REMOVED: ContactRemovedEvent,
    EventType.CONNECTIONS_STATE: ConnectionsStateEvent,
    EventType.SWITCH_SUCCESS: SwitchSuccessEvent,
    EventType.CONTACT_LIST: ContactListEvent,
    EventType.INBOX_NOTIFICATION: InboxNotificationEvent,
    EventType.INBOX_DATA: InboxDataEvent,
    EventType.MSG_FALLBACK_TO_DROP: MsgFallbackToDropEvent,
    EventType.CLI_RESPONSE: CliResponseEvent,
}
