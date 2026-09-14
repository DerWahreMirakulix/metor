"""Immutable permissions for one authenticated client restriction cycle."""

from dataclasses import dataclass
from typing import Optional

from metor.core.api import (
    ClientUnlockMethod,
    LockedAcceptPolicy,
    NotificationPrivacy,
)


@dataclass(frozen=True)
class RestrictedSessionPolicy:
    """Immutable permissions and privacy for one restricted lock cycle."""

    unlock_method: ClientUnlockMethod
    continued_live_target: Optional[str]
    live_while_locked: bool
    accept_while_locked: LockedAcceptPolicy
    notification_privacy: NotificationPrivacy
    continued_live_context: object | None = None
    device_lifecycle: bool = False
    continued_live_generation: Optional[int] = None
