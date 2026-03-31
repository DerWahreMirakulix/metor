"""
Module defining the Data Transfer Objects (DTOs) for inbound Daemon commands.
Utilizes dynamic decorators for registry mapping.
"""

from dataclasses import dataclass, field
from typing import Optional, Union

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import Action
from metor.core.api.registry import register_command


@register_command(Action.INIT)
@dataclass
class InitCommand(IpcCommand):
    """
    Data Transfer Object for initializing the daemon session.

    Attributes:
        action (Action): The strict IPC action code.
    """

    action: Action = field(default=Action.INIT, init=False)


@register_command(Action.GET_CONNECTIONS)
@dataclass
class GetConnectionsCommand(IpcCommand):
    """
    Data Transfer Object for requesting the current connection state.

    Attributes:
        is_header (bool): Flag indicating if the request is for the UI header.
        action (Action): The strict IPC action code.
    """

    is_header: bool = False
    action: Action = field(default=Action.GET_CONNECTIONS, init=False)


@register_command(Action.GET_CONTACTS_LIST)
@dataclass
class GetContactsListCommand(IpcCommand):
    """
    Data Transfer Object for retrieving the address book.

    Attributes:
        chat_mode (bool): Flag indicating if the data should be formatted for chat mode.
        action (Action): The strict IPC action code.
    """

    chat_mode: bool = False
    action: Action = field(default=Action.GET_CONTACTS_LIST, init=False)


@register_command(Action.CONNECT)
@dataclass
class ConnectCommand(IpcCommand):
    """
    Data Transfer Object for initiating a connection to a remote peer.

    Attributes:
        target (str): The target alias or onion address.
        action (Action): The strict IPC action code.
    """

    target: str
    action: Action = field(default=Action.CONNECT, init=False)


@register_command(Action.DISCONNECT)
@dataclass
class DisconnectCommand(IpcCommand):
    """
    Data Transfer Object for terminating an active connection.

    Attributes:
        target (str): The target alias or onion address.
        action (Action): The strict IPC action code.
    """

    target: str
    action: Action = field(default=Action.DISCONNECT, init=False)


@register_command(Action.ACCEPT)
@dataclass
class AcceptCommand(IpcCommand):
    """
    Data Transfer Object for accepting a pending connection request.

    Attributes:
        target (str): The target alias or onion address.
        action (Action): The strict IPC action code.
    """

    target: str
    action: Action = field(default=Action.ACCEPT, init=False)


@register_command(Action.REJECT)
@dataclass
class RejectCommand(IpcCommand):
    """
    Data Transfer Object for rejecting a pending connection request.

    Attributes:
        target (str): The target alias or onion address.
        action (Action): The strict IPC action code.
    """

    target: str
    action: Action = field(default=Action.REJECT, init=False)


@register_command(Action.MSG)
@dataclass
class MsgCommand(IpcCommand):
    """
    Data Transfer Object for sending a live chat message.

    Attributes:
        target (str): The target alias or onion address.
        text (str): The message payload.
        msg_id (str): The unique message identifier (UUID).
        action (Action): The strict IPC action code.
    """

    target: str
    text: str
    msg_id: str
    action: Action = field(default=Action.MSG, init=False)


@register_command(Action.ADD_CONTACT)
@dataclass
class AddContactCommand(IpcCommand):
    """
    Data Transfer Object for adding a new contact or saving a RAM alias.

    Attributes:
        alias (str): The chosen name for the contact.
        onion (Optional[str]): The remote onion identity.
        action (Action): The strict IPC action code.
    """

    alias: str
    onion: Optional[str] = None
    action: Action = field(default=Action.ADD_CONTACT, init=False)


@register_command(Action.REMOVE_CONTACT)
@dataclass
class RemoveContactCommand(IpcCommand):
    """
    Data Transfer Object for removing a saved contact.

    Attributes:
        alias (str): The alias of the contact to remove.
        action (Action): The strict IPC action code.
    """

    alias: str
    action: Action = field(default=Action.REMOVE_CONTACT, init=False)


@register_command(Action.RENAME_CONTACT)
@dataclass
class RenameContactCommand(IpcCommand):
    """
    Data Transfer Object for renaming an existing contact.

    Attributes:
        old_alias (str): The current alias.
        new_alias (str): The desired new alias.
        action (Action): The strict IPC action code.
    """

    old_alias: str
    new_alias: str
    action: Action = field(default=Action.RENAME_CONTACT, init=False)


