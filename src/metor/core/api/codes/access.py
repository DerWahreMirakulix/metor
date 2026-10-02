"""Restricted client-session and quick-unlock policy enums."""

from enum import Enum


class ClientUnlockMethod(str, Enum):
    """Configured method for reauthorizing one restricted client."""

    PIN = 'pin'
    PROFILE_PASSWORD = 'profile_password'
    NONE = 'none'


class NotificationPrivacy(str, Enum):
    """Identity metadata visible to one restricted client."""

    SHOW_ALL = 'show_all'
    ANONYMIZE = 'anonymize'
    OFF = 'off'


class QuickUnlockAction(str, Enum):
    """Supported quick-unlock credential mutations."""

    SET = 'set'
    REMOVE = 'remove'
