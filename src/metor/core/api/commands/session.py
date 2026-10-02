"""Session, daemon-lock, and live-connection command DTOs."""

from dataclasses import dataclass, field
from typing import Optional

from metor.shared import Constants

# Local Package Imports
from metor.core.api.base import IpcCommand
from metor.core.api.codes import CommandType
from metor.core.api.codes import (
    ClientUnlockMethod,
    NotificationPrivacy,
    QuickUnlockAction,
)
from metor.core.api.registry import register_command


@register_command(CommandType.FRONTEND_LEASE)
@dataclass(repr=False)
class FrontendLeaseCommand(IpcCommand):
    """Join or release the automatic daemon lifetime without profile authority."""

    frontend_id: str = field(
        metadata={'example': '0' * (2 * Constants.FRONTEND_LIFETIME_ID_BYTES)}
    )
    token: Optional[str] = None
    release: bool = False
    command_type: CommandType = field(default=CommandType.FRONTEND_LEASE, init=False)

    def __post_init__(self) -> None:
        """Reject malformed bounded identities before dispatch."""
        values = [(self.frontend_id, Constants.FRONTEND_LIFETIME_ID_BYTES)]
        if self.token is not None:
            values.append((self.token, Constants.FRONTEND_LIFETIME_TOKEN_BYTES))
        for value, size in values:
            if (
                not isinstance(value, str)
                or len(value) != 2 * size
                or any(character not in '0123456789abcdef' for character in value)
            ):
                raise ValueError('Invalid frontend lifetime identity')
        if type(self.release) is not bool:
            raise ValueError('Invalid frontend lifetime operation')


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
    context_generation: Optional[int] = None
    attempt_id: Optional[str] = None
    command_type: CommandType = field(default=CommandType.DISCONNECT, init=False)

    def __post_init__(self) -> None:
        """Validates mutually exclusive logical-context and outbound-attempt assertions.

        Args:
            None
        Returns:
            None
        """
        if self.context_generation is not None and (
            type(self.context_generation) is not int or self.context_generation <= 0
        ):
            raise ValueError('Invalid LIVE context generation')
        if self.attempt_id is not None and (
            not isinstance(self.attempt_id, str)
            or len(self.attempt_id) != 2 * Constants.LIVE_ATTEMPT_TOKEN_BYTES
            or any(character not in '0123456789abcdef' for character in self.attempt_id)
        ):
            raise ValueError('Invalid LIVE attempt identity')
        if self.context_generation is not None and self.attempt_id is not None:
            raise ValueError('LIVE end requires one exact identity')


@register_command(CommandType.ACCEPT)
@dataclass
class AcceptCommand(IpcCommand):
    """Accepts a pending live connection."""

    target: str
    action_handle: Optional[str] = None
    command_type: CommandType = field(default=CommandType.ACCEPT, init=False)


@register_command(CommandType.REJECT)
@dataclass
class RejectCommand(IpcCommand):
    """Rejects a pending live connection."""

    target: str
    action_handle: Optional[str] = None
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
    context_generation: Optional[int] = None
    command_type: CommandType = field(default=CommandType.RETUNNEL, init=False)

    def __post_init__(self) -> None:
        """Validates an optional exact active LIVE context assertion.

        Args:
            None
        Returns:
            None
        """
        if self.context_generation is not None and (
            type(self.context_generation) is not int or self.context_generation <= 0
        ):
            raise ValueError('context_generation must be a positive integer')


@register_command(CommandType.RESTRICT_CLIENT)
@dataclass
class RestrictClientCommand(IpcCommand):
    """Places only the requesting authenticated IPC session in restricted state."""

    unlock_method: ClientUnlockMethod = ClientUnlockMethod.PROFILE_PASSWORD
    notification_privacy: NotificationPrivacy = NotificationPrivacy.OFF
    device_lifecycle: bool = False
    accept_calls_locked: bool = False
    command_type: CommandType = field(
        default=CommandType.RESTRICT_CLIENT,
        init=False,
    )

    def __post_init__(self) -> None:
        """Rejects untyped privilege switches before session authorization."""
        for value in (self.device_lifecycle, self.accept_calls_locked):
            if type(value) is not bool:
                raise ValueError('Restricted policy requires a Boolean')
        self.unlock_method = ClientUnlockMethod(self.unlock_method)
        self.notification_privacy = NotificationPrivacy(self.notification_privacy)


@register_command(CommandType.GET_RESTRICTED_CLIENT_STATE)
@dataclass
class GetRestrictedClientStateCommand(IpcCommand):
    """Reads this client's currently effective restricted grants and permitted call metadata."""

    command_type: CommandType = field(
        default=CommandType.GET_RESTRICTED_CLIENT_STATE, init=False
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
