"""
Module defining the Data Transfer Objects (DTOs) for inbound Daemon commands.
"""

from dataclasses import dataclass, field
from typing import Optional, Union

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import Action


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
    cli_mode: bool = False
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
