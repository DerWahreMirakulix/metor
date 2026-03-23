"""
Module defining the IPC API contract between the CLI/UI and the background Daemon.
Uses strongly-typed Data Transfer Objects (DTOs) to eliminate raw dictionaries.
"""

import json
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Optional, List, Dict, Any


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

    # Async / Offline Actions
    SEND_DROP = 'send_drop'
    GET_INBOX = 'get_inbox'
    MARK_READ = 'mark_read'

    # CLI Proxy Actions (Remote Mode)
    GET_HISTORY = 'get_history'
    CLEAR_HISTORY = 'clear_history'
    GET_MESSAGES = 'get_messages'
    CLEAR_MESSAGES = 'clear_messages'
    GET_ADDRESS = 'get_address'
    GENERATE_ADDRESS = 'generate_address'


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

    # Async / Offline Events
    INBOX_NOTIFICATION = 'inbox_notification'
    INBOX_DATA = 'inbox_data'
    MSG_FALLBACK_TO_DROP = 'msg_fallback_to_drop'

    # CLI Proxy Events
    CLI_RESPONSE = 'cli_response'


@dataclass
class IpcMessage:
    """Base class providing JSON serialization for all IPC messages."""

    def to_json(self) -> str:
        """
        Serializes the current DTO into a JSON string, excluding any None values.

        Args:
            None

        Returns:
            str: The serialized JSON string representing the object.
        """
        data: Dict[str, Any] = {k: v for k, v in asdict(self).items() if v is not None}
        return json.dumps(data)


@dataclass
class IpcCommand(IpcMessage):
    """Data Transfer Object for commands targeting the Daemon."""

    action: Action
    target: Optional[str] = None
    text: Optional[str] = None
    msg_id: Optional[str] = None
    alias: Optional[str] = None
    onion: Optional[str] = None
    old_alias: Optional[str] = None
    new_alias: Optional[str] = None
    is_header: bool = False
    chat_mode: bool = False
    limit: int = 50

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IpcCommand':
        """
        Safely parses a raw dictionary into an IpcCommand DTO.

        Args:
            data (Dict[str, Any]): The raw dictionary received over the socket.

        Returns:
            IpcCommand: The strongly-typed command object.
        """
        return cls(
            action=Action(data['action']),
            target=data.get('target'),
            text=data.get('text'),
            msg_id=data.get('msg_id'),
            alias=data.get('alias'),
            onion=data.get('onion'),
            old_alias=data.get('old_alias'),
            new_alias=data.get('new_alias'),
            is_header=data.get('is_header', False),
            chat_mode=data.get('chat_mode', False),
            limit=data.get('limit', 50),
        )


@dataclass
class IpcEvent(IpcMessage):
    """Data Transfer Object for events broadcasted by the Daemon to the UI."""

    type: EventType
    text: Optional[str] = None
    alias: Optional[str] = None
    onion: Optional[str] = None
    msg_id: Optional[str] = None
    old_alias: Optional[str] = None
    new_alias: Optional[str] = None
    active: List[str] = field(default_factory=list)
    pending: List[str] = field(default_factory=list)
    contacts: List[str] = field(default_factory=list)
    msg_ids: List[str] = field(default_factory=list)
    inbox_counts: Dict[str, int] = field(default_factory=dict)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    is_header: bool = False
    is_demotion: bool = False
    history_updated: bool = False
    success: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IpcEvent':
        """
        Safely parses a raw dictionary into an IpcEvent DTO.

        Args:
            data (Dict[str, Any]): The raw dictionary received over the socket.

        Returns:
            IpcEvent: The strongly-typed event object.
        """
        return cls(
            type=EventType(data['type']),
            text=data.get('text'),
            alias=data.get('alias'),
            onion=data.get('onion'),
            msg_id=data.get('msg_id'),
            old_alias=data.get('old_alias'),
            new_alias=data.get('new_alias'),
            active=data.get('active', []),
            pending=data.get('pending', []),
            contacts=data.get('contacts', []),
            msg_ids=data.get('msg_ids', []),
            inbox_counts=data.get('inbox_counts', {}),
            messages=data.get('messages', []),
            is_header=data.get('is_header', False),
            is_demotion=data.get('is_demotion', False),
            history_updated=data.get('history_updated', False),
            success=data.get('success', True),
        )
