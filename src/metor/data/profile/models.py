"""
Module defining data models and enumerations for profile configurations.
Enforces strict typing for profile-level settings to prevent key collisions.
"""

from enum import Enum
from typing import Dict, Union

from metor.data import SettingValue


# Types
ProfileConfigValue = Union[SettingValue, None]
NestedConfigDict = Dict[str, Union[ProfileConfigValue, Dict[str, ProfileConfigValue]]]


class ProfileConfigKey(str, Enum):
    """Keys strictly reserved for profile-specific internal states, NOT global overrides."""

    IS_REMOTE = 'is_remote'
    DAEMON_PORT = 'daemon_port'
