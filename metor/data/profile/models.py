from enum import Enum


class ProfileConfigKey(str, Enum):
    """Keys for the profile-specific config.json."""

    IS_REMOTE = 'is_remote'
    DAEMON_PORT = 'daemon_port'
