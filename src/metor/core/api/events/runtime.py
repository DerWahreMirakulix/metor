"""Runtime, auth, settings, and config IPC event DTOs."""

from dataclasses import dataclass, field
from typing import Optional

# Local Package Imports
from metor.core.api.base import IpcEvent
from metor.core.api.codes import ClientUnlockMethod, EventType
from metor.core.api.registry import register_event


@register_event(EventType.AUTH_REQUIRED)
@dataclass
class AuthRequiredEvent(IpcEvent):
    """Signals that the session must authenticate first."""

    challenge: Optional[str] = None
    salt: Optional[str] = None
    event_type: EventType = field(default=EventType.AUTH_REQUIRED, init=False)


@register_event(EventType.INVALID_PASSWORD)
@dataclass
class InvalidPasswordEvent(IpcEvent):
    """Signals that the supplied unlock password or session proof was invalid."""

    challenge: Optional[str] = None
    salt: Optional[str] = None
    event_type: EventType = field(default=EventType.INVALID_PASSWORD, init=False)


@register_event(EventType.LOCAL_AUTH_RATE_LIMITED)
@dataclass
class LocalAuthRateLimitedEvent(IpcEvent):
    """Signals that local daemon auth is temporarily rate-limited."""

    retry_after: int
    event_type: EventType = field(
        default=EventType.LOCAL_AUTH_RATE_LIMITED,
        init=False,
    )


@register_event(EventType.DB_CORRUPTED)
@dataclass
class DatabaseCorruptedEvent(IpcEvent):
    """Signals that the profile database is corrupted."""

    event_type: EventType = field(default=EventType.DB_CORRUPTED, init=False)


@register_event(EventType.ALREADY_UNLOCKED)
@dataclass
class AlreadyUnlockedEvent(IpcEvent):
    """Signals that the daemon is already unlocked."""

    event_type: EventType = field(default=EventType.ALREADY_UNLOCKED, init=False)


@register_event(EventType.SESSION_AUTHENTICATED)
@dataclass
class SessionAuthenticatedEvent(IpcEvent):
    """Signals that the current session authenticated successfully."""

    event_type: EventType = field(
        default=EventType.SESSION_AUTHENTICATED,
        init=False,
    )


@register_event(EventType.CLIENT_RESTRICTED)
@dataclass
class ClientRestrictedEvent(IpcEvent):
    """Confirms per-session restriction and supplies a one-use unlock challenge."""

    unlock_method: ClientUnlockMethod
    challenge: Optional[str] = None
    salt: Optional[str] = None
    device_lifecycle: bool = False
    event_type: EventType = field(default=EventType.CLIENT_RESTRICTED, init=False)


@register_event(EventType.CLIENT_REAUTHORIZED)
@dataclass
class ClientReauthorizedEvent(IpcEvent):
    """Confirms that only the requesting restricted client was reauthorized."""

    event_type: EventType = field(default=EventType.CLIENT_REAUTHORIZED, init=False)


@register_event(EventType.CLIENT_ACCESS_RESTRICTED)
@dataclass
class ClientAccessRestrictedEvent(IpcEvent):
    """Rejects an operation outside the locked-session policy."""

    command: str
    event_type: EventType = field(
        default=EventType.CLIENT_ACCESS_RESTRICTED,
        init=False,
    )


@register_event(EventType.QUICK_UNLOCK_CONFIGURED)
@dataclass
class QuickUnlockConfiguredEvent(IpcEvent):
    """Confirms installation or removal of the PIN verifier."""

    enabled: bool
    event_type: EventType = field(
        default=EventType.QUICK_UNLOCK_CONFIGURED,
        init=False,
    )


@register_event(EventType.QUICK_UNLOCK_FAILED)
@dataclass
class QuickUnlockFailedEvent(IpcEvent):
    """Rejects invalid quick-unlock verifier configuration or proof."""

    password_required: bool = False
    challenge: Optional[str] = None
    salt: Optional[str] = None
    event_type: EventType = field(default=EventType.QUICK_UNLOCK_FAILED, init=False)


@register_event(EventType.SELF_DESTRUCT_INITIATED)
@dataclass
class SelfDestructInitiatedEvent(IpcEvent):
    """Signals that daemon self-destruction has started."""

    event_type: EventType = field(
        default=EventType.SELF_DESTRUCT_INITIATED,
        init=False,
    )


