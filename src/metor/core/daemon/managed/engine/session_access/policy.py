"""Immutable permissions for one authenticated client restriction cycle."""

from dataclasses import dataclass

from metor.core.api import ClientUnlockMethod, NotificationPrivacy


@dataclass(frozen=True)
class RestrictedSessionPolicy:
    """Contains no chat or message-media permission, even for an active LIVE chat."""

    unlock_method: ClientUnlockMethod
    notification_privacy: NotificationPrivacy
    accept_calls_locked: bool = False
    device_lifecycle: bool = False
