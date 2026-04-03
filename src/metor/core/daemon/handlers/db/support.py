"""Shared support logic for the modular database command handlers."""

from typing import Callable, List, Optional, cast

from metor.core.api import (
    ContactRemovedEvent,
    HistoryEntry,
    IpcEvent,
    RenameSuccessEvent,
)
from metor.data import ContactManager, HistoryManager, MessageManager
from metor.data.contact import ContactAliasChange, ContactRemoval
from metor.data.profile import ProfileManager


class DatabaseCommandHandlerSupportMixin:
    """Provides shared attributes and helper methods for database handler mixins."""

    _pm: ProfileManager
    _cm: ContactManager
    _hm: HistoryManager
    _mm: MessageManager
    _get_active_onions: Callable[[], List[str]]
    _broadcast: Callable[[IpcEvent], None]

    def _build_history_entry(self, entry: object) -> HistoryEntry:
        """
        Converts one data-layer history row into its IPC DTO form.

        Args:
            entry (object): The typed history row object.

        Returns:
            HistoryEntry: The IPC DTO entry.
        """
        peer_onion: Optional[str] = cast(Optional[str], getattr(entry, 'peer_onion'))
        return HistoryEntry(
            timestamp=str(getattr(entry, 'timestamp')),
            family=str(getattr(entry, 'family')),
            event_code=str(getattr(entry, 'event_code')),
            peer_onion=peer_onion,
            actor=str(getattr(entry, 'actor')),
            trigger=cast(Optional[str], getattr(entry, 'trigger')),
            detail_code=cast(Optional[str], getattr(entry, 'detail_code')),
            detail_text=str(getattr(entry, 'detail_text')),
            flow_id=str(getattr(entry, 'flow_id')),
            alias=self._cm.require_alias_by_onion(peer_onion) if peer_onion else None,
        )

    def _emit_contact_side_effects(
        self,
        renames: tuple[ContactAliasChange, ...],
        removals: tuple[ContactRemoval, ...],
    ) -> None:
        """
        Broadcasts contact rename and removal side effects to attached UIs.

        Args:
            renames (tuple[ContactAliasChange, ...]): Alias change side effects.
            removals (tuple[ContactRemoval, ...]): Removal side effects.

        Returns:
            None
        """
        for rename in renames:
            self._broadcast(
                RenameSuccessEvent(
                    old_alias=rename.old_alias,
                    new_alias=rename.new_alias,
                    onion=rename.onion,
                    is_demotion=True,
                    was_saved=rename.was_saved,
                )
            )

        for removal in removals:
            self._broadcast(
                ContactRemovedEvent(
                    alias=removal.alias,
                    onion=removal.onion,
                    profile=self._pm.profile_name,
                )
            )

    def _emit_orphan_cleanup(self, removed_peers: List[tuple[str, str]]) -> None:
        """
        Broadcasts discovered-peer removals produced by orphan cleanup.

        Args:
            removed_peers (List[tuple[str, str]]): Removed alias/onion pairs.

        Returns:
            None
        """
        for alias, onion in removed_peers:
            self._broadcast(
                ContactRemovedEvent(
                    alias=alias,
                    onion=onion,
                    profile=self._pm.profile_name,
                )
            )
