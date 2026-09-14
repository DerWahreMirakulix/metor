"""Strict public values for the protected per-profile GUI preference namespace."""

from dataclasses import dataclass, field
from enum import Enum

from metor.shared import Constants, decode_tor_v3_onion_public_key

# Local Package Imports
from .codes import ClientUnlockMethod, LockedAcceptPolicy, NotificationPrivacy


class GuiPreferenceFailure(str, Enum):
    """Stable non-sensitive outcomes of protected preference operations."""

    UNAVAILABLE = 'unavailable'
    UNSUPPORTED = 'unsupported'
    FULL_AUTH_REQUIRED = 'full_auth_required'
    CONFLICT = 'conflict'
    PROTECTED_STORAGE_UNAVAILABLE = 'protected_storage_unavailable'
    INVALID_PREFERENCES = 'invalid_preferences'
    PIN_UNAVAILABLE = 'pin_unavailable'


@dataclass
class GuiPreferences:
    """Minimal policy and peer-ID ordering; contains no aliases or message content."""

    pins: list[str] = field(default_factory=list)
    auto_play: bool = False
    keep_live_locked: bool = False
    accept_live_locked: LockedAcceptPolicy = LockedAcceptPolicy.NONE
    notifications_locked: NotificationPrivacy = NotificationPrivacy.ANONYMIZE
    unlock_method: ClientUnlockMethod = ClientUnlockMethod.PROFILE_PASSWORD
    idle_seconds: int = Constants.GUI_DEFAULT_IDLE_SECONDS
    show_profile_locked: bool = False
    keyboard_layout: str = 'qwerty'
    setup_complete: bool = False

    def __post_init__(self) -> None:
        """Rejects invalid policy, resource limits and noncanonical peer identities.

        Args:
            None
        Returns:
            None
        """
        for value in (
            self.auto_play,
            self.keep_live_locked,
            self.show_profile_locked,
            self.setup_complete,
        ):
            if type(value) is not bool:
                raise ValueError('GUI preference requires a Boolean')
        if (
            type(self.idle_seconds) is not int
            or not 0 <= self.idle_seconds <= Constants.GUI_MAX_IDLE_SECONDS
        ):
            raise ValueError('Invalid GUI idle timeout')
        if self.keyboard_layout not in ('qwerty', 'qwertz'):
            raise ValueError('Unsupported GUI keyboard layout')
        self.accept_live_locked = LockedAcceptPolicy(self.accept_live_locked)
        self.notifications_locked = NotificationPrivacy(self.notifications_locked)
        self.unlock_method = ClientUnlockMethod(self.unlock_method)
        if not isinstance(self.pins, list) or len(self.pins) > Constants.GUI_MAX_PINS:
            raise ValueError('GUI pin limit exceeded')
        known: set[str] = set()
        for peer in self.pins:
            if (
                not isinstance(peer, str)
                or len(peer) != Constants.TOR_V3_ONION_ADDRESS_LENGTH
                or peer in known
                or peer != peer.lower()
            ):
                raise ValueError('Invalid GUI pin identity')
            decode_tor_v3_onion_public_key(peer)
            known.add(peer)
