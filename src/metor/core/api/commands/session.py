"""Session and live-connection command DTOs."""

from dataclasses import dataclass, field
from typing import Optional

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
