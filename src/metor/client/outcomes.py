"""Explicit nonterminal and rejection classifications for correlated SDK exchanges."""

from metor.core.api import EventType, IpcEvent


PROGRESS_EVENTS = frozenset(
    {
        EventType.FALLBACK_SUCCESS,
        EventType.VOICE_RESOURCE_PRESSURE,
        EventType.RUNTIME_STATE_CHANGED,
        EventType.LIVE_MESSAGE_RESOURCE_PRESSURE,
        EventType.AUTO_FALLBACK_QUEUED,
    }
)
REJECTION_EVENTS = frozenset(
    {
        EventType.VOICE_OPERATION_REJECTED,
        EventType.VOICE_RESOURCE_LIMIT,
        EventType.FALLBACK_REJECTED,
        EventType.LIVE_MESSAGE_UNAVAILABLE,
        EventType.INTERNAL_ERROR,
        EventType.UNKNOWN_COMMAND,
        EventType.CLIENT_ACCESS_RESTRICTED,
        EventType.PEER_NOT_FOUND,
        EventType.INVALID_TARGET,
        EventType.NO_PENDING_LIVE_MSGS,
        EventType.IPC_CLIENT_LIMIT_REACHED,
        EventType.DAEMON_OFFLINE,
        EventType.INVALID_PASSWORD,
        EventType.LOCAL_AUTH_RATE_LIMITED,
        EventType.INVALID_SETTING_KEY,
        EventType.INVALID_CONFIG_KEY,
        EventType.CLIENT_SCOPE_KEY_REJECTED,
        EventType.SETTING_UPDATE_FAILED,
        EventType.SETTING_TYPE_ERROR,
        EventType.CONFIG_UPDATE_FAILED,
        EventType.DB_CORRUPTED,
        EventType.PASSWORD_CHANGE_FAILED,
        EventType.PASSWORD_CHANGE_UNSUPPORTED,
        EventType.INVALID_NEW_PASSWORD,
        EventType.NO_PENDING_CONNECTION,
        EventType.MAX_CONNECTIONS_REACHED,
        EventType.NO_CONNECTION_TO_REJECT,
        EventType.NO_CONNECTION_TO_DISCONNECT,
        EventType.DROPS_DISABLED,
        EventType.CANNOT_DROP_SELF,
        EventType.CANNOT_CONNECT_SELF,
        EventType.CANNOT_SWITCH_SELF,
    }
)


class MetorProtocolError(RuntimeError):
    """A valid wire DTO is incompatible with this correlated exchange's contract."""

    def __init__(self, event: IpcEvent) -> None:
        """Retains the incompatible DTO without misrepresenting it as rejection."""
        super().__init__(f'Unexpected correlated response: {event.event_type.value}.')
        self.event = event