@register_event(EventType.SELF_DESTRUCT_COMPLETED)
@dataclass
class SelfDestructCompletedEvent(IpcEvent):
    """Signals that protected key access was destroyed before cleanup completion."""

    event_type: EventType = field(
        default=EventType.SELF_DESTRUCT_COMPLETED,
        init=False,
    )


@register_event(EventType.SELF_DESTRUCT_KEY_DESTROYED)
@dataclass
class SelfDestructKeyDestroyedEvent(IpcEvent):
    """Confirms irreversible destruction of protected profile-key access."""

    profile: str
    event_type: EventType = field(
        default=EventType.SELF_DESTRUCT_KEY_DESTROYED,
        init=False,
    )


@register_event(EventType.SELF_DESTRUCT_CLEANUP_FAILED)
@dataclass
class SelfDestructCleanupFailedEvent(IpcEvent):
    """Reports the exact failed destruction phase and irreversible state."""

    profile: str
    phase: str = 'cleanup'
    key_destroyed: bool = True
    event_type: EventType = field(
        default=EventType.SELF_DESTRUCT_CLEANUP_FAILED,
        init=False,
    )


@register_event(EventType.PROFILE_EXIT_PREPARED)
@dataclass
class ProfileExitPreparedEvent(IpcEvent):
    """Confirms durable local transition and hard lock for normal profile exit."""

    profile: str
    event_type: EventType = field(
        default=EventType.PROFILE_EXIT_PREPARED,
        init=False,
    )


@register_event(EventType.RUNTIME_STATE_CHANGED)
@dataclass
class RuntimeStateChangedEvent(IpcEvent):
    """Invalidates one content-free canonical runtime projection scope."""

    scope: str
    onion: Optional[str] = None
    event_type: EventType = field(
        default=EventType.RUNTIME_STATE_CHANGED,
        init=False,
    )


@register_event(EventType.PASSWORD_CHANGED)
@dataclass
class PasswordChangedEvent(IpcEvent):
    """Signals that the current profile PMK was rewrapped successfully."""

    event_type: EventType = field(default=EventType.PASSWORD_CHANGED, init=False)


@register_event(EventType.PASSWORD_CHANGE_UNSUPPORTED)
@dataclass
class PasswordChangeUnsupportedEvent(IpcEvent):
    """Signals that password change is unavailable for plaintext storage."""

    event_type: EventType = field(
        default=EventType.PASSWORD_CHANGE_UNSUPPORTED,
        init=False,
    )


@register_event(EventType.INVALID_NEW_PASSWORD)
@dataclass
class InvalidNewPasswordEvent(IpcEvent):
    """Signals that a replacement password fails validation."""

    event_type: EventType = field(
        default=EventType.INVALID_NEW_PASSWORD,
        init=False,
    )


@register_event(EventType.PASSWORD_CHANGE_FAILED)
@dataclass
class PasswordChangeFailedEvent(IpcEvent):
    """Signals that password-keyslot replacement could not be committed."""

    event_type: EventType = field(
        default=EventType.PASSWORD_CHANGE_FAILED,
        init=False,
    )


@register_event(EventType.DAEMON_UNLOCKED)
@dataclass
class DaemonUnlockedEvent(IpcEvent):
    """Signals that the daemon was unlocked successfully."""

    event_type: EventType = field(default=EventType.DAEMON_UNLOCKED, init=False)


@register_event(EventType.DAEMON_LOCKED)
@dataclass
class DaemonLockedEvent(IpcEvent):
    """Signals that the daemon is locked."""

    event_type: EventType = field(default=EventType.DAEMON_LOCKED, init=False)


@register_event(EventType.DAEMON_OFFLINE)
@dataclass
class DaemonOfflineEvent(IpcEvent):
    """Signals that no local daemon is running."""

    event_type: EventType = field(default=EventType.DAEMON_OFFLINE, init=False)


@register_event(EventType.IPC_CLIENT_LIMIT_REACHED)
@dataclass
class IpcClientLimitReachedEvent(IpcEvent):
    """Signals that the daemon rejected a new IPC session due to client saturation."""

    max_clients: int
    event_type: EventType = field(
        default=EventType.IPC_CLIENT_LIMIT_REACHED,
        init=False,
    )


