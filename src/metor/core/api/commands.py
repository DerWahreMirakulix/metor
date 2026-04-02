"""Strict command DTOs for the UI-to-daemon IPC boundary."""

from dataclasses import dataclass, field
from typing import Optional, Union

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.registry import register_command


@register_command(CommandType.INIT)
@dataclass
class InitCommand(IpcCommand):
    """Requests daemon-session initialization."""

    command_type: CommandType = field(default=CommandType.INIT, init=False)


@register_command(CommandType.REGISTER_LIVE_CONSUMER)
@dataclass
class RegisterLiveConsumerCommand(IpcCommand):
    """Marks the current IPC session as an interactive live consumer."""

    command_type: CommandType = field(
        default=CommandType.REGISTER_LIVE_CONSUMER,
        init=False,
    )


@register_command(CommandType.GET_CONNECTIONS)
@dataclass
class GetConnectionsCommand(IpcCommand):
    """Requests the current connection state."""

    is_header: bool = False
    command_type: CommandType = field(
        default=CommandType.GET_CONNECTIONS,
        init=False,
    )


@register_command(CommandType.GET_CONTACTS_LIST)
@dataclass
class GetContactsListCommand(IpcCommand):
    """Requests the structured address book."""

    chat_mode: bool = False
    command_type: CommandType = field(
        default=CommandType.GET_CONTACTS_LIST,
        init=False,
    )


@register_command(CommandType.CONNECT)
@dataclass
class ConnectCommand(IpcCommand):
    """Requests a live connection to a target peer."""

    target: str
    command_type: CommandType = field(default=CommandType.CONNECT, init=False)


@register_command(CommandType.DISCONNECT)
@dataclass
class DisconnectCommand(IpcCommand):
    """Requests disconnection from an active peer."""

    target: str
    command_type: CommandType = field(default=CommandType.DISCONNECT, init=False)


@register_command(CommandType.ACCEPT)
@dataclass
class AcceptCommand(IpcCommand):
    """Accepts a pending live connection."""

    target: str
    command_type: CommandType = field(default=CommandType.ACCEPT, init=False)


@register_command(CommandType.REJECT)
@dataclass
class RejectCommand(IpcCommand):
    """Rejects a pending live connection."""

    target: str
    command_type: CommandType = field(default=CommandType.REJECT, init=False)


@register_command(CommandType.MSG)
@dataclass
class MsgCommand(IpcCommand):
    """Sends a live chat message to a peer."""

    target: str
    text: str
    msg_id: str
    command_type: CommandType = field(default=CommandType.MSG, init=False)


@register_command(CommandType.ADD_CONTACT)
@dataclass
class AddContactCommand(IpcCommand):
    """Adds a new contact or promotes a discovered peer."""

    alias: str
    onion: Optional[str] = None
    command_type: CommandType = field(default=CommandType.ADD_CONTACT, init=False)


@register_command(CommandType.REMOVE_CONTACT)
@dataclass
class RemoveContactCommand(IpcCommand):
    """Removes a saved contact or discovered peer."""

    alias: str
    command_type: CommandType = field(
        default=CommandType.REMOVE_CONTACT,
        init=False,
    )


@register_command(CommandType.RENAME_CONTACT)
@dataclass
class RenameContactCommand(IpcCommand):
    """Renames an existing contact or discovered peer."""

    old_alias: str
    new_alias: str
    command_type: CommandType = field(
        default=CommandType.RENAME_CONTACT,
        init=False,
    )


@register_command(CommandType.CLEAR_CONTACTS)
@dataclass
class ClearContactsCommand(IpcCommand):
    """Clears the complete address book."""

    command_type: CommandType = field(
        default=CommandType.CLEAR_CONTACTS,
        init=False,
    )


@register_command(CommandType.SWITCH)
@dataclass
class SwitchCommand(IpcCommand):
    """Changes the active UI focus."""

    target: Optional[str] = None
    command_type: CommandType = field(default=CommandType.SWITCH, init=False)


@register_command(CommandType.SEND_DROP)
@dataclass
class SendDropCommand(IpcCommand):
    """Queues an asynchronous offline message."""

    target: str
    text: str
    msg_id: str
    command_type: CommandType = field(default=CommandType.SEND_DROP, init=False)


@register_command(CommandType.GET_INBOX)
@dataclass
class GetInboxCommand(IpcCommand):
    """Requests unread-message counters."""

    command_type: CommandType = field(default=CommandType.GET_INBOX, init=False)


@register_command(CommandType.MARK_READ)
@dataclass
class MarkReadCommand(IpcCommand):
    """Reads and clears unread messages for a peer."""

    target: str
    command_type: CommandType = field(default=CommandType.MARK_READ, init=False)


