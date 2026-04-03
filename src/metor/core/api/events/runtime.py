"""Runtime, auth, settings, and config IPC event DTOs."""

from dataclasses import dataclass, field
from typing import Optional

# Local Package Imports
from metor.core.api.base import IpcEvent
from metor.core.api.codes import EventType
from metor.core.api.registry import register_event


@register_event(EventType.AUTH_REQUIRED)
@dataclass
class AuthRequiredEvent(IpcEvent):
    """Signals that the session must authenticate first."""

    event_type: EventType = field(default=EventType.AUTH_REQUIRED, init=False)


@register_event(EventType.INVALID_PASSWORD)
@dataclass
class InvalidPasswordEvent(IpcEvent):
    """Signals that the supplied password was invalid."""

    event_type: EventType = field(default=EventType.INVALID_PASSWORD, init=False)


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


@register_event(EventType.SELF_DESTRUCT_INITIATED)
@dataclass
class SelfDestructInitiatedEvent(IpcEvent):
    """Signals that daemon self-destruction has started."""

    event_type: EventType = field(
        default=EventType.SELF_DESTRUCT_INITIATED,
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


@register_event(EventType.UNKNOWN_COMMAND)
@dataclass
class UnknownCommandEvent(IpcEvent):
    """Signals that the daemon received an unknown command."""

    event_type: EventType = field(default=EventType.UNKNOWN_COMMAND, init=False)


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


@register_event(EventType.DAEMON_CANNOT_MANAGE_UI)
@dataclass
class DaemonCannotManageUiEvent(IpcEvent):
    """Signals that a UI-only setting was routed to the daemon."""

    event_type: EventType = field(
        default=EventType.DAEMON_CANNOT_MANAGE_UI,
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