@register_event(EventType.UNKNOWN_COMMAND)
@dataclass
class UnknownCommandEvent(IpcEvent):
    """Signals that the daemon received an unknown command."""

    event_type: EventType = field(default=EventType.UNKNOWN_COMMAND, init=False)


@register_event(EventType.PROTOCOL_MISMATCH)
@dataclass
class ProtocolMismatchEvent(IpcEvent):
    """Signals that the client and daemon IPC ranges do not overlap."""

    daemon_current_version: int
    daemon_min_supported: int
    client_current_version: int
    client_min_supported: int
    event_type: EventType = field(
        default=EventType.PROTOCOL_MISMATCH,
        init=False,
    )


@register_event(EventType.INTERNAL_ERROR)
@dataclass
class InternalErrorEvent(IpcEvent):
    """Signals that the daemon hit an unexpected internal error."""

    event_type: EventType = field(default=EventType.INTERNAL_ERROR, init=False)


@register_event(EventType.INVALID_SETTING_KEY)
@dataclass
class InvalidSettingKeyEvent(IpcEvent):
    """Signals that a setting key was invalid."""

    event_type: EventType = field(default=EventType.INVALID_SETTING_KEY, init=False)


@register_event(EventType.INVALID_CONFIG_KEY)
@dataclass
class InvalidConfigKeyEvent(IpcEvent):
    """Signals that a configuration key was invalid."""

    event_type: EventType = field(default=EventType.INVALID_CONFIG_KEY, init=False)


@register_event(EventType.CLIENT_SCOPE_KEY_REJECTED)
@dataclass
class ClientScopeKeyRejectedEvent(IpcEvent):
    """Signals that a client-scope setting or config key was routed to the daemon."""

    key: str = ''

    event_type: EventType = field(
        default=EventType.CLIENT_SCOPE_KEY_REJECTED,
        init=False,
    )


@register_event(EventType.SETTING_UPDATED)
@dataclass
class SettingUpdatedEvent(IpcEvent):
    """Signals that a global setting was updated."""

    key: str
    event_type: EventType = field(default=EventType.SETTING_UPDATED, init=False)


@register_event(EventType.SETTING_UPDATE_FAILED)
@dataclass
class SettingUpdateFailedEvent(IpcEvent):
    """Signals that a global setting update failed."""

    event_type: EventType = field(
        default=EventType.SETTING_UPDATE_FAILED,
        init=False,
    )


@register_event(EventType.SETTING_TYPE_ERROR)
@dataclass
class SettingTypeErrorEvent(IpcEvent):
    """Signals a type mismatch while applying a setting value."""

    key: Optional[str] = None
    reason: Optional[str] = None
    event_type: EventType = field(default=EventType.SETTING_TYPE_ERROR, init=False)


@register_event(EventType.SETTING_DATA)
@dataclass
class SettingDataEvent(IpcEvent):
    """Returns a global setting value."""

    key: str
    value: str
    event_type: EventType = field(default=EventType.SETTING_DATA, init=False)


@register_event(EventType.CONFIG_UPDATED)
@dataclass
class ConfigUpdatedEvent(IpcEvent):
    """Signals that a profile-specific config override was updated."""

    key: str
    event_type: EventType = field(default=EventType.CONFIG_UPDATED, init=False)


@register_event(EventType.CONFIG_UPDATE_FAILED)
@dataclass
class ConfigUpdateFailedEvent(IpcEvent):
    """Signals that a config update failed."""

    event_type: EventType = field(
        default=EventType.CONFIG_UPDATE_FAILED,
        init=False,
    )


@register_event(EventType.CONFIG_DATA)
@dataclass
class ConfigDataEvent(IpcEvent):
    """Returns a profile-specific config value."""

    key: str
    value: str
    event_type: EventType = field(default=EventType.CONFIG_DATA, init=False)


@register_event(EventType.CONFIG_SYNCED)
@dataclass
class ConfigSyncedEvent(IpcEvent):
    """Signals that profile config overrides were cleared."""

    event_type: EventType = field(default=EventType.CONFIG_SYNCED, init=False)