@register_command(Action.CLEAR_CONTACTS)
@dataclass
class ClearContactsCommand(IpcCommand):
    """
    Data Transfer Object for wiping the entire address book.

    Attributes:
        action (Action): The strict IPC action code.
    """

    action: Action = field(default=Action.CLEAR_CONTACTS, init=False)


@register_command(Action.SWITCH)
@dataclass
class SwitchCommand(IpcCommand):
    """
    Data Transfer Object for changing the active UI focus.

    Attributes:
        target (Optional[str]): The alias to focus on, or None to clear focus.
        action (Action): The strict IPC action code.
    """

    target: Optional[str] = None
    action: Action = field(default=Action.SWITCH, init=False)


@register_command(Action.SEND_DROP)
@dataclass
class SendDropCommand(IpcCommand):
    """
    Data Transfer Object for queuing an asynchronous offline message.

    Attributes:
        target (str): The destination alias or onion address.
        text (str): The message payload.
        cli_mode (bool): Flag indicating if the request originated from the CLI.
        action (Action): The strict IPC action code.
    """

    target: str
    text: str
    cli_mode: bool = False
    action: Action = field(default=Action.SEND_DROP, init=False)


@register_command(Action.GET_INBOX)
@dataclass
class GetInboxCommand(IpcCommand):
    """
    Data Transfer Object for requesting unread message counts.

    Attributes:
        cli_mode (bool): Flag indicating if the request originated from the CLI.
        action (Action): The strict IPC action code.
    """

    cli_mode: bool = False
    action: Action = field(default=Action.GET_INBOX, init=False)


@register_command(Action.MARK_READ)
@dataclass
class MarkReadCommand(IpcCommand):
    """
    Data Transfer Object for reading and clearing messages from the inbox.

    Attributes:
        target (str): The target alias or onion address.
        cli_mode (bool): Flag indicating if the request originated from the CLI.
        action (Action): The strict IPC action code.
    """

    target: str
    cli_mode: bool = False
    action: Action = field(default=Action.MARK_READ, init=False)


@register_command(Action.FALLBACK)
@dataclass
class FallbackCommand(IpcCommand):
    """
    Data Transfer Object for forcing unacknowledged messages into the drop queue.

    Attributes:
        target (str): The target alias or onion address.
        action (Action): The strict IPC action code.
    """

    target: str
    action: Action = field(default=Action.FALLBACK, init=False)


@register_command(Action.GET_HISTORY)
@dataclass
class GetHistoryCommand(IpcCommand):
    """
    Data Transfer Object for retrieving connection event logs.

    Attributes:
        target (Optional[str]): The specific alias or onion to filter by.
        limit (Optional[int]): The maximum number of events to retrieve.
        action (Action): The strict IPC action code.
    """

    target: Optional[str] = None
    limit: Optional[int] = None
    action: Action = field(default=Action.GET_HISTORY, init=False)


@register_command(Action.CLEAR_HISTORY)
@dataclass
class ClearHistoryCommand(IpcCommand):
    """
    Data Transfer Object for deleting connection event logs.

    Attributes:
        target (Optional[str]): The specific alias or onion to clear.
        action (Action): The strict IPC action code.
    """

    target: Optional[str] = None
    action: Action = field(default=Action.CLEAR_HISTORY, init=False)


@register_command(Action.GET_MESSAGES)
@dataclass
class GetMessagesCommand(IpcCommand):
    """
    Data Transfer Object for retrieving past chat history.

    Attributes:
        target (Optional[str]): The specific alias or onion to retrieve messages for.
        limit (Optional[int]): The maximum number of messages to retrieve.
        action (Action): The strict IPC action code.
    """

    target: Optional[str] = None
    limit: Optional[int] = None
    action: Action = field(default=Action.GET_MESSAGES, init=False)


@register_command(Action.CLEAR_MESSAGES)
@dataclass
class ClearMessagesCommand(IpcCommand):
    """
    Data Transfer Object for deleting past chat history.

    Attributes:
        target (Optional[str]): The specific alias or onion to clear messages for.
        non_contacts_only (bool): Restricts deletion to unsaved peers.
        action (Action): The strict IPC action code.
    """

    target: Optional[str] = None
    non_contacts_only: bool = False
    action: Action = field(default=Action.CLEAR_MESSAGES, init=False)


