"""Optional public host interface for bounded local profile catalog and management."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from metor.shared import Constants

# Local Package Imports
from .frontends import (
    FrontendProfileCreateRequest,
    FrontendProfileOperationResult,
    FrontendProfileState,
    OneUseSecretProvider,
)


def valid_frontend_profile_name(value: str) -> bool:
    """Checks exact names against the base catalog's canonical character set.

    Args:
        value: Untrusted profile name or catalog bookmark.
    Returns:
        bool: Whether the bounded name needs no filesystem-path normalization.
    """
    return (
        isinstance(value, str)
        and 0 < len(value) <= Constants.FRONTEND_PROFILE_NAME_CHARACTERS
        and all(character.isalnum() or character in '-_' for character in value)
    )


class FrontendProfileAction(str, Enum):
    """Explicit local catalog mutations; transport and profile purge are separate."""

    SET_DEFAULT = 'set_default'
    RENAME = 'rename'
    REMOVE = 'remove'


@dataclass(frozen=True)
class FrontendProfileChange:
    """Captures a catalog target and the host selection shown during confirmation."""

    action: FrontendProfileAction
    profile: str
    selected_profile: str
    new_name: str | None = None

    def __post_init__(self) -> None:
        """Rejects ambiguous path-like targets before the host can touch profile files.

        Args:
            None
        Returns:
            None
        """
        if (
            not isinstance(self.action, FrontendProfileAction)
            or not valid_frontend_profile_name(self.profile)
            or not valid_frontend_profile_name(self.selected_profile)
        ):
            raise ValueError('Invalid profile change')
        if self.action is FrontendProfileAction.RENAME:
            if self.new_name is None or not valid_frontend_profile_name(self.new_name):
                raise ValueError('Invalid new profile name')
        elif self.new_name is not None:
            raise ValueError('Unexpected new profile name')


@dataclass(frozen=True)
class FrontendProfileCatalog:
    """One finite metadata page; no paths, keys, credentials or remote host internals."""

    entries: tuple[FrontendProfileState, ...]
    selected_profile: str
    default_profile: str
    next_after: str | None = None


@runtime_checkable
class FrontendProfileManagement(Protocol):
    """Optional base-owned management extension; ordinary launch hosts stay valid."""

    def profile_catalog(
        self,
        after: str | None = None,
        limit: int = Constants.FRONTEND_PROFILE_PAGE_ITEMS,
    ) -> FrontendProfileCatalog:
        """Reads one bounded page without starting or authenticating any runtime.

        Args:
            after: Exclusive profile-name bookmark, or the first page.
            limit: Finite page size within the shared host bound.
        Returns:
            FrontendProfileCatalog: Local selected/default state and page entries.
        """
        ...

    def manage_profile(
        self, change: FrontendProfileChange
    ) -> FrontendProfileOperationResult:
        """Applies a user-confirmed catalog mutation through existing base eligibility.

        Args:
            change: Original selected-host context and exact target.
        Returns:
            FrontendProfileOperationResult: Actual success or safe refusal code.
        """
        ...

    def create_profile_entry(
        self,
        request: FrontendProfileCreateRequest,
        secret: OneUseSecretProvider | None = None,
    ) -> FrontendProfileOperationResult:
        """Creates a profile while preserving the host's current selection.

        Args:
            request: Explicit non-secret creation inputs.
            secret: One-use creation secret, consumed even on refusal.
        Returns:
            FrontendProfileOperationResult: Actual creation result, without activation.
        """
        ...
