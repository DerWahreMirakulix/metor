"""Session, daemon-lock, and live-connection command DTOs."""

from dataclasses import dataclass, field
from typing import Optional

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.codes import (
    ClientUnlockMethod,
    LockedAcceptPolicy,
    NotificationPrivacy,
    QuickUnlockAction,
)
from metor.core.api.registry import register_command


@register_command(CommandType.INIT)
@dataclass
class InitCommand(IpcCommand):
    """Requests initialization and advertises the client IPC support range."""

    current_version: int
    min_supported: int
    command_type: CommandType = field(default=CommandType.INIT, init=False)


@register_command(CommandType.GET_CHAT_STARTUP_STATE)
@dataclass
class GetChatStartupStateCommand(IpcCommand):
    """Requests the chat-specific startup snapshot for first attach rendering."""

    command_type: CommandType = field(
        default=CommandType.GET_CHAT_STARTUP_STATE,
        init=False,
    )


@register_command(CommandType.GET_RUNTIME_SNAPSHOT)
@dataclass
class GetRuntimeSnapshotCommand(IpcCommand):
    """Requests one frontend-neutral aggregate runtime projection."""

    command_type: CommandType = field(
        default=CommandType.GET_RUNTIME_SNAPSHOT,
        init=False,
    )


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


@register_command(CommandType.SWITCH)
@dataclass
class SwitchCommand(IpcCommand):
    """Changes the active UI focus."""

    target: Optional[str] = None
    command_type: CommandType = field(default=CommandType.SWITCH, init=False)


@register_command(CommandType.UNLOCK)
@dataclass
class UnlockCommand(IpcCommand):
    """Unlocks a daemon that was started in locked mode."""

    password: str
    command_type: CommandType = field(default=CommandType.UNLOCK, init=False)


@register_command(CommandType.LOCK)
@dataclass
class LockCommand(IpcCommand):
    """Securely releases the active profile runtime without stopping IPC."""

    command_type: CommandType = field(default=CommandType.LOCK, init=False)


@register_command(CommandType.CHANGE_PASSWORD)
@dataclass(repr=False)
class ChangePasswordCommand(IpcCommand):
    """Rewraps an encrypted profile PMK after verifying its current password."""

    current_password: str
    new_password: str
    command_type: CommandType = field(
        default=CommandType.CHANGE_PASSWORD,
        init=False,
    )


@register_command(CommandType.AUTHENTICATE_SESSION)
@dataclass
class AuthenticateSessionCommand(IpcCommand):
    """Authenticates the current IPC session using one daemon-issued proof challenge."""

    proof: str
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


@register_command(CommandType.RESTRICT_CLIENT)
@dataclass
class RestrictClientCommand(IpcCommand):
    """Places only the requesting authenticated IPC session in restricted state."""

    unlock_method: ClientUnlockMethod = ClientUnlockMethod.PROFILE_PASSWORD
    continued_live_target: Optional[str] = None
    live_while_locked: bool = False
    accept_while_locked: LockedAcceptPolicy = LockedAcceptPolicy.NONE
    notification_privacy: NotificationPrivacy = NotificationPrivacy.OFF
    device_lifecycle: bool = False
    command_type: CommandType = field(
        default=CommandType.RESTRICT_CLIENT,
        init=False,
    )


@register_command(CommandType.REAUTHORIZE_CLIENT)
@dataclass(repr=False)
class ReauthorizeClientCommand(IpcCommand):
    """Reauthorizes one restricted session using its configured proof method."""

    method: ClientUnlockMethod
    proof: Optional[str] = None
    command_type: CommandType = field(
        default=CommandType.REAUTHORIZE_CLIENT,
        init=False,
    )


@register_command(CommandType.CONFIGURE_QUICK_UNLOCK)
@dataclass(repr=False)
class ConfigureQuickUnlockCommand(IpcCommand):
    """Installs or removes memory-hard PIN verifier material."""

    action: QuickUnlockAction
    salt: Optional[str] = None
    verifier: Optional[str] = None
    command_type: CommandType = field(
        default=CommandType.CONFIGURE_QUICK_UNLOCK,
        init=False,
    )