@register_command(Action.GET_ADDRESS)
@dataclass
class GetAddressCommand(IpcCommand):
    """
    Data Transfer Object for retrieving the current hidden service address.

    Attributes:
        action (Action): The strict IPC action code.
    """

    action: Action = field(default=Action.GET_ADDRESS, init=False)


@register_command(Action.GENERATE_ADDRESS)
@dataclass
class GenerateAddressCommand(IpcCommand):
    """
    Data Transfer Object for generating a new hidden service address.

    Attributes:
        action (Action): The strict IPC action code.
    """

    action: Action = field(default=Action.GENERATE_ADDRESS, init=False)


@register_command(Action.CLEAR_PROFILE_DB)
@dataclass
class ClearProfileDbCommand(IpcCommand):
    """
    Data Transfer Object for completely wiping a profile's SQLite database.

    Attributes:
        action (Action): The strict IPC action code.
    """

    action: Action = field(default=Action.CLEAR_PROFILE_DB, init=False)


@register_command(Action.SET_SETTING)
@dataclass
class SetSettingCommand(IpcCommand):
    """
    Data Transfer Object for updating a global setting.

    Attributes:
        setting_key (str): The configuration key to modify.
        setting_value (Union[str, int, float, bool]): The new strictly typed value.
        action (Action): The strict IPC action code.
    """

    setting_key: str
    setting_value: Union[str, int, float, bool]
    action: Action = field(default=Action.SET_SETTING, init=False)


@register_command(Action.GET_SETTING)
@dataclass
class GetSettingCommand(IpcCommand):
    """
    Data Transfer Object for retrieving a global setting.

    Attributes:
        setting_key (str): The configuration key to retrieve.
        action (Action): The strict IPC action code.
    """

    setting_key: str
    action: Action = field(default=Action.GET_SETTING, init=False)


@register_command(Action.SET_CONFIG)
@dataclass
class SetConfigCommand(IpcCommand):
    """
    Data Transfer Object for updating a profile-specific config override.

    Attributes:
        setting_key (str): The configuration key to modify.
        setting_value (Union[str, int, float, bool]): The new strictly typed value.
        action (Action): The strict IPC action code.
    """

    setting_key: str
    setting_value: Union[str, int, float, bool]
    action: Action = field(default=Action.SET_CONFIG, init=False)


@register_command(Action.GET_CONFIG)
@dataclass
class GetConfigCommand(IpcCommand):
    """
    Data Transfer Object for retrieving a profile-specific config override.

    Attributes:
        setting_key (str): The configuration key to retrieve.
        action (Action): The strict IPC action code.
    """

    setting_key: str
    action: Action = field(default=Action.GET_CONFIG, init=False)


@register_command(Action.SYNC_CONFIG)
@dataclass
class SyncConfigCommand(IpcCommand):
    """
    Data Transfer Object for wiping all profile-specific settings to restore the global cascade.

    Attributes:
        action (Action): The strict IPC action code.
    """

    action: Action = field(default=Action.SYNC_CONFIG, init=False)


@register_command(Action.SELF_DESTRUCT)
@dataclass
class SelfDestructCommand(IpcCommand):
    """
    Data Transfer Object for initiating the daemon self-destruct and data purge protocol.

    Attributes:
        action (Action): The strict IPC action code.
    """

    action: Action = field(default=Action.SELF_DESTRUCT, init=False)


@register_command(Action.UNLOCK)
@dataclass
class UnlockCommand(IpcCommand):
    """
    Data Transfer Object for authenticating and unlocking a remote daemon.

    Attributes:
        password (str): The master password.
        action (Action): The strict IPC action code.
    """

    password: str
    action: Action = field(default=Action.UNLOCK, init=False)


@register_command(Action.RETUNNEL)
@dataclass
class RetunnelCommand(IpcCommand):
    """
    Data Transfer Object for forcing a Tor circuit rotation and reconnecting.

    Attributes:
        target (str): The alias or onion address to retunnel.
        action (Action): The strict IPC action code.
    """

    target: str
    action: Action = field(default=Action.RETUNNEL, init=False)