@register_command(CommandType.FALLBACK)
@dataclass
class FallbackCommand(IpcCommand):
    """Forces pending live messages into the drop queue."""

    target: str
    command_type: CommandType = field(default=CommandType.FALLBACK, init=False)


@register_command(CommandType.GET_HISTORY)
@dataclass
class GetHistoryCommand(IpcCommand):
    """Requests connection event history."""

    target: Optional[str] = None
    limit: Optional[int] = None
    command_type: CommandType = field(default=CommandType.GET_HISTORY, init=False)


@register_command(CommandType.CLEAR_HISTORY)
@dataclass
class ClearHistoryCommand(IpcCommand):
    """Clears connection event history."""

    target: Optional[str] = None
    command_type: CommandType = field(default=CommandType.CLEAR_HISTORY, init=False)


@register_command(CommandType.GET_MESSAGES)
@dataclass
class GetMessagesCommand(IpcCommand):
    """Requests stored message history."""

    target: Optional[str] = None
    limit: Optional[int] = None
    command_type: CommandType = field(default=CommandType.GET_MESSAGES, init=False)


@register_command(CommandType.CLEAR_MESSAGES)
@dataclass
class ClearMessagesCommand(IpcCommand):
    """Clears stored message history."""

    target: Optional[str] = None
    non_contacts_only: bool = False
    command_type: CommandType = field(
        default=CommandType.CLEAR_MESSAGES,
        init=False,
    )


@register_command(CommandType.GET_ADDRESS)
@dataclass
class GetAddressCommand(IpcCommand):
    """Requests the current onion address."""

    command_type: CommandType = field(
        default=CommandType.GET_ADDRESS,
        init=False,
    )


@register_command(CommandType.GENERATE_ADDRESS)
@dataclass
class GenerateAddressCommand(IpcCommand):
    """Requests generation of a new onion address."""

    command_type: CommandType = field(
        default=CommandType.GENERATE_ADDRESS,
        init=False,
    )


@register_command(CommandType.CLEAR_PROFILE_DB)
@dataclass
class ClearProfileDbCommand(IpcCommand):
    """Requests a full profile-database wipe."""

    command_type: CommandType = field(
        default=CommandType.CLEAR_PROFILE_DB,
        init=False,
    )


@register_command(CommandType.SET_SETTING)
@dataclass
class SetSettingCommand(IpcCommand):
    """Updates a global setting."""

    setting_key: str
    setting_value: Union[str, int, float, bool]
    command_type: CommandType = field(default=CommandType.SET_SETTING, init=False)


@register_command(CommandType.GET_SETTING)
@dataclass
class GetSettingCommand(IpcCommand):
    """Requests a global setting value."""

    setting_key: str
    command_type: CommandType = field(default=CommandType.GET_SETTING, init=False)


@register_command(CommandType.SET_CONFIG)
@dataclass
class SetConfigCommand(IpcCommand):
    """Updates a profile-specific configuration override."""

    setting_key: str
    setting_value: Union[str, int, float, bool]
    command_type: CommandType = field(default=CommandType.SET_CONFIG, init=False)


@register_command(CommandType.GET_CONFIG)
@dataclass
class GetConfigCommand(IpcCommand):
    """Requests a profile-specific configuration value."""

    setting_key: str
    command_type: CommandType = field(default=CommandType.GET_CONFIG, init=False)


@register_command(CommandType.SYNC_CONFIG)
@dataclass
class SyncConfigCommand(IpcCommand):
    """Syncs profile configuration overrides with global settings."""

    command_type: CommandType = field(default=CommandType.SYNC_CONFIG, init=False)


@register_command(CommandType.SELF_DESTRUCT)
@dataclass
class SelfDestructCommand(IpcCommand):
    """Triggers daemon self-destruction."""

    command_type: CommandType = field(
        default=CommandType.SELF_DESTRUCT,
        init=False,
    )


@register_command(CommandType.UNLOCK)
@dataclass
class UnlockCommand(IpcCommand):
    """Unlocks a daemon that was started in locked mode."""

    password: str
    command_type: CommandType = field(default=CommandType.UNLOCK, init=False)


@register_command(CommandType.AUTHENTICATE_SESSION)
@dataclass
class AuthenticateSessionCommand(IpcCommand):
    """Authenticates the current IPC session when local auth is required."""

    password: str
    command_type: CommandType = field(
        default=CommandType.AUTHENTICATE_SESSION,
        init=False,
    )


@register_command(CommandType.RETUNNEL)
@dataclass
class RetunnelCommand(IpcCommand):
    """Retunnels an active connection over a new Tor circuit."""

    target: str
    command_type: CommandType = field(default=CommandType.RETUNNEL, init=False)
