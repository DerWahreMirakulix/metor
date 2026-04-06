"""Shared support logic for the modular database command handlers."""

from typing import Callable, List, Optional

from metor.core.api import (
    ContactRemovedEvent,
    HistoryEntryActor,
    HistoryEntryFamily,
    HistoryEntryReasonCode,
    HistoryEntryTrigger,
    HistoryRawEventCode,
    IpcEvent,
    RawHistoryEntry,
    RenameSuccessEvent,
    SummaryHistoryEntry,
    HistorySummaryEventCode,
)
from metor.data import ContactManager, HistoryManager, MessageManager
from metor.data.contact import ContactAliasChange, ContactRemoval
from metor.data.history import (
    HistoryLedgerEntry as DataHistoryLedgerEntry,
    HistorySummaryEntry as DataHistorySummaryEntry,
)
from metor.data.profile import ProfileManager


class DatabaseCommandHandlerSupportMixin:
    """Provides shared attributes and helper methods for database handler mixins."""

    _pm: ProfileManager
    _cm: ContactManager
    _hm: HistoryManager
    _mm: MessageManager
    _get_active_onions: Callable[[], List[str]]
    _broadcast: Callable[[IpcEvent], None]

    def _build_raw_history_entry(
        self,
        entry: DataHistoryLedgerEntry,
    ) -> RawHistoryEntry:
        """
        Converts one raw data-layer history row into its IPC DTO form.

        Args:
            entry (DataHistoryLedgerEntry): The raw history row.

        Returns:
            RawHistoryEntry: The IPC DTO entry.
        """
        peer_onion: Optional[str] = entry.peer_onion
        return RawHistoryEntry(
            timestamp=entry.timestamp,
            family=HistoryEntryFamily(entry.family.value),
            event_code=HistoryRawEventCode(entry.event_code.value),
            peer_onion=peer_onion,
            actor=HistoryEntryActor(entry.actor.value),
            trigger=(
                HistoryEntryTrigger(entry.trigger.value)
                if entry.trigger is not None
                else None
            ),
            detail_code=(
                HistoryEntryReasonCode(entry.detail_code.value)
                if entry.detail_code is not None
                else None
            ),
            detail_text=entry.detail_text,
            flow_id=entry.flow_id,
            alias=self._cm.require_alias_by_onion(peer_onion) if peer_onion else None,
        )

    def _build_summary_history_entry(
        self,
        entry: DataHistorySummaryEntry,
    ) -> SummaryHistoryEntry:
        """
        Converts one summary data-layer history row into its IPC DTO form.

        Args:
            entry (DataHistorySummaryEntry): The projected history row.

        Returns:
            SummaryHistoryEntry: The IPC DTO entry.
        """
        peer_onion: Optional[str] = entry.peer_onion
        return SummaryHistoryEntry(
            timestamp=entry.timestamp,
            family=HistoryEntryFamily(entry.family.value),
            event_code=HistorySummaryEventCode(entry.event_code.value),
            peer_onion=peer_onion,
            actor=HistoryEntryActor(entry.actor.value),
            trigger=(
                HistoryEntryTrigger(entry.trigger.value)
                if entry.trigger is not None
                else None
            ),
            detail_code=(
                HistoryEntryReasonCode(entry.detail_code.value)
                if entry.detail_code is not None
                else None
            ),
            detail_text=entry.detail_text,
            flow_id=entry.flow_id,
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
