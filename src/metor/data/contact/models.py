"""Typed contact-domain models returned by the address-book service."""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


ContactResultValue = str | int
ContactResultParams = Mapping[str, ContactResultValue]


@dataclass(frozen=True)
class ContactRecord:
    """Represents one alias-to-onion mapping in the local address book."""

    alias: str
    onion: str


@dataclass(frozen=True)
class ContactsSnapshot:
    """Represents the current saved and discovered contact sets."""

    saved: tuple[ContactRecord, ...]
    discovered: tuple[ContactRecord, ...]
    profile: str


@dataclass(frozen=True)
class ContactAliasChange:
    """Represents one alias rename side effect that must be broadcast to UIs."""

    old_alias: str
    new_alias: str
    onion: str
    was_saved: bool


@dataclass(frozen=True)
class ContactRemoval:
    """Represents one removed peer that must be broadcast to UIs."""

    alias: str
    onion: str


class ContactOperationType(str, Enum):
    """Enumeration of contact-domain outcomes independent from IPC events."""

    ALIAS_IN_USE = 'alias_in_use'
    ALIAS_NOT_FOUND = 'alias_not_found'
    ALIAS_RENAMED = 'alias_renamed'
    ALIAS_SAME = 'alias_same'
    CONTACT_ADDED = 'contact_added'
    CONTACT_ALREADY_SAVED = 'contact_already_saved'
    CONTACT_DOWNGRADED = 'contact_downgraded'
    CONTACT_REMOVED = 'contact_removed'
    CONTACT_REMOVED_DOWNGRADED = 'contact_removed_downgraded'
    CONTACTS_CLEARED = 'contacts_cleared'
    CONTACTS_CLEAR_FAILED = 'contacts_clear_failed'
    DISCOVERED_PEER_NOT_FOUND = 'discovered_peer_not_found'
    ONION_IN_USE = 'onion_in_use'
    PEER_ANONYMIZED = 'peer_anonymized'
    PEER_CANT_DELETE_ACTIVE = 'peer_cant_delete_active'
    PEER_NOT_FOUND = 'peer_not_found'
    PEER_PROMOTED = 'peer_promoted'
    PEER_REMOVED = 'peer_removed'


@dataclass(frozen=True)
class ContactOperationResult:
    """Represents one typed address-book mutation result."""

    success: bool
    operation_type: ContactOperationType
    params: ContactResultParams
    renames: tuple[ContactAliasChange, ...] = ()
    removals: tuple[ContactRemoval, ...] = ()
