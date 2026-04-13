"""Facade exports for strict command DTO packages."""

from metor.core.api.commands.address import GenerateAddressCommand, GetAddressCommand
from metor.core.api.commands.contacts import (
    AddContactCommand,
    ClearContactsCommand,
    GetContactsListCommand,
    RemoveContactCommand,
    RenameContactCommand,
)
from metor.core.api.commands.history import (
    ClearHistoryCommand,
    GetHistoryCommand,
    GetRawHistoryCommand,
)
from metor.core.api.commands.messages import (
    ClearMessagesCommand,
    FallbackCommand,
    GetInboxCommand,
    GetMessagesCommand,
    MarkReadCommand,
    MsgCommand,
    SendDropCommand,
)
from metor.core.api.commands.profile import (
    AddProfileCommand,
    MigrateProfileSecurityCommand,
    RemoveProfileCommand,
    RenameProfileCommand,
    SetDefaultProfileCommand,
)
from metor.core.api.commands.session import (
    AcceptCommand,
    AuthenticateSessionCommand,
    ConnectCommand,
    DisconnectCommand,
    GetConnectionsCommand,
    InitCommand,
    RegisterLiveConsumerCommand,
    RejectCommand,
    RetunnelCommand,
    SwitchCommand,
    UnlockCommand,
)
from metor.core.api.commands.settings import (
    GetConfigCommand,
    GetSettingCommand,
    SetConfigCommand,
    SetSettingCommand,
    SyncConfigCommand,
)
from metor.core.api.commands.system import ClearProfileDbCommand, SelfDestructCommand


__all__ = [
    'InitCommand',
    'RegisterLiveConsumerCommand',
    'GetConnectionsCommand',
    'ConnectCommand',
    'DisconnectCommand',
    'AcceptCommand',
    'RejectCommand',
    'SwitchCommand',
    'UnlockCommand',
    'AuthenticateSessionCommand',
    'RetunnelCommand',
    'GetContactsListCommand',
    'AddContactCommand',
    'RemoveContactCommand',
    'RenameContactCommand',
    'ClearContactsCommand',
    'AddProfileCommand',
    'MigrateProfileSecurityCommand',
    'RemoveProfileCommand',
    'RenameProfileCommand',
    'SetDefaultProfileCommand',
    'MsgCommand',
    'SendDropCommand',
    'GetInboxCommand',
    'MarkReadCommand',
    'FallbackCommand',
    'GetHistoryCommand',
    'GetRawHistoryCommand',
    'ClearHistoryCommand',
    'GetMessagesCommand',
    'ClearMessagesCommand',
    'GetAddressCommand',
    'GenerateAddressCommand',
    'SetSettingCommand',
    'GetSettingCommand',
    'SetConfigCommand',
    'GetConfigCommand',
    'SyncConfigCommand',
    'ClearProfileDbCommand',
    'SelfDestructCommand',
]
